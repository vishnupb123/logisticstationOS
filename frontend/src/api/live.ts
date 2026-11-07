// The live twin playback stream (GET /simulation/live) — Server-Sent
// Events via the browser's own EventSource, no extra dependency. Every
// frame is a simulated snapshot (ADR-0006): this hook never presents
// it as operational truth, and the consuming view badges it as such.
import { useCallback, useEffect, useRef, useState } from "react";
import { BASE_URL } from "./client";
import type { LiveSnapshot } from "./types";

export type LiveStatus = "idle" | "connecting" | "streaming" | "complete" | "stopped" | "error";

export interface LiveParams {
  scenario: string;
  seed?: number;
  stepSeconds: number;
  frameIntervalMs: number;
}

// Long scenarios produce a few hundred frames; keep the full history
// (it's small) so charts can show the whole run, but cap defensively.
const MAX_HISTORY = 2500;

export function useLiveTwin() {
  const [status, setStatus] = useState<LiveStatus>("idle");
  const [history, setHistory] = useState<LiveSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  const start = useCallback(
    (params: LiveParams) => {
      close();
      setHistory([]);
      setError(null);
      setStatus("connecting");

      const query = new URLSearchParams({
        scenario: params.scenario,
        step_seconds: String(params.stepSeconds),
        frame_interval_ms: String(params.frameIntervalMs),
      });
      if (params.seed !== undefined) query.set("seed", String(params.seed));

      const source = new EventSource(`${BASE_URL}/simulation/live?${query}`);
      sourceRef.current = source;

      source.addEventListener("snapshot", (event) => {
        const snapshot = JSON.parse((event as MessageEvent).data) as LiveSnapshot;
        setStatus("streaming");
        setHistory((prev) => {
          const next = prev.length >= MAX_HISTORY ? prev.slice(1) : prev.slice();
          next.push(snapshot);
          return next;
        });
      });
      source.addEventListener("end", () => {
        // Close before the browser's auto-reconnect would restart the run.
        source.close();
        sourceRef.current = null;
        setStatus("complete");
      });
      source.onerror = () => {
        if (sourceRef.current !== source) return; // already closed deliberately
        source.close();
        sourceRef.current = null;
        setStatus("error");
        setError(
          "Lost the live stream — the backend may be down, or rejected the scenario/parameters.",
        );
      };
    },
    [close],
  );

  const stop = useCallback(() => {
    close();
    setStatus((s) => (s === "streaming" || s === "connecting" ? "stopped" : s));
  }, [close]);

  useEffect(() => close, [close]);

  return { status, history, latest: history[history.length - 1] ?? null, error, start, stop };
}
