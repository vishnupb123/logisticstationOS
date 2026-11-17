// Presenter controls (HANDOFF_V2 E12): chapter buttons that jump the simulated
// clock to the demo script's bookmarks, and a large-type "Presenter mode"
// toggle (persisted per browser). The chapter strip shows on a pitch-day
// session or whenever presenter mode is on.
import { useEffect, useState } from "react";
import { useStation } from "../api/runtime";
import { useSeek } from "../api/runtimeV2";
import "./PresenterBar.css";

const KEY = "stationos-presenter";

function readPresenter(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function PresenterBar() {
  const q = useStation();
  const seek = useSeek();
  const [on, setOn] = useState<boolean>(readPresenter);
  useEffect(() => {
    document.body.classList.toggle("presenter-mode", on);
    try {
      localStorage.setItem(KEY, on ? "1" : "0");
    } catch {
      // storage unavailable — the mode still applies for this page view
    }
    return () => document.body.classList.remove("presenter-mode");
  }, [on]);

  const chapters = q.data?.views.chapters ?? [];
  const minute = q.data?.snapshot.minute ?? 0;
  const pitch = !!q.data?.session.pitch;
  const current = [...chapters].reverse().find((c) => c.minute <= minute + 0.5)?.minute;
  const showChapters = (pitch || on) && chapters.length > 0;

  return (
    <div className="pbar" data-testid="presenter-bar">
      <button
        type="button"
        className="button button--sm pbar__toggle"
        aria-pressed={on}
        onClick={() => setOn((v) => !v)}
        data-testid="presenter-toggle"
        title="Large type and chapter navigation for a demo"
      >
        {on ? "✓ Presenter mode" : "Presenter mode"}
      </button>
      {showChapters && (
        <div className="pbar__chapters" role="group" aria-label="Demo chapters">
          {chapters.map((c) => (
            <button
              key={c.minute}
              type="button"
              className={`pbar__chapter${current === c.minute ? " pbar__chapter--current" : ""}`}
              aria-current={current === c.minute ? "step" : undefined}
              disabled={seek.isPending}
              onClick={() => seek.mutate(c.minute)}
              title={c.title}
              data-testid={`chapter-${c.minute}`}
            >
              <span className="tabular pbar__clock">{c.clock}</span>
              <span className="pbar__title">{c.title}</span>
            </button>
          ))}
          {seek.isPending && <span className="muted pbar__status">Jumping…</span>}
          {seek.error && <span className="pbar__status pbar__status--err">{String(seek.error.message)}</span>}
        </div>
      )}
    </div>
  );
}
