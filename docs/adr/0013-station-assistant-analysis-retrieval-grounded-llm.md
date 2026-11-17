# ADR-0013: Station Assistant — computed analysis, retrieval, grounded LLM summaries

**Status**: Accepted (2026-11-12). Amends ADR-0012 §5 (the assistant); the ADR-0008/0009 boundaries are unchanged.

## Context

The project owner asked for an assistant that gives detailed answers about anything in the shift. Examples:
- *why* DEA went low, and which decisions were made to improve it;
- the live status of trucks, ferries and the truckfile;
- VETs raised and accepted, VTOs, and tomorrow's volume.

It should still coordinate the agents and carry out tasks: "retrieval + LLM + agent + task coordination".

Under ADR-0012 the LLM could only *classify* unmatched messages, and answers were short templated lookups.

## Decision

Every question about the shift is answered in three layers.

1. **Computed analysis** (`app/runtime/explain.py`): deterministic, rule-based analyses over the live twin.
   - The analyses cover DEA root cause, OTD root cause, trucks/ferries/truckfile/GTDR, labor and VET/VTO, tomorrow, decisions, and a shift summary.
   - Attribution rules are stated in code. For example, a rolled-over package that arrived after pick start is attributed to its late linehaul.
   - Decisions are listed with who made them, and the agents' simulated expected gain.
   - **Impact** comes from replaying the same day (same seed and disruptions) without any decisions. It is reported as a simulated counterfactual.
   - This layer is the authoritative answer.
2. **Retrieval** (`app/runtime/knowledge.py`): a corpus rebuilt per question from live state.
   - It covers metrics, linehauls, tomorrow's truckfile and revisions, GTDRs, VET/VTO offers, call-outs, close-out tasks, every applied action, agent decisions with rationale, disruptions, notifications, late routes, the sweep log and events.
   - It is ranked by BM25 with a domain synonym map: local, deterministic, no embedding model.
   - Retrieved records are cited as sources, and they alone answer free-form questions.
3. **Local-LLM summary** (optional; ADR-0008 provider, structured `GroundedAnswer`).
   - The LLM sees only the numbered computed facts and writes a short narrative, tagged `inferred`.
   - A guard checks that **every number in it appears in the facts** (times exactly, values to rounding) and that cited fact ids exist.
   - Otherwise the summary is withheld (`llm_status="withheld"`).
   - Numbers are therefore never generated. The narrative can still simplify, so the UI labels it "AI summary · inferred" above the computed sections.

Requests (goals, floor/dispatch actions, close-out actions, what-ifs, session control) still go through the deterministic parser to the agents or the simulated station, exactly as before.

Follow-ups ("why?", "what did you do about it?") reuse the last topic.

## Consequences

- Answers are reproducible and auditable; the LLM adds readability, not facts.
- A 1.5B local model's prose is shallow and sometimes imprecise. The number guard catches invented figures but not every wording error.
- A larger local model (e.g. `OLLAMA_MODEL=qwen2.5:7b`) would read better, with no code change.
- A DEA/OTD question after departures costs one extra twin replay (~0.3–1 s). It is cached per decision count.

## Revisit conditions

- Real operational data: the corpus would then need access control and redaction before any LLM sees it.
- If semantic retrieval is needed beyond lexical BM25: add a local embedding model through the provider abstraction, not a hosted vector DB.
