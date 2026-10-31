"""Minimal, local-first tracing (Milestone 9,
docs/SYSTEM_ARCHITECTURE.md §Observability: "revisit OpenTelemetry
here... by now there is [more than one process/hop worth tracing]").

A `ConsoleSpanExporter` only — no external collector, no mandatory
cloud service, same "no premature infrastructure" stance ADR-0001/
ADR-0010 apply elsewhere. Structured JSON logging
(`app/core/logging.py`) remains the primary day-to-day observability
tool; tracing adds step-level correlation and duration *within* one
multi-step operation (an agent run, a decision proposal) — genuinely
useful even though every component here is still one Python process,
with no real network/process hop yet to call "distributed." Revisit a
real exporter/collector only once an actual hop exists (a future API
consumer, a future worker process), not before.

`configure_tracing()` is opt-in (called once at app startup, mirroring
`configure_logging()`) — scripts and tests that never call it still get
a safe, inert OpenTelemetry API default (a no-op tracer), so calling
`get_tracer()` anywhere is always safe and never adds console noise to
a CLI script or a test run unless tracing was explicitly configured.
"""

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

_configured = False


def configure_tracing(service_name: str = "stationos-backend") -> None:
    """`SimpleSpanProcessor`, deliberately not `BatchSpanProcessor` — it
    exports synchronously on each span's end, with no background
    export thread to manage or leak past process/test shutdown.
    Batching exists to amortize the cost of a real network export; a
    local console print has no such cost to amortize, so there's
    nothing batching would buy here, only a lifecycle to get wrong.
    """
    global _configured
    if _configured:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
