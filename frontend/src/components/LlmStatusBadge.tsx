// Whether the local LLM (Ollama) is reachable with its configured model —
// so a "degraded" investigation is explained before anyone runs one.
import { useQuery } from "@tanstack/react-query";
import { stationOpsApi } from "../api/stationOps";

export function LlmStatusBadge() {
  const s = useQuery({ queryKey: ["llm-status"], queryFn: stationOpsApi.llmStatus, refetchInterval: 30_000 });
  if (!s.data) return null;
  return (
    <span
      className={`status-pill status-pill--${s.data.available ? "completed" : "degraded"}`}
      data-testid="llm-status"
      title={`${s.data.provider} at ${s.data.base_url}`}
    >
      LLM {s.data.available ? `ready · ${s.data.model}` : `unavailable · ${s.data.model}`}
    </span>
  );
}
