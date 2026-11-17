"""Station Assistant — retrieval + analysis + local LLM + agent coordination
over the live session.

Questions about the shift ("why did DEA drop?", "what's the status of the
ferries?", "how many VETs were accepted?", "volume for tomorrow?") are answered
by (1) a deterministic analysis of the live twin (app/runtime/explain.py:
root causes, decisions taken and their simulated impact), (2) retrieval over a
shift knowledge base rebuilt from live state (app/runtime/knowledge.py), and
(3) optionally a local-LLM summary grounded in those numbered facts — whose
numbers are checked against the facts and dropped if any are unsupported.
Follow-ups ("why?", "what did you do about it?") reuse the last topic.

Understands two kinds of message:
- **questions** ("how's stow WIP?", "which drivers are late?", "where is
  R-012?", "what's at risk?") — answered from live twin state, with numbers
  computed deterministically, never generated;
- **requests** ("fix stow WIP", "protect OTD", "prioritise R-012", "move
  R-031 to the next wave", "notify late drivers", "VET 3 stowers", "simulate a
  jam on line 2", "what if we extend pick start 15 min?") — routed to the
  multi-agent orchestrator (goals) or applied directly to the *simulated*
  station, always reported with the effect that actually happened.

Understanding is a deterministic intent parser first (predictable, testable).
Only if nothing matches, and a local LLM is available, the LLM may *classify*
the message into the same closed set of intents (schema-restricted, ADR-0008)
— it never invents an action outside that set, and never produces numbers.
"""

import re
import time
from typing import Literal

from pydantic import BaseModel

from app.agents.station_ops.counterfactual import applied_log, belief_configs, evaluate_prepared
from app.agents.station_ops.detectors import AGENT_LABEL, detect_risks
from app.agents.station_ops.mitigations import Candidate
from app.core.llm.base import LLMProvider, LLMProviderError
from app.runtime import explain, explain_v2
from app.runtime.knowledge import Index, build_corpus
from app.runtime.session import StationSession
from app.simulation.station_ops.model import Intervention
from app.simulation.station_ops.snapshot import METRIC_DEFINITIONS, build_snapshot

Intent = Literal[
    "help",
    "summary",
    "metric",
    "risks",
    "route_status",
    "drivers",
    "linehauls",
    "labor",
    "high_value",
    "tomorrow",
    "floor",
    "yard",
    "explain",
    "ask",
    "fix_wip",
    "protect_dea",
    "protect_otd",
    "action",
    "what_if",
    "control",
    "approve",
    "dismiss",
    "unknown",
]

ROUTE_RE = re.compile(r"\bR-?(\d{1,3})\b", re.I)
NUM_RE = re.compile(r"(\d+)")
_METRIC_WORDS = {
    "dea": ("dea", "delivery estimate"),
    "otd": ("otd", "on-time departure", "on time departure"),
    "sort_compliance": ("sort compliance",),
    "timely_staged": ("timely staged", "staging"),
    "scan_compliance": ("scan compliance", "no-read", "no read"),
    "stow_wip_compliance": ("wip compliance",),
    "induct_fph": ("fph", "induct rate"),
    "stow_pph": ("stow rate", "pph"),
    "lost_hours": ("lost hours", "downtime"),
    "hv_custody_compliance": ("custody",),
    "swipe_compliance": ("swipe",),
    "rts_rate": ("rts", "return to station"),
}
_ROLES = {
    "stow": "stow",
    "stower": "stow",
    "pick": "pick",
    "picker": "pick",
    "problem": "problem_solve",
    "hv": "high_value",
    "high value": "high_value",
    "induct": "induct",
}


class ChatReply(BaseModel):
    reply: str
    intent: Intent
    actions: list[dict] = []
    data: dict = {}
    understood_by: Literal["rules", "llm", "none"] = "rules"
    #: Rich answers: a title, sections of computed lines, and cited sources.
    title: str | None = None
    sections: list[dict] = []
    sources: list[dict] = []
    #: Local-LLM summary of the facts (evidence category: inferred), only when
    #: every number in it is found in the facts; otherwise withheld.
    llm_summary: str | None = None
    llm_status: Literal["grounded", "withheld", "unavailable", "skipped"] = "skipped"


class GroundedAnswer(BaseModel):
    """What the LLM may return: prose over the numbered facts, citing them."""

    answer: str
    cited_facts: list[int] = []
    category: Literal["inferred"] = "inferred"


