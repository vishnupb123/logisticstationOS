"""get_tracer() must be safe to call from anywhere (scripts, tests,
app code) whether or not configure_tracing() was ever invoked — a
script/test run should never crash, or print unrequested span noise,
just because tracing wasn't explicitly configured.
"""

from app.core.tracing import get_tracer


def test_get_tracer_without_configure_is_safe_and_inert():
    tracer = get_tracer("test")

    with tracer.start_as_current_span("test-span") as span:
        span.set_attribute("test.ok", True)
    # No exception, no configuration required — the OpenTelemetry API's
    # own no-op default handles this.


def test_configure_tracing_is_idempotent():
    from app.core.tracing import configure_tracing

    configure_tracing()
    configure_tracing()  # must not raise or double-configure
