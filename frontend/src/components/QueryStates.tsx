import { ApiError } from "../api/client";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return <div className="query-state query-state--loading">{label}</div>;
}

export function ErrorState({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? `${error.status}: ${error.detail}`
      : error instanceof Error
        ? error.message
        : "Unknown error";
  return <div className="query-state query-state--error">⚠ {message}</div>;
}

export function EmptyState({ label }: { label: string }) {
  return <div className="query-state query-state--empty">{label}</div>;
}