_NUM = re.compile(r"\d{1,2}:\d{2}|\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM.findall(text):
        if ":" in m:
            h, mm = m.split(":")
            out.add(f"t{int(h)}:{mm}")
        else:
            v = float(m.replace(",", ""))
            out.add(f"{v:g}")
    return out


def grounded(answer: str, facts: list[str]) -> bool:
    """Every number the LLM wrote must appear in the facts (times exactly,
    values to the same digits after rounding); small counts ≤ 2 are allowed."""
    have = set().union(*(_numbers(f) for f in facts)) if facts else set()
    vals = {float(x) for x in have if not x.startswith("t")}
    for n in _numbers(answer):
        if n in have:
            continue
        if n.startswith("t"):
            return False
        v = float(n)
        if v <= 2 or any(abs(v - h) < 0.051 or abs(v - round(h)) < 1e-9 for h in vals):
            continue
        return False
    return True


_TOPICS = (
    ("dea", r"\b(dea|delivery estimate|rollover|rolled over|roll over|missed packages?)\b"),
    ("otd", r"\b(otd|on.time depart\w*|departures?|left late|late routes?)\b"),
    # v2 topics (HANDOFF_V2 §10.1) — specific before generic
    (
        "labor_plan",
        r"\b(covered|coverage|by hour|hourly|headcount by|staffed between|short between)\b",
    ),
    ("rotation", r"\b(rotation|disallowed|trained paths?|can'?t do|cannot do)\b"),
    (
        "quality",
        r"\b(which line|lines? hurt|hurt us|no.?reads?|multi.?reads?|misapplied|lost hours|downtime|dpmo|quality)\b",
    ),
    ("stow_wip", r"\b(stow ?wip|wip|out of band)\b"),
    ("fingers", r"\b(fingers?|full bays?|bays? full)\b"),
    ("containers", r"\b(gaylords?|pallets?|containers?)\b"),
    ("receive", r"\b(unplanned|planned volume|manifest\w*|receive)\b"),
    (
        "plan_actual",
        r"\b(on plan|plan vs\.? actual|planned vs|vs\.? plan|behind plan|ahead of plan)\b",
    ),
    ("work_items", r"\b(work items?|expired|to.?do list|open tasks?|pending tasks?)\b"),
    (
        "ageing",
        r"\b(ageing|aging|missing packages?|lost packages?|marked (as )?(missing|lost)|scrubs?)\b",
    ),
    (
        "cycles",
        r"\b(pick start|cycles?|force.?induct\w*|change.?cycle|wrong.?cycle|induct (is |was )?blocked)\b",
    ),
    (
        "trucks",
        r"\b(truck ?file|trucks?|ferr(y|ies)|linehauls?|trailers?|sailings?|gtdrs?|ports?)\b",
    ),
    (
        "labor",
        r"\b(vets?|vtos?|associates?|headcount|labou?r|staff\w*|call(?:ed)?.?outs?|absent\w*)\b",
    ),
    ("tomorrow", r"\b(tomorrow|next day|next cycle|plan for|volume for)\b"),
    ("decisions", r"\b(decisions?|agents? (do|did)|what did (you|the agents)|actions taken)\b"),
    ("shift", r"\b(shift|today|the day|overall|how did (it|we|the day) go)\b"),
)
_QUESTION = re.compile(
    r"^(why|how|what|which|when|who|explain|tell me|describe|give me|show me|summari[sz]e|anything|"
    r"walk me|break ?down|any|is|are|did|was|were|status)\b|\b(why|cause[sd]?|reason|explain|"
    r"details?|status|update|breakdown)\b"
)
_FOLLOWUP = re.compile(
    r"^(why\??|and\b.*|what (did|have) (you|we|the agents) do.*|what was done.*|how come\??|"
    r"tell me more|more( details)?|go on|details\??|what else\??)$"
)


def topic_of(t: str) -> str | None:
    for name, rx in _TOPICS:
        if re.search(rx, t):
            return name
    return None


class LLMIntent(BaseModel):
    intent: Literal[
        "summary",
        "metric",
        "risks",
        "drivers",
        "linehauls",
        "labor",
        "high_value",
        "tomorrow",
        "floor",
        "yard",
        "fix_wip",
        "protect_dea",
        "protect_otd",
        "unknown",
    ]


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _route(msg: str) -> str | None:
    m = ROUTE_RE.search(msg)
    return f"R-{int(m.group(1)):03d}" if m else None


def _num(msg: str, default: int) -> int:
    m = NUM_RE.search(ROUTE_RE.sub("", msg))
    return int(m.group(1)) if m else default


def parse(msg: str) -> tuple[Intent, dict]:  # noqa: C901
    t = msg.lower().strip()
    route = _route(msg)
    if not t or t in ("help", "?") or "what can you" in t:
        return "help", {}
    if re.search(r"\b(approve|accept)\b", t):
        return "approve", {"all": "all" in t, "id": _num(t, -1)}
    if re.search(r"\b(dismiss|reject)\b", t):
        return "dismiss", {"all": "all" in t, "id": _num(t, -1)}
    if re.search(
        r"\b(pause|resume|faster|slower|speed|autopilot|copilot|advise mode|observe mode)\b", t
    ):
        return "control", {"text": t}
    if t.startswith("what if") or "what would happen" in t:
        return "what_if", {"text": t, "route": route}
    if re.search(r"\b(simulate|inject)\b", t):
        return "action", {"text": t, "route": route, "kind": "inject"}
    if "wip" in t and re.search(r"\b(fix|balance|correct|sort out|bring|adjust|handle)\b", t):
        return "fix_wip", {}
    if re.search(r"\b(protect|fix|improve|save|recover)\b", t) and re.search(
        r"\b(otd|departure|driver)", t
    ):
        return "protect_otd", {}
    if re.search(r"\b(protect|fix|improve|save|recover|prevent)\b", t) and re.search(
        r"\b(dea|rollover|roll over|backlog|induct|stow capacity|cycle)\b", t
    ):
        return "protect_dea", {}
    if re.search(
        r"\b(restage|sweep|replacement|replace|marshals?|check ferr\w*|re-?plan|offer|draft|"
        r"gtdrs? file|file gtdrs?|force.?induct|change (the )?cycle|enable (the )?(next )?cycle|"
        r"rebalance|approve damaged|post (a )?(vet|vto)|close (the )?(sign.?up )?windows?|"
        r"re-?run (the )?rotation|watch)\b",
        t,
    ) and not re.search(r"^(how|what|when|why|is|are|did|show)\b", t):
        return "action", {"text": t, "route": route}
    if re.search(
        r"\b(prioriti[sz]e|sideline|unsideline|move|notify|remind|standby|backup|vet|call in|"
        r"add|open|extend|scrub|resequence|unload first)\b",
        t,
    ):
        return "action", {"text": t, "route": route}
    topic = topic_of(t)
    if _FOLLOWUP.match(t) and not (topic and topic != "decisions"):
        return "explain", {"topic": topic, "followup": True, "text": t}
    if route:
        return "route_status", {"route": route}
    if topic and _QUESTION.search(t):
        return "explain", {"topic": topic, "text": t}
    if re.search(
        r"\b(tomorrow|next day|truck ?file|vto|gtdrs?|close-?out|roster|rotation|scrubs?)\b", t
    ):
        return "tomorrow", {}
    if re.search(r"\b(vsa|grounded|yard marshals?|safety audit|replacement vans?)\b", t):
        return "yard", {}
    if re.search(
        r"(misstag|wrong staging|left behind|sweep|cluster transfer|notifications?|floor)", t
    ):
        return "floor", {}
    if re.search(r"\b(risks?|issues?|problems?|alerts?|wrong|attention)\b", t):
        return "risks", {}
    if re.search(r"\b(drivers?|dsps?|vans?|swipes?)\b", t):
        return "drivers", {}
    if re.search(r"\b(trucks?|linehauls?|ferry|ferries|trailers?|yard|inbound)\b", t):
        return "linehauls", {}
    if re.search(r"\b(labor|labour|headcount|associates?|idle|staff|absent)\b", t):
        return "labor", {}
    if re.search(r"\b(high value|high-value|cage|hv)\b", t):
        return "high_value", {}
    for key, words in _METRIC_WORDS.items():
        if any(w in t for w in words):
            return "metric", {"metric": key}
    if "wip" in t:
        return "metric", {"metric": "wip"}
    if re.search(r"\b(status|summary|how are we|how is|overview|doing|update)\b", t):
        return "summary", {}
    if topic:
        return "explain", {"topic": topic, "text": t}
    if _QUESTION.search(t):
        return "ask", {"text": t}
    return "unknown", {}


class StationAssistant:
    def __init__(self, session: StationSession, llm: LLMProvider | None = None):
        self.s = session
        self.llm = llm

    def handle(self, message: str) -> ChatReply:
        intent, ent = parse(message)
        understood = "rules"
        if intent == "unknown" and self.llm is not None:
            try:
                got = self.llm.complete_structured(
                    system_prompt="Classify a station-operations chat message into one intent. "
                    "Reply only with JSON.",
                    user_prompt=message,
                    response_model=LLMIntent,
                    timeout_seconds=20,
                )
                if got.intent != "unknown":
                    intent, understood = got.intent, "llm"
            except LLMProviderError:
                pass
        if intent == "unknown":
            intent, ent = "ask", {"text": message.lower()}
        reply = getattr(self, f"_{intent}")(message, ent)
        reply.understood_by = understood
        if reply.intent == "explain" and reply.data.get("topic"):
            self.s.chat_context["topic"] = reply.data["topic"]
        self.s.chat_history.append({"role": "user", "text": message})
        self.s.chat_history.append(
            {
                "role": "assistant",
                "text": reply.reply,
                "intent": reply.intent,
                "actions": reply.actions,
                "title": reply.title,
                "sections": reply.sections,
                "sources": reply.sources,
                "llm_summary": reply.llm_summary,
                "llm_status": reply.llm_status,
            }
        )
        return reply

    # --- helpers -------------------------------------------------------------------

    def _snap(self):
        with self.s.lock:
            return build_snapshot(self.s.twin, 0)

    def _apply(self, iv: Intervention) -> dict:
        return self.s.act(iv.model_copy(update={"source": "chat"}))

    # --- questions -----------------------------------------------------------------

    def _help(self, msg, ent) -> ChatReply:
        return ChatReply(
            intent="help",
            reply=(
                "I can answer questions and act on the live (simulated) station. Try:\n"
                '• "status" · "what\'s at risk?" · "DEA" / "OTD" / "stow WIP" · "late drivers" · '
                '"late trucks" · "where is R-012?" · "labor" · "high value"\n'
                '• "fix stow WIP" · "protect DEA" · "protect OTD" — the agents plan and act\n'
                '• "prioritise R-012" · "move R-031 to the next wave" · "notify late drivers" · '
                '"standby for R-045" · "remind drivers to swipe" · "VET 3 stowers" · '
                '"move 1 problem solve to stow" · "open spare line" · "extend pick start 15" · '
                '"start in-station scrub"\n'
                '• Floor & yard: "restage R-012" · "sweep aisle A05" · "replacement van for R-031" '
                '· "add a yard marshal" · "any misstaged carts?" · "VSA status"\n'
                '• After dispatch: "plan for tomorrow" · "check ferry" · "re-plan tomorrow" · '
                '"offer VET to 3" · "offer VTO to 2" · "draft GTDRs"\n'
                '• "what if we VET 4 stowers?" — simulated, nothing applied\n'
                '• "simulate a jam on line 2" · "inject traffic incident south" · "pause" · '
                '"speed 5" · "approve all"'
            ),
        )

    def _summary(self, msg, ent) -> ChatReply:
        s = self._snap()
        m = s.metrics
        dea = m["dea"].value if s.done else m["dea_ceiling"].value
        risks = self.s.loop.current_risks
        txt = (
            f"{s.clock} · {s.phase.replace('_', ' ')} · {s.scenario}. "
            f"DEA {'final' if s.done else 'ceiling'} {_pct(dea)}, OTD {_pct(m['otd'].value)}, "
            f"sort compliance {_pct(m['sort_compliance'].value)}, timely staged "
            f"{_pct(m['timely_staged'].value)}. Stow WIP {s.stow['wip_minutes']:.1f} min "
            f"(band {s.stow['wip_target_min']:.0f}–{s.stow['wip_target_max']:.0f}). "
            f"{s.package_status['rolled_over']} rolled over, {s.outbound['departed']}/"
            f"{s.outbound['routes_total']} routes departed. "
            + (
                f"{len(risks)} open risk(s): "
                + "; ".join(r.risk_type.replace("_", " ") for r in risks[:4])
                + "."
                if risks
                else "No open risks."
            )
        )
        return ChatReply(intent="summary", reply=txt, data={"clock": s.clock})

    def _metric(self, msg, ent) -> ChatReply:
        s = self._snap()
        key = ent["metric"]
        if key == "wip":
            st = s.stow
            band = f"{st['wip_target_min']:.0f}–{st['wip_target_max']:.0f}"
            state = (
                "above"
                if st["wip_minutes"] > st["wip_target_max"]
                else "below"
                if st["wip_minutes"] < st["wip_target_min"]
                else "inside"
            )
            return ChatReply(
                intent="metric",
                reply=(
                    f"Stow WIP is {st['wip_minutes']:.1f} min of work ({st['wip_packages']} packages, "
                    f"{st['stowers']} stowers) — {state} the {band} min band. Est. WIP compliance so far "
                    f"{_pct(s.metrics['stow_wip_compliance'].value)}."
                    + (
                        ' Say "fix stow WIP" and the Sort & Stow agent will act.'
                        if state != "inside"
                        else ""
                    )
                ),
                data={"wip_minutes": st["wip_minutes"], "state": state},
            )
        mt = s.metrics.get(key)
        d = METRIC_DEFINITIONS.get(key, {})
        val = mt.value if mt else None
        shown = _pct(val) if mt and mt.unit == "ratio" else "—" if val is None else f"{val:,.0f}"
        if key == "dea" and not s.done:
            shown = f"{_pct(s.metrics['dea_ceiling'].value)} ceiling so far ({s.delivery['known_misses']} known misses)"
        return ChatReply(
            intent="metric",
            reply=(
                f"{d.get('label', key)}: {shown}"
                + (
                    f" (target {_pct(mt.target)})"
                    if mt and mt.target and mt.unit == "ratio"
                    else ""
                )
                + f". Definition ({d.get('status', 'proposed')}): {d.get('formula', '—')}."
            ),
            data={"metric": key, "value": val},
        )

    def _risks(self, msg, ent) -> ChatReply:
        with self.s.lock:
            risks = detect_risks(self.s.twin, build_snapshot(self.s.twin, 0))
        if not risks:
            return ChatReply(intent="risks", reply="No open risks detected right now.")
        lines = [f"• [{r.severity}] {AGENT_LABEL[r.agent]}: {r.summary}" for r in risks[:8]]
        return ChatReply(
            intent="risks",
            reply="Open risks:\n" + "\n".join(lines),
            data={"risks": [r.model_dump(mode="json") for r in risks]},
        )

    def _route_status(self, msg, ent) -> ChatReply:
        s = self._snap()
        r = next((x for x in s.routes if x["route_id"] == ent["route"]), None)
        if r is None:
            return ChatReply(intent="route_status", reply=f"I can't find {ent['route']}.")
        parts = [
            f"{r['route_id']} ({r['dsp']}, wave {r['wave']}, {r['staging_location']}): {r['status']}",
            f"stage-by {r['stage_by']}, planned depart {r['planned_depart']}",
            f"{r['spr']} packages, bags {r['bags_done']}/{r['bags_total']}",
        ]
        if r["picker"]:
            parts.append(f"picker {r['picker']}")
        if r["projected_stage_at"] and r["status"] in ("not_ready", "ready", "picking"):
            parts.append(
                f"projected staged {r['projected_stage_at']}"
                + (" ⚠ at risk" if r["at_risk"] else "")
            )
        if r["driver"]:
            parts.append(
                f"driver {r['driver']} ({r['driver_state']}"
                + (f", projected {r['driver_late_by']:.0f} min late" if r["driver_late_by"] else "")
                + ")"
            )
        if r["departed_at"]:
            parts.append(
                f"departed {r['departed_at']}"
                + (
                    f" ({r['depart_late_minutes']:.0f} min late)"
                    if r["depart_late_minutes"]
                    else " on time"
                )
            )
        return ChatReply(intent="route_status", reply="; ".join(parts) + ".", data={"route": r})

    def _drivers(self, msg, ent) -> ChatReply:
        s = self._snap()
        late = [r for r in s.routes if (r["driver_late_by"] or 0) > 0]
        departed = [r for r in s.routes if r["departed_at"]]
        late_dep = [r for r in departed if (r["depart_late_minutes"] or 0) > 0]
        txt = (
            f"{len(late)} driver(s) projected late for check-in"
            + (
                ": "
                + ", ".join(
                    f"{r['route_id']} {r['dsp']} +{r['driver_late_by']:.0f}m" for r in late[:8]
                )
                if late
                else ""
            )
            + f". {len(departed)} routes departed, {len(late_dep)} late. OTD {_pct(s.metrics['otd'].value)}"
            f" (vs original plan {_pct(s.metrics['otd_original_plan'].value)})."
        )
        if late:
            txt += ' Say "notify late drivers" or "protect OTD".'
        return ChatReply(intent="drivers", reply=txt, data={"late": [r["route_id"] for r in late]})

    def _linehauls(self, msg, ent) -> ChatReply:
        return self._explain(msg, {"topic": "trucks", "text": msg.lower()})

    def _labor(self, msg, ent) -> ChatReply:
        return self._explain(msg, {"topic": "labor", "text": msg.lower()})

    def _high_value(self, msg, ent) -> ChatReply:
        with self.s.lock:
            tw = self.s.twin
            hv = [p for p in tw.pkgs if p.hv]
            in_cage = sum(1 for p in hv if p.status == "hv_in_cage")
            queue = len(tw.hv_q)
            assoc = sum(1 for a in tw.assocs if a.present and a.role == "high_value")
        return ChatReply(
            intent="high_value",
            reply=(
                f"{len(hv)} high-value packages today: {in_cage} in the cage, {queue} HV tasks queued, "
                f"{assoc} HV associate(s). "
                + (
                    'Say "move 1 problem solve to high value" to reinforce the cage.'
                    if queue > 10
                    else "Cage flow looks healthy."
                )
            ),
        )

    # --- requests --------------------------------------------------------------------

    # --- explain (analysis + retrieval + grounded LLM) -------------------------------

    def _replay(self) -> dict | None:
        """Same day without any decisions — cached per (decisions so far)."""
        with self.s.lock:
            tw = self.s.twin
            if not tw.done:
                return None
            cfg, ivs, n = explain.replay_inputs(tw)
            key = (n, len(ivs))
            cache = self.s.chat_context.get("replay")
        if cache and cache[0] == key:
            return cache[1]
        out = explain.replay_without_decisions(cfg, ivs)
        self.s.chat_context["replay"] = (key, out)
        return out

    def _analysis(self, topic: str, text: str) -> explain.Analysis:
        replay = self._replay() if topic in ("dea", "otd") else None
        with self.s.lock:
            tw, loop = self.s.twin, self.s.loop
            if topic == "dea":
                return explain.dea(tw, loop, replay)
            if topic == "otd":
                return explain.otd(tw, loop, replay)
            if topic == "trucks":
                return explain.trucks(tw, text)
            if topic == "labor":
                return explain.labor(tw)
            if topic == "tomorrow":
                return explain.tomorrow(tw)
            v2 = {
                "labor_plan": lambda: explain_v2.labor_plan(tw, text),
                "rotation": lambda: explain_v2.rotation(tw, text),
                "quality": lambda: explain_v2.quality(tw),
                "stow_wip": lambda: explain_v2.stow_wip(tw, text),
                "fingers": lambda: explain_v2.fingers(tw),
                "containers": lambda: explain_v2.containers(tw),
                "receive": lambda: explain_v2.receive(tw),
                "plan_actual": lambda: explain_v2.plan_actual(tw, text),
                "work_items": lambda: explain_v2.work_items(tw),
                "ageing": lambda: explain_v2.ageing(tw),
                "cycles": lambda: explain_v2.cycles(tw),
            }
            if topic in v2:
                return v2[topic]()
            if topic == "decisions":
                return explain.decisions_summary(tw, loop)
            return explain.shift(tw, loop)

    def _retrieve(self, query: str, k: int = 6) -> list:
        with self.s.lock:
            docs = build_corpus(self.s.twin, self.s.loop)
        return Index(docs).search(query, k=k)

    def _summarise(self, question: str, facts: list[str]) -> tuple[str | None, str]:
        if self.llm is None:
            return None, "unavailable"
        numbered = "\n".join(f"[{i + 1}] {f}" for i, f in enumerate(facts[:40]))
        try:
            got = self.llm.complete_structured(
                system_prompt=(
                    "You are the shift assistant of a delivery station. Answer the manager's "
                    "question in 2-5 plain sentences using ONLY the numbered facts. Explain causes "
                    "and what was done about them. Never introduce a number that is not in the "
                    "facts. Cite the fact numbers you used. Glossary: DEA = Delivery Estimate "
                    "Accuracy; OTD = On-Time Departure; VET = Voluntary Extra Time; VTO = "
                    "Voluntary Time Off; GTDR = Global Trailer Dock and Release; OFD = out for "
                    "delivery; SPR = shipments per route; pp = percentage points. Reply only "
                    "with JSON."
                ),
                user_prompt=f"Question: {question}\n\nFacts:\n{numbered}",
                response_model=GroundedAnswer,
                timeout_seconds=40,
            )
        except LLMProviderError:
            return None, "unavailable"
        ans = got.answer.strip()
        ok = (
            len(ans) > 20
            and grounded(ans, facts)
            and all(1 <= i <= len(facts) for i in got.cited_facts)
        )
        return (ans, "grounded") if ok else (None, "withheld")

    def _explain(self, msg, ent) -> ChatReply:
        last = self.s.chat_context.get("topic")
        topic = ent.get("topic") or last or "shift"
        if ent.get("followup") and topic == "decisions" and last not in (None, "decisions"):
            topic = last  # "what did you do about it?" → the decisions on the last topic
        t0 = time.time()
        a = self._analysis(topic, ent.get("text", msg.lower()))
        hits = self._retrieve(msg, k=5)
        # the LLM sees only the computed analysis (small models get confused by
        # raw records); retrieved records are shown to the user as sources
        summary, status = self._summarise(msg, a.facts()[:30])
        sources = [s.model_dump() for s in a.sources] + [
            {"kind": h.kind, "title": h.title, "clock": h.clock} for h in hits
        ]
        return ChatReply(
            intent="explain",
            title=a.title,
            reply=a.text(),
            sections=[s.model_dump() for s in a.sections],
            sources=sources,
            llm_summary=summary,
            llm_status=status,
            data={"topic": topic, "headline": a.headline, "ms": round((time.time() - t0) * 1000)},
        )

    def _ask(self, msg, ent) -> ChatReply:
        """Anything else about the shift: retrieve, then summarise (grounded)."""
        hits = self._retrieve(msg, k=8)
        if not hits:
            return ChatReply(
                intent="ask",
                reply="I couldn't find anything about that in today's shift record. "
                + self._help(msg, ent).reply,
            )
        facts = [h.text for h in hits]
        summary, status = self._summarise(msg, facts)
        lines = [f"[{h.clock or '—'}] {h.text}" for h in hits]
        return ChatReply(
            intent="ask",
            title="From the shift record",
            reply="Here's what the shift record says:\n" + "\n".join(f"• {x}" for x in lines),
            sections=[{"title": "Most relevant records", "lines": lines}],
            sources=[{"kind": h.kind, "title": h.title, "clock": h.clock} for h in hits],
            llm_summary=summary,
            llm_status=status,
        )

    def _tomorrow(self, msg, ent) -> ChatReply:
        return self._explain(msg, {"topic": "tomorrow", "text": msg.lower()})

    def _floor(self, msg, ent) -> ChatReply:
        with self.s.lock:
            tw = self.s.twin
            mis = [
                f"{r.route_id} cart in {r.misstaged_at} (belongs {r.staging_location})"
                for r in tw.routes
                if r.misstaged_at and r.misstage_fixed_at is None
            ]
            fixed = sum(1 for r in tw.routes if r.misstage_fixed_at)
            flagged = sum(
                1
                for p in tw.pkgs
                if p.status == "left_behind" and p.left_reason == "bag_not_loaded"
            )
            swept, ct = tw.counters["sweep_staged"], tw.counters["cluster_transfer"]
            unacked = sum(
                1 for n in tw.notifications if not n["ack"] and n["audience"] == "supervisor"
            )
        reply = (
            ("Misstaged carts now: " + "; ".join(mis) + ". ")
            if mis
            else "No misstaged carts right now. "
        ) + (
            f"{fixed} wrong staging scan(s) corrected today. {flagged} flagged package(s) still in "
            f"aisles; sweep has staged {swept} left-behind package(s) back to carts and "
            f"{ct} went to cluster transfer for the next cycle. {unacked} unacknowledged "
            "supervisor notification(s)."
        )
        return ChatReply(intent="floor", reply=reply)

    def _yard(self, msg, ent) -> ChatReply:
        with self.s.lock:
            from app.simulation.station_ops.views import yard

            y = yard(self.s.twin)
        g = [r for r in y["rows"] if r["state"] == "grounded"]
        reply = (
            f"{y['marshals']} yard marshal(s); {y['audited']} vans audited — {y['passed']} passed, "
            f"{y['minor_fixed']} fixed on site, {y['grounded']} grounded; {y['queue']} in the VSA "
            f"queue (booked {y['booked_ahead_minutes']} min ahead). Spare vans: "
            + ", ".join(f"{k} {v}" for k, v in y["spare_vans"].items())
            + "."
        )
        if g:
            reply += " Grounded now: " + "; ".join(
                f"{r['route_id']} ({r['defect']}) — "
                + (f"{r['van_request']} ETA {r['van_eta']}" if r["van_request"] else "no van yet")
                for r in g
            )
        return ChatReply(intent="yard", reply=reply)

    def _goal(self, risk_type: str, label: str, intent: Intent) -> ChatReply:
        a = self.s.loop.handle_goal(self.s.twin, risk_type, label)
        txt = f"{a.agent_label} on it — {a.rationale}"
        if a.applied_effects:
            txt += " Applied to the simulated station: " + "; ".join(a.applied_effects) + "."
        elif a.advisory:
            txt += " " + a.advisory
        return ChatReply(intent=intent, reply=txt, actions=[a.model_dump(mode="json")])

    def _fix_wip(self, msg, ent) -> ChatReply:
        s = self._snap()
        st = s.stow
        if st["wip_minutes"] > st["wip_target_max"]:
            return self._goal(
                "stow_wip_above_band", "Stow WIP above band (chat request)", "fix_wip"
            )
        if st["wip_minutes"] < st["wip_target_min"]:
            return self._goal(
                "stow_wip_below_band", "Stow WIP below band (chat request)", "fix_wip"
            )
        return ChatReply(
            intent="fix_wip",
            reply=(
                f"Stow WIP is {st['wip_minutes']:.1f} min — already inside the "
                f"{st['wip_target_min']:.0f}–{st['wip_target_max']:.0f} min band, so no change is needed."
            ),
        )

    def _protect_dea(self, msg, ent) -> ChatReply:
        with self.s.lock:
            risks = {r.risk_type for r in detect_risks(self.s.twin, build_snapshot(self.s.twin, 0))}
        for rt in (
            "late_linehaul_rollover",
            "induct_line_down",
            "induct_capacity_shortfall",
            "stow_capacity_shortfall",
            "problem_solve_backlog",
            "routes_at_risk",
        ):
            if rt in risks:
                return self._goal(rt, "DEA protection (chat request)", "protect_dea")
        return ChatReply(
            intent="protect_dea",
            reply=(
                "No DEA risk is detected right now — every projection fits before pick start. "
                "I'll keep the agents watching."
            ),
        )

    def _protect_otd(self, msg, ent) -> ChatReply:
        with self.s.lock:
            tw = self.s.twin
            risks = detect_risks(tw, build_snapshot(tw, 0))
            acted = []
            for r in risks:
                if r.risk_type in ("driver_late", "wave_checkin_upcoming"):
                    routes = r.evidence.get("unnotified", [])
                    if routes:
                        acted.append(
                            tw.apply(
                                Intervention(
                                    kind="notify_drivers",
                                    target=routes[0],
                                    at_minute=tw.now_minute,
                                    source="chat",
                                    params={"routes": routes},
                                )
                            )
                        )
                if r.risk_type == "driver_no_show":
                    for rid in r.evidence.get("routes", []):
                        acted.append(
                            tw.apply(
                                Intervention(
                                    kind="reassign_standby",
                                    target=rid,
                                    at_minute=tw.now_minute,
                                    source="chat",
                                )
                            )
                        )
                if r.risk_type == "traffic_incident":
                    acted.append(
                        tw.apply(
                            Intervention(
                                kind="notify_drivers",
                                at_minute=tw.now_minute,
                                source="chat",
                                params={
                                    "sector": r.evidence.get("sector"),
                                    "leave_early_minutes": r.evidence.get("minutes", 15),
                                },
                            )
                        )
                    )
            self.s._cache = None
        has_route_risk = any(r.risk_type == "routes_at_risk" for r in risks)
        if not acted and not has_route_risk:
            return ChatReply(
                intent="protect_otd",
                reply="No departure risk detected right now — "
                "drivers are on track and staging is ahead of stage-by.",
            )
        reply = ChatReply(
            intent="protect_otd",
            actions=acted,
            reply=(
                "Dispatch Agent: "
                + ("; ".join(a["effect"] for a in acted) if acted else "drivers on track")
                + "."
            ),
        )
        if has_route_risk:
            g = self._goal("routes_at_risk", "Staging risk (chat request)", "protect_otd")
            reply.reply += " " + g.reply
            reply.actions += g.actions
        return reply

    def _parse_action(self, t: str, route: str | None) -> Intervention | None:  # noqa: C901
        n = _num(t, 1)
        if re.search(r"force.?induct", t):
            return Intervention(kind="force_induct", amount=min(30, max(5, _num(t, 15))))
        if re.search(r"change (the )?cycle", t):
            return Intervention(kind="change_cycle")
        if re.search(r"enable (the )?(next )?cycle", t):
            return Intervention(kind="enable_cycle", amount=min(8, max(1, _num(t, 4))))
        if "rebalance" in t:
            f = re.search(r"finger[- ]?([ab])", t)
            return Intervention(
                kind="rebalance_finger", target=f"FINGER-{f.group(1).upper()}" if f else None
            )
        if "approve damaged" in t:
            return Intervention(kind="approve_damaged")
        m = re.search(r"post (?:a )?(vet|vto)", t)
        if m:
            frame = next(
                (w.name for w in self.s.twin.config.labor_plan.work_groups if w.name.lower() in t),
                None,
            )
            return Intervention(
                kind="post_opportunity",
                target=m.group(1).upper(),
                amount=min(12, max(1, n)),
                params={"frame": frame} if frame else {},
            )
        if re.search(r"close (the )?(sign.?up )?windows?", t):
            return Intervention(kind="close_window")
        if re.search(r"re-?run (the )?rotation", t):
            return Intervention(kind="rerun_rotation")
        if "watch" in t:
            trip = re.search(r"\b(lh-[a-z0-9]+)\b", t)
            if trip:
                return Intervention(kind="watch_trip", target=trip.group(1).upper())
        if "restage" in t and route:
            return Intervention(kind="restage_cart", target=route)
        if "sweep" in t:
            aisle = re.search(r"\b([ab])\s?-?(\d{1,2})\b", t)
            if aisle:
                return Intervention(
                    kind="direct_sweep", target=f"{aisle.group(1).upper()}{int(aisle.group(2)):02d}"
                )
            if route:
                r = self.s.twin.route_by_id(route)
                if r:
                    return Intervention(kind="direct_sweep", target=r.aisle)
        if ("replacement" in t or "replace" in t or "spare van" in t) and route:
            return Intervention(kind="request_replacement_van", target=route)
        if "marshal" in t:
            return Intervention(kind="add_yard_marshal")
        if "ferr" in t and "check" in t:
            return Intervention(kind="check_ferry")
        if re.search(r"re-?plan", t):
            return Intervention(kind="replan_next_day")
        if "gtdr" in t:
            return Intervention(kind="draft_gtdr")
        if "offer" in t and "vto" in t:
            return Intervention(kind="offer_vto", amount=min(12, max(1, n)))
        if "offer" in t and "vet" in t:
            return Intervention(kind="offer_vet", amount=min(12, max(1, n)))
        if "inject" in t or "simulate" in t:
            kind = (
                "line_jam"
                if "jam" in t or "line" in t and "down" in t
                else "scanner_degradation"
                if "scanner" in t
                else "traffic_incident"
                if "traffic" in t
                else "weather"
                if "weather" in t or "rain" in t or "storm" in t
                else "volume_surge"
                if "surge" in t or "volume" in t
                else "absenteeism"
                if "absent" in t or "leave" in t or "call out" in t
                else None
            )
            if kind is None:
                return None
            sector = next(
                (
                    v
                    for k, v in (("north", "N"), ("south", "S"), ("east", "E"), ("west", "W"))
                    if k in t
                ),
                None,
            )
            line = re.search(r"line\s*(\d)", t)
            dur = re.search(r"(\d+)\s*min", t)
            params = {"kind": kind, "duration_minutes": float(dur.group(1)) if dur else 30.0}
            if kind in ("line_jam", "scanner_degradation"):
                params["target"] = line.group(1) if line else "1"
                params["magnitude"] = 3.0
            elif kind == "traffic_incident":
                params["target"], params["magnitude"] = sector or "N", 20.0
            elif kind == "weather":
                params["magnitude"] = 2.5
            elif kind == "volume_surge":
                params["magnitude"] = float(n if n > 1 else 400)
            elif kind == "absenteeism":
                params["target"], params["magnitude"] = "stow", float(n if n < 10 else 2)
            return Intervention(
                kind="inject_disruption",
                target=kind,
                params=params,
                amount=params.get("magnitude", 1),
            )
        if "unsideline" in t and route:
            return Intervention(kind="unsideline_route", target=route)
        if "sideline" in t and route:
            return Intervention(kind="sideline_route", target=route)
        if "priorit" in t and route:
            return Intervention(
                kind="prioritize_route", target=route, amount=max(1, n if n < 10 else 1)
            )
        if ("wave" in t or "later" in t) and route:
            return Intervention(kind="move_route_wave", target=route, amount=1)
        if ("standby" in t or "backup" in t or "rescue" in t) and route:
            return Intervention(kind="reassign_standby", target=route)
        if "swipe" in t:
            return Intervention(kind="notify_swipe_finish")
        if "notify" in t or "remind" in t:
            target = route or ("all" if "all" in t else "late")
            return Intervention(kind="notify_drivers", target=target)
        if "scrub" in t:
            return Intervention(
                kind="start_scrub", target="on_road" if "road" in t else "in_station"
            )
        if "spare" in t or ("open" in t and "line" in t):
            return Intervention(kind="open_induct_line")
        if "extend" in t or "pick start" in t:
            return Intervention(kind="extend_cutoff", amount=min(45, n if n > 1 else 15))
        if "resequence" in t or "unload first" in t:
            trip = re.search(r"(LH-[0-9A-F]+)", t.upper())
            return (
                Intervention(kind="resequence_unload", target=trip.group(1))
                if trip
                else Intervention(kind="priority_late_linehauls")
            )
        if "move" in t:
            hits = sorted((t.find(k), v) for k, v in _ROLES.items() if k in t)
            roles = list(dict.fromkeys(v for _, v in hits))
            m = re.search(r"from\s+(\w+(?:\s\w+)?)\s+to\s+(\w+(?:\s\w+)?)", t)
            if m:
                fr = next((v for k, v in _ROLES.items() if k in m.group(1)), None)
                to = next((v for k, v in _ROLES.items() if k in m.group(2)), None)
            elif len(roles) >= 2:
                fr, to = roles[0], roles[1]
            else:
                fr = to = None
            if fr and to:
                return Intervention(
                    kind="move_associates",
                    target=to,
                    amount=n,
                    params={"from_role": fr, "to_role": to},
                )
        if "vet" in t or "call in" in t or "add" in t:
            if "pick" in t:
                return Intervention(kind="add_pickers", amount=min(6, n))
            if "stow" in t:
                return Intervention(kind="add_stowers", amount=min(6, n))
        return None

    def _action(self, msg, ent) -> ChatReply:
        iv = self._parse_action(ent["text"], ent.get("route"))
        if iv is None:
            return ChatReply(
                intent="action",
                reply=(
                    "I couldn't map that to an action I can take. " + self._help(msg, ent).reply
                ),
            )
        rec = self._apply(iv)
        noop = rec["effect"].startswith("no-op")
        return ChatReply(
            intent="action",
            actions=[rec],
            reply=(
                ("Couldn't do that: " if noop else "Done (simulated station): ")
                + rec["effect"]
                + "."
            ),
        )

    def _what_if(self, msg, ent) -> ChatReply:
        iv = self._parse_action(
            ent["text"].replace("what if", "").replace("we ", ""), ent.get("route")
        )
        if iv is None:
            return ChatReply(
                intent="what_if", reply='Tell me the lever, e.g. "what if we VET 3 stowers?"'
            )
        with self.s.lock:
            tw = self.s.twin
            configs = belief_configs(tw, 2)
            applied = applied_log(tw)
            iv = iv.model_copy(update={"at_minute": tw.now_minute, "source": "what_if"})
        _, [ev, *_] = evaluate_prepared(
            configs,
            applied,
            [Candidate(name=iv.kind.replace("_", " "), interventions=[iv], labor_hours=0)],
            try_combination=False,
        )
        return ChatReply(
            intent="what_if",
            data=ev.model_dump(mode="json"),
            reply=(
                f"Simulated over {ev.futures} belief futures, not applied: DEA {ev.delta_dea_pp:+.2f}pp, "
                f"OTD {ev.delta_otd_pp:+.2f}pp, timely staged {ev.delta_timely_staged_pp:+.2f}pp "
                f'(robust score {ev.score}). Say the same without "what if" to apply it.'
            ),
        )

    def _control(self, msg, ent) -> ChatReply:
        t = ent["text"]
        kw: dict = {}
        if "pause" in t:
            kw["paused"] = True
        if "resume" in t:
            kw["paused"] = False
        if "speed" in t or "faster" in t or "slower" in t:
            n = _num(t, 0)
            kw["speed"] = float(n) if n else self.s.speed * (2 if "faster" in t else 0.5)
        for mode in ("autopilot", "observe"):
            if mode in t:
                kw["mode"] = mode
        if "copilot" in t or "advise" in t:
            kw["mode"] = "advise"
        info = self.s.control(**kw)
        return ChatReply(
            intent="control",
            reply=(
                f"Session {'paused' if info['paused'] else 'running'} at {info['speed']:g} sim-min/sec, "
                f"agents in {info['mode']} mode."
            ),
            data=info,
        )

    def _approve(self, msg, ent) -> ChatReply:
        pending = [a for a in self.s.loop.actions if a.status == "pending"]
        chosen = (
            pending
            if ent.get("all")
            else [a for a in pending if a.id == ent.get("id")] or pending[-1:]
        )
        done = [self.s.approve(a.id) for a in chosen]
        if not done:
            return ChatReply(intent="approve", reply="There are no pending recommendations.")
        return ChatReply(
            intent="approve",
            actions=[a.model_dump(mode="json") for a in done],
            reply=(
                f"Approved {len(done)} recommendation(s): "
                + "; ".join(f"#{a.id} {a.chosen}" for a in done)
                + "."
            ),
        )

    def _dismiss(self, msg, ent) -> ChatReply:
        pending = [a for a in self.s.loop.actions if a.status == "pending"]
        chosen = (
            pending
            if ent.get("all")
            else [a for a in pending if a.id == ent.get("id")] or pending[-1:]
        )
        done = [self.s.dismiss(a.id) for a in chosen]
        return ChatReply(intent="dismiss", reply=f"Dismissed {len(done)} recommendation(s).")

    def _unknown(self, msg, ent) -> ChatReply:
        return ChatReply(
            intent="unknown", reply="I didn't catch that. " + self._help(msg, ent).reply
        )
