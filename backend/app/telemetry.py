"""OpenTelemetry traces, metrics and trace-correlated JSON logs.

Everything is configured by environment variables and is off unless
``OTEL_EXPORTER_OTLP_ENDPOINT`` is set. With it unset nothing is configured,
no exporter threads start and no handler is attached.

Privacy rule: telemetry never carries student names or ids, note text, hours
values, tokens or request bodies. Query strings are dropped, URLs are
replaced by their route template, and SQL is recorded as the parameterised
statement only (bound values never reach a span).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TextIO

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    LogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)

ENDPOINT_VAR = "OTEL_EXPORTER_OTLP_ENDPOINT"
DEFAULT_SERVICE_NAME = "league-table"
# Health checks and nothing else are kept out of traces (regex, searched in the URL).
EXCLUDED_URLS = "login/options"
# Only these route templates feed the journey metrics.
JOURNEY_PREFIX = "/me/commitments"

_STANDARD_RECORD_KEYS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}

request_logger = logging.getLogger("league_table.request")


@dataclass
class TelemetryExporters:
    """Injectable exporters/readers; tests pass in-memory ones, production builds OTLP ones."""

    span_exporter: SpanExporter
    metric_reader: MetricReader
    log_exporter: LogRecordExporter
    synchronous: bool = False  # simple (immediate) span/log processors instead of batching


def basic_auth_header(instance_id: str | None, token: str | None) -> dict[str, str]:
    """Authorization header for Grafana Cloud OTLP; whitespace and newlines are stripped."""
    instance_id = "".join((instance_id or "").split())
    token = "".join((token or "").split())
    if not instance_id or not token:
        return {}
    raw = f"{instance_id}:{token}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def otlp_exporters(environ: Mapping[str, str]) -> TelemetryExporters:
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    base = environ[ENDPOINT_VAR].strip().rstrip("/")
    headers = basic_auth_header(environ.get("GRAFANA_OTLP_INSTANCE_ID"), environ.get("GRAFANA_OTLP_TOKEN")) or None
    return TelemetryExporters(
        span_exporter=OTLPSpanExporter(endpoint=f"{base}/v1/traces", headers=headers),
        metric_reader=PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{base}/v1/metrics", headers=headers)),
        log_exporter=OTLPLogExporter(endpoint=f"{base}/v1/logs", headers=headers),
    )


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with trace_id/span_id of the active span (hex, as in the trace)."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            out["trace_id"] = format(ctx.trace_id, "032x")
            out["span_id"] = format(ctx.span_id, "016x")
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_"):
                out[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            # Type only: exception messages can echo request data.
            out["exception"] = record.exc_info[0].__name__
        return json.dumps(out, default=str)


def status_class(status: int) -> str:
    return f"{status // 100}xx"


class _RequestMiddleware:
    """Pure ASGI middleware: journey metrics, one request log line, URL scrubbing.

    Runs inside the server span, so the log line carries its trace and span ids.
    """

    def __init__(self, app, telemetry: Telemetry):
        self.app = app
        self.t = telemetry

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or "login/options" in scope.get("path", ""):
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                template = _route_template(scope)
                if template:
                    span = trace.get_current_span()
                    host = _host(scope)
                    span.set_attribute("http.target", template)
                    span.set_attribute("http.url", f"{scope.get('scheme', 'http')}://{host}{template}")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            template = _route_template(scope)
            if template:
                self.t.record(template, scope.get("method", ""), status, time.perf_counter() - start)


def _host(scope) -> str:
    server = scope.get("server")
    return str(server[0]) if server else ""


def _route_template(scope) -> str | None:
    route = scope.get("route")
    return getattr(route, "path", None)


def _scrub_server_span(span, scope) -> None:
    """Drop the query string (it carries student ids) before routing is known."""
    path = scope.get("path", "")
    host = _host(scope)
    span.set_attribute("http.target", path)
    span.set_attribute("http.url", f"{scope.get('scheme', 'http')}://{host}{path}")


@dataclass
class Telemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider
    app: Any
    _handlers: list[logging.Handler] = field(default_factory=list)
    _saved_root_level: int = logging.WARNING
    _saved_access_level: int = logging.INFO
    _db_instrumented: bool = False

    def __post_init__(self) -> None:
        meter = self.meter_provider.get_meter("league_table")
        self.requests = meter.create_counter("league_table.requests", unit="1", description="Journey requests")
        self.errors = meter.create_counter("league_table.request.errors", unit="1", description="Journey requests answered 4xx or 5xx")
        self.duration = meter.create_histogram("league_table.request.duration", unit="s", description="Journey request latency")

    def record(self, template: str, method: str, status: int, seconds: float) -> None:
        # Labels are the route template and status class only: no ids, no values.
        if template.startswith(JOURNEY_PREFIX):
            attrs = {"http.route": template, "http.status_class": status_class(status)}
            self.requests.add(1, attrs)
            if status >= 400:
                self.errors.add(1, attrs)
            self.duration.record(seconds, attrs)
        request_logger.info(
            "request",
            extra={"http_method": method, "http_route": template,
                   "http_status_class": status_class(status), "duration_ms": round(seconds * 1000)},
        )

    def shutdown(self) -> None:
        root = logging.getLogger()
        for handler in self._handlers:
            root.removeHandler(handler)
        root.setLevel(self._saved_root_level)
        logging.getLogger("uvicorn.access").setLevel(self._saved_access_level)
        FastAPIInstrumentor.uninstrument_app(self.app)
        if self._db_instrumented:
            SQLAlchemyInstrumentor().uninstrument()
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()


def setup_telemetry(
    app,
    engine=None,
    *,
    environ: Mapping[str, str] | None = None,
    exporters: TelemetryExporters | None = None,
    log_stream: TextIO | None = None,
) -> Telemetry | None:
    """Wire telemetry into ``app``. Returns None (and does nothing) when it is not enabled."""
    environ = os.environ if environ is None else environ
    if exporters is None:
        if not environ.get(ENDPOINT_VAR, "").strip():
            return None
        exporters = otlp_exporters(environ)

    resource_attrs = {"service.name": environ.get("OTEL_SERVICE_NAME", "").strip() or DEFAULT_SERVICE_NAME}
    if environ.get("DEPLOYMENT_ENV", "").strip():
        resource_attrs["deployment.environment"] = environ["DEPLOYMENT_ENV"].strip()
    resource = Resource.create(resource_attrs)

    span_processor = (SimpleSpanProcessor if exporters.synchronous else BatchSpanProcessor)(exporters.span_exporter)
    log_processor = (SimpleLogRecordProcessor if exporters.synchronous else BatchLogRecordProcessor)(exporters.log_exporter)
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(span_processor)
    meter_provider = MeterProvider(resource=resource, metric_readers=[exporters.metric_reader])
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(log_processor)

    telemetry = Telemetry(tracer_provider, meter_provider, logger_provider, app)

    # Logs: JSON on stdout plus OTLP, both correlated with the active span.
    root = logging.getLogger()
    telemetry._saved_root_level = root.level
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    stdout = logging.StreamHandler(log_stream or sys.stdout)
    stdout.setFormatter(JsonFormatter())
    otlp_logs = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    # The exporters' own warnings must not be re-exported (a failing export would feed itself).
    otlp_logs.addFilter(lambda record: not record.name.startswith("opentelemetry"))
    for handler in (stdout, otlp_logs):
        root.addHandler(handler)
        telemetry._handlers.append(handler)
    # uvicorn's access log prints full URLs including query strings (student ids);
    # the structured request log line replaces it.
    access = logging.getLogger("uvicorn.access")
    telemetry._saved_access_level = access.level
    access.setLevel(logging.WARNING)

    # Added first so it sits inside the (later, hence outer) server-span middleware.
    app.add_middleware(_RequestMiddleware, telemetry=telemetry)
    FastAPIInstrumentor.instrument_app(
        app,
        server_request_hook=_scrub_server_span,
        tracer_provider=tracer_provider,
        excluded_urls=EXCLUDED_URLS,
        exclude_spans=["receive", "send"],
    )
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=tracer_provider)
        telemetry._db_instrumented = True
    return telemetry
