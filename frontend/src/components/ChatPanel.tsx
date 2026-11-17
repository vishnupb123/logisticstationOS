// Station Assistant: ask about the live station or tell it what to do
// ("fix stow WIP", "notify late drivers", "move R-031 to the next wave").
// Requests route to the multi-agent orchestrator or straight to the
// simulated station; every reply reports what actually happened.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { type ChatTurn, runtimeApi } from "../api/runtime";
import "./ChatPanel.css";

const SUGGESTIONS = [
  "how did the shift go?",
  "why did DEA drop?",
  "why did OTD drop?",
  "status of trucks and ferries",
  "VET and VTO for tomorrow",
  "volume for tomorrow",
  "what did the agents do?",
  "fix stow WIP",
  "protect OTD",
];

const KIND_LABEL: Record<string, string> = {
  metric: "metric",
  linehaul: "linehaul",
  truckfile: "truckfile",
  gtdr: "GTDR",
  offer: "VET/VTO",
  closeout: "close-out",
  action: "action",
  agent: "agent decision",
  disruption: "disruption",
  notification: "notification",
  route: "route",
  sweep: "sweep",
  event: "event",
  packages: "packages",
  actions: "actions",
  routes: "routes",
  drivers: "drivers",
  associates: "associates",
  offers: "offers",
  plan: "plan",
  events: "events",
};

function Answer({ m }: { m: ChatTurn }) {
  const [open, setOpen] = useState<boolean>(false);
  if (!m.sections?.length) return <>{m.text}</>;
  const [headline] = m.text.split("\n");
  const long = m.sections.reduce((n, s) => n + s.lines.length, 0) > 10;
  const shown = long && !open ? m.sections.slice(0, 2) : m.sections;
  return (
    <div className="chat__answer">
      {m.title && <div className="chat__title">{m.title}</div>}
      <div className="chat__headline">{headline}</div>
      {m.llm_summary && (
        <div className="chat__ai" data-testid="chat-ai-summary">
          <span className="chat__ai-tag" title="Written by the local LLM from the computed facts below; every number was checked against them. Evidence category: inferred.">
            AI summary · inferred
          </span>
          {m.llm_summary}
        </div>
      )}
      {shown.map((s) => (
        <div key={s.title} className="chat__section">
          <div className="chat__section-title">{s.title}</div>
          <ul>
            {s.lines.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      ))}
      {long && (
        <button className="chat__more" onClick={() => setOpen((o) => !o)}>
          {open ? "Show less" : `Show all ${m.sections.length} sections`}
        </button>
      )}
      {!!m.sources?.length && (
        <details className="chat__sources">
          <summary>Sources ({m.sources.length})</summary>
          <ul>
            {m.sources.map((x, i) => (
              <li key={i}>
                <span className="chat__src-kind">{KIND_LABEL[x.kind] ?? x.kind}</span> {x.title}
                {x.clock ? <span className="muted"> · {x.clock}</span> : null}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function ChatBox({ height = 420, autoFocus = false }: { height?: number; autoFocus?: boolean }) {
  const qc = useQueryClient();
  const history = useQuery({ queryKey: ["chat-history"], queryFn: runtimeApi.chatHistory });
  const [msgs, setMsgs] = useState<ChatTurn[] | null>(null);
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const shown: ChatTurn[] = msgs ?? history.data ?? [];
  const send = useMutation({
    mutationFn: runtimeApi.chat,
    onSuccess: (r, message) => {
      setMsgs((m) => [
        ...(m ?? history.data ?? []),
        { role: "user", text: message },
        {
          role: "assistant",
          text: r.reply,
          intent: r.intent,
          title: r.title,
          sections: r.sections,
          sources: r.sources,
          llm_summary: r.llm_summary,
          llm_status: r.llm_status,
        },
      ]);
      qc.invalidateQueries({ queryKey: ["live-state"] });
    },
  });
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [shown.length, send.isPending]);

  const submit = (e?: FormEvent, value?: string) => {
    e?.preventDefault();
    const m = (value ?? text).trim();
    if (!m) return;
    setText("");
    send.mutate(m);
  };

  return (
    <div className="chat" data-testid="chat">
      <div className="chat__log" style={{ height }} aria-live="polite">
        {shown.length === 0 && (
          <p className="muted chat__hint">
            Ask anything about the shift — why DEA or OTD moved, trucks and ferries, VET/VTO, tomorrow's volume — or tell
            me what to fix. Answers are computed from the live station and cite their sources; requests go to the agents.
          </p>
        )}
        {shown.map((m, i) => (
          <div key={i} className={`chat__msg chat__msg--${m.role}${m.sections?.length ? " chat__msg--rich" : ""}`} data-testid={`chat-${m.role}`}>
            {m.role === "assistant" ? <Answer m={m} /> : m.text}
            {m.role === "assistant" && m.intent && (
              <span className="chat__meta">
                {m.intent.replace(/_/g, " ")}
                {m.llm_status === "withheld" ? " · AI summary withheld (unsupported numbers)" : ""}
              </span>
            )}
          </div>
        ))}
        {send.isPending && <div className="chat__msg chat__msg--assistant chat__typing">Analysing the shift…</div>}
        <div ref={endRef} />
      </div>
      <div className="chat__suggest">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="chat__chip" onClick={() => submit(undefined, s)} disabled={send.isPending}>
            {s}
          </button>
        ))}
      </div>
      <form className="chat__form" onSubmit={submit}>
        <input
          aria-label="Message the station assistant"
          value={text}
          autoFocus={autoFocus}
          placeholder="e.g. why did DEA drop? · status of the ferries · fix stow WIP"
          onChange={(e) => setText(e.target.value)}
        />
        <button className="button button--primary" type="submit" disabled={send.isPending || !text.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}

export function ChatLauncher() {
  const [open, setOpen] = useState(false);
  return (
    <>
      {open && (
        <div className="chat-pop" role="dialog" aria-label="Station assistant">
          <div className="chat-pop__head">
            <strong>Station Assistant</strong>
            <span className="muted">acts on the simulated station</span>
            <button className="chat-pop__close" onClick={() => setOpen(false)} aria-label="Close assistant">
              ×
            </button>
          </div>
          <ChatBox height={420} autoFocus />
        </div>
      )}
      <button className="chat-fab" onClick={() => setOpen((o) => !o)} data-testid="chat-launcher" aria-label="Open station assistant">
        {open ? "×" : "💬 Assistant"}
      </button>
    </>
  );
}
