// Station Assistant: ask about the live station or tell it what to do
// ("fix stow WIP", "notify late drivers", "move R-031 to the next wave").
// Requests route to the multi-agent orchestrator or straight to the
// simulated station; every reply reports what actually happened.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { runtimeApi } from "../api/runtime";
import "./ChatPanel.css";

const SUGGESTIONS = [
  "status",
  "what's at risk?",
  "how is stow WIP?",
  "fix stow WIP",
  "protect OTD",
  "late drivers",
  "what if we VET 3 stowers?",
  "simulate a jam on line 2 for 20 min",
];

interface Msg {
  role: "user" | "assistant";
  text: string;
  intent?: string;
  by?: string;
}

export function ChatBox({ height = 420, autoFocus = false }: { height?: number; autoFocus?: boolean }) {
  const qc = useQueryClient();
  const history = useQuery({ queryKey: ["chat-history"], queryFn: runtimeApi.chatHistory });
  const [msgs, setMsgs] = useState<Msg[] | null>(null);
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const shown: Msg[] = msgs ?? history.data ?? [];
  const send = useMutation({
    mutationFn: runtimeApi.chat,
    onSuccess: (r, message) => {
      setMsgs((m) => [
        ...(m ?? history.data ?? []),
        { role: "user", text: message },
        { role: "assistant", text: r.reply, intent: r.intent, by: r.understood_by },
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
            Ask about the live station, or tell me what to fix. I act on the simulated station and the agents — and
            tell you exactly what happened.
          </p>
        )}
        {shown.map((m, i) => (
          <div key={i} className={`chat__msg chat__msg--${m.role}`} data-testid={`chat-${m.role}`}>
            {m.text}
            {m.role === "assistant" && m.intent && (
              <span className="chat__meta">
                {m.intent.replace(/_/g, " ")}
                {m.by === "llm" ? " · understood by local LLM" : ""}
              </span>
            )}
          </div>
        ))}
        {send.isPending && <div className="chat__msg chat__msg--assistant chat__typing">Working…</div>}
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
          placeholder="e.g. fix stow WIP · move R-031 to the next wave · where is R-012?"
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
          <ChatBox height={340} autoFocus />
        </div>
      )}
      <button className="chat-fab" onClick={() => setOpen((o) => !o)} data-testid="chat-launcher" aria-label="Open station assistant">
        {open ? "×" : "💬 Assistant"}
      </button>
    </>
  );
}
