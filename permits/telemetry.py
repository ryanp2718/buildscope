# -*- coding: utf-8 -*-
"""OpenTelemetry wiring, kept in one place and off by default.

Why OTel rather than a vendor SDK: the raw store is permanently private
([ADR-0015](../docs/adr/0015-the-raw-store-is-permanently-private.md)), and a
hosted tracing backend would carry page content off this machine as a side
effect of being switched on. OTel's GenAI semantic conventions are the
vendor-neutral spelling of the same data, so the spans this project emits can
be read by Phoenix, Jaeger, Braintrust or LangSmith without any of them being
a dependency, and without the default configuration sending anything anywhere.

Off by default is deliberate. With no provider installed the OTel API returns
a no-op tracer, so `infer.py` can be written as though tracing is always on
and cost nothing when it is not.

    PERMITS_TRACE=console   spans to stdout, no network
    PERMITS_TRACE=otlp      spans to OTEL_EXPORTER_OTLP_ENDPOINT
    (unset)                 no-op

`otlp` needs the optional extra: `uv sync --extra otlp`.
"""
import os

from opentelemetry import trace

SERVICE_NAME = "permits"
_configured = False


def setup(mode=None):
    """Install a tracer provider. Idempotent; safe to call from any entry."""
    global _configured
    if _configured:
        return trace.get_tracer(SERVICE_NAME)
    mode = (mode or os.environ.get("PERMITS_TRACE", "")).strip().lower()
    if mode in ("", "off", "none"):
        _configured = True
        return trace.get_tracer(SERVICE_NAME)

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({"service.name": SERVICE_NAME}))
    if mode == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        exporter = ConsoleSpanExporter()
    elif mode == "otlp":
        # Imported here so the base install does not need the extra.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter()
    else:
        raise ValueError(
            "PERMITS_TRACE=%r is not one of console, otlp, off" % mode)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True
    return trace.get_tracer(SERVICE_NAME)


def tracer():
    """The tracer, configuring on first use."""
    return setup()
