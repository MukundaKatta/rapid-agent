"""Optional export of rapid-agent Trace events to Arize Phoenix.

Usage (requires ``arize-phoenix[otel]`` installed):

    from rapid_agent import Trace
    from rapid_agent.phoenix_export import export_trace_to_phoenix

    trace = Trace()
    # ... run the agent ...
    export_trace_to_phoenix(trace, run_name="research-brief")

Phoenix captures each governance event (fetch, model call, budget check) as a
span so you get latency, token counts, and USD cost in the Phoenix UI without
any extra infrastructure.  The Phoenix server can be started locally with::

    python -m phoenix.server.main &

or pointed at a remote endpoint via the PHOENIX_COLLECTOR_ENDPOINT env var.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rapid_agent.governance import Trace


def export_trace_to_phoenix(trace: "Trace", run_name: str = "rapid-agent-run") -> bool:
    """Export *trace* events to Arize Phoenix via OpenTelemetry.

    Returns True if the export succeeded, False if ``arize-phoenix`` is not
    installed (the caller can decide whether to raise or silently skip).
    """
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except ImportError:
        return False

    endpoint = os.environ.get(
        "PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces"
    )

    resource = Resource.create({"service.name": "rapid-agent"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
    tracer = otel_trace.get_tracer("rapid_agent")

    import time as _time

    with tracer.start_as_current_span(run_name) as run_span:
        run_span.set_attribute("rapid_agent.total_usd", trace.total_usd)
        run_span.set_attribute("rapid_agent.total_ms", trace.total_ms)
        run_span.set_attribute("rapid_agent.event_count", len(trace.events))

        for ev in trace.events:
            start_ns = int(ev.started_at * 1e9)
            end_ns = start_ns + int(ev.duration_ms * 1e6)
            with tracer.start_as_current_span(
                ev.name,
                start_time=start_ns,
            ) as span:
                span.set_attribute("rapid_agent.usd", ev.usd)
                span.set_attribute("rapid_agent.input_tokens", ev.input_tokens)
                span.set_attribute("rapid_agent.output_tokens", ev.output_tokens)
                for k, v in ev.meta.items():
                    span.set_attribute(f"rapid_agent.meta.{k}", str(v))

    provider.force_flush()
    return True
