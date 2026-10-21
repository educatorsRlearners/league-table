"""Issue #78: OpenTelemetry traces, metrics and trace-correlated JSON logs for the commitment journey."""

import base64
import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.main import create_app
from app.telemetry import TelemetryExporters, basic_auth_header, setup_telemetry
from tests.conftest import FakeClock

PUT_ROUTE = "/me/commitments/weeks/{weekNumber}"


class Capture:
    def __init__(self):
        self.spans = InMemorySpanExporter()
        self.metrics = InMemoryMetricReader()
        self.logs = InMemoryLogRecordExporter()
        self.stdout = io.StringIO()

    def metric_points(self):
        data = self.metrics.get_metrics_data()
        out = {}
        for rm in data.resource_metrics if data else []:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    out[m.name] = m.data.data_points
        return out

    def json_lines(self):
        return [json.loads(line) for line in self.stdout.getvalue().splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _quiet_test_client_logging():
    # The httpx test client logs full request URLs (with studentId); that is the
    # client's output, not the server's, so keep it out of the captured stdout.
    logging.getLogger("httpx2").setLevel(logging.WARNING)


@pytest.fixture
def cap():
    return Capture()


@pytest.fixture
def traced_app(cap):
    exporters = TelemetryExporters(cap.spans, cap.metrics, cap.logs, synchronous=True)
    app = create_app(clock=FakeClock(), frontend_dir=None, telemetry_exporters=exporters)
    # Route the stdout handler into the capture buffer (create_app used sys.stdout).
    for h in app.state.telemetry._handlers:
        if type(h) is logging.StreamHandler:
            h.setStream(cap.stdout)
    yield app
    app.state.telemetry.shutdown()


def journey(app, sid="s10", hours=None):
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {sid}"})
    body = hours or {"work": 10, "childcare": 0, "eldercare": 0}
    return client.put("/me/commitments/weeks/16", params={"classId": "c1", "studentId": sid}, json=body)


def other_student(app):
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer s11"})
    return client.put("/me/commitments/weeks/16", params={"classId": "c1", "studentId": "s10"}, json={"work": 1})


def server_span(cap):
    spans = [s for s in cap.spans.get_finished_spans() if s.kind.name == "SERVER"]
    assert len(spans) == 1
    return spans[0]


def test_disabled_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    root_handlers = list(logging.getLogger().handlers)
    app = create_app(clock=FakeClock(), frontend_dir=None)
    assert app.state.telemetry is None
    assert logging.getLogger().handlers == root_handlers
    assert setup_telemetry(app, None, environ={}) is None
    assert journey(app).status_code == 200


def test_journey_trace_has_server_and_db_spans(traced_app, cap):
    assert journey(traced_app).status_code == 200
    span = server_span(cap)
    assert span.name == f"PUT {PUT_ROUTE}"
    assert span.attributes["http.route"] == PUT_ROUTE
    children = [s for s in cap.spans.get_finished_spans() if s.kind.name != "SERVER"]
    db = [s for s in children if "db.system" in (s.attributes or {})]
    assert db, "expected database child spans"
    assert {s.context.trace_id for s in children} == {span.context.trace_id}
    assert len(cap.spans.get_finished_spans()) <= 40  # one span per query (the journey runs ~27) plus the request; no send/receive spans


def test_resource_distinguishes_environments(monkeypatch, cap):
    exporters = TelemetryExporters(cap.spans, cap.metrics, cap.logs, synchronous=True)
    cap2 = Capture()
    exporters2 = TelemetryExporters(cap2.spans, cap2.metrics, cap2.logs, synchronous=True)
    app = create_app(clock=FakeClock(), frontend_dir=None)
    t = setup_telemetry(app, None, environ={"OTEL_SERVICE_NAME": "league-table-dev", "DEPLOYMENT_ENV": "dev"}, exporters=exporters)
    try:
        attrs = t.tracer_provider.resource.attributes
        assert attrs["service.name"] == "league-table-dev"
        assert attrs["deployment.environment"] == "dev"
    finally:
        t.shutdown()
    app2 = create_app(clock=FakeClock(), frontend_dir=None)
    t2 = setup_telemetry(app2, None, environ={}, exporters=exporters2)
    try:
        assert t2.tracer_provider.resource.attributes["service.name"] == "league-table"
        assert "deployment.environment" not in t2.tracer_provider.resource.attributes
    finally:
        t2.shutdown()


def test_json_logs_carry_the_trace_id(traced_app, cap):
    assert journey(traced_app).status_code == 200
    span = server_span(cap)
    lines = [ln for ln in cap.json_lines() if ln["logger"] == "league_table.request"]
    assert len(lines) == 1
    line = lines[0]
    assert line["trace_id"] == format(span.context.trace_id, "032x")
    assert line["span_id"] == format(span.context.span_id, "016x")
    assert line["http_route"] == PUT_ROUTE and line["http_status_class"] == "2xx"
    # Every stdout line is JSON (json_lines parsed them all) and the OTLP copy matches.
    exported = [r.log_record for r in cap.logs.get_finished_logs()]
    assert any(format(r.trace_id, "032x") == line["trace_id"] for r in exported)


def test_journey_metrics_by_route_and_status_class(traced_app, cap):
    assert journey(traced_app).status_code == 200
    assert journey(traced_app, hours={"work": 81}).status_code == 422
    assert other_student(traced_app).status_code == 403
    points = cap.metric_points()

    def by_class(name):
        return {(p.attributes["http.route"], p.attributes["http.status_class"]): p for p in points[name]}

    reqs = by_class("league_table.requests")
    assert reqs[(PUT_ROUTE, "2xx")].value == 1
    assert reqs[(PUT_ROUTE, "4xx")].value >= 1
    errors = by_class("league_table.request.errors")
    assert (PUT_ROUTE, "2xx") not in errors and errors[(PUT_ROUTE, "4xx")].value >= 1
    hist = by_class("league_table.request.duration")
    assert hist[(PUT_ROUTE, "2xx")].count == 1
    for name in ("league_table.requests", "league_table.request.errors", "league_table.request.duration"):
        for p in points[name]:
            assert set(p.attributes) == {"http.route", "http.status_class"}


def test_health_check_is_not_traced(traced_app, cap):
    assert TestClient(traced_app).get("/login/options").status_code == 200
    assert cap.spans.get_finished_spans() == ()
    assert cap.json_lines() == []


def test_no_pii_or_secrets_in_telemetry(caplog):
    """Run the journey with distinctive values and scan every span, metric label and log."""
    cap = Capture()
    exporters = TelemetryExporters(cap.spans, cap.metrics, cap.logs, synchronous=True)
    app = create_app(clock=FakeClock(), frontend_dir=None, telemetry_exporters=exporters)
    for h in app.state.telemetry._handlers:
        if type(h) is logging.StreamHandler:
            h.setStream(cap.stdout)
    try:
        name = next(s.display_name for s in app.state.ctx.db.list_students("c1") if s.id == "s10")
        sentinel_hours = {"work": 63.5, "childcare": 41.5, "eldercare": 7.5}
        client = TestClient(app)
        client.headers.update({"Authorization": "Bearer s10"})
        params = {"classId": "c1", "studentId": "s10"}
        assert client.put("/me/commitments/weeks/16", params=params, json=sentinel_hours).status_code == 200
        assert client.get("/me/commitments", params=params).status_code == 200
        assert client.put("/me/commitments/weeks/16", params=params, json={"work": 99.9}).status_code == 422

        spans = cap.spans.get_finished_spans()
        assert spans
        blobs = []
        for s in spans:
            blobs.append(json.dumps(dict(s.attributes or {}), default=str))
            blobs.append(s.name)
            for ev in s.events:
                blobs.append(json.dumps(dict(ev.attributes or {}), default=str) + ev.name)
        for pts in cap.metric_points().values():
            blobs.extend(json.dumps(dict(p.attributes), default=str) for p in pts)
        blobs.append(cap.stdout.getvalue())
        for r in cap.logs.get_finished_logs():
            blobs.append(json.dumps({"b": str(r.log_record.body), "a": dict(r.log_record.attributes or {})}, default=str))
        text = "\n".join(blobs)
        assert "http.route" in text
        for secret in (name, "s10", "63.5", "41.5", "99.9", "studentId", "classId", "Bearer"):
            assert secret not in text, f"{secret!r} leaked into telemetry"
        # The trace-level db spans parameterise their statements.
        assert any("db.statement" in (s.attributes or {}) or "db.query.text" in (s.attributes or {}) for s in spans)
    finally:
        app.state.telemetry.shutdown()


def test_basic_auth_header_strips_newlines():
    token = "glc_abc\n"
    header = basic_auth_header("1885253\n", token)["Authorization"]
    assert header.startswith("Basic ")
    assert base64.b64decode(header[6:]) == b"1885253:glc_abc"
    assert basic_auth_header("1885253", None) == {} and basic_auth_header(None, "x") == {}


def test_otlp_exporters_post_to_signal_paths_with_basic_auth():
    """Real OTLP/HTTP POSTs to a local receiver: signal paths and the Authorization header."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append((self.path, self.headers.get("Authorization")))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    environ = {
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{server.server_port}/otlp/",
        "GRAFANA_OTLP_INSTANCE_ID": "42", "GRAFANA_OTLP_TOKEN": "tok\n",
    }
    app = create_app(clock=FakeClock(), frontend_dir=None)
    t = setup_telemetry(app, None, environ=environ)
    try:
        assert t is not None
        assert journey(app).status_code == 200
        t.tracer_provider.force_flush()
        t.logger_provider.force_flush()
        t.meter_provider.force_flush()
    finally:
        t.shutdown()
        server.shutdown()
    expected = "Basic " + base64.b64encode(b"42:tok").decode()
    assert {p for p, _ in seen} == {"/otlp/v1/traces", "/otlp/v1/logs", "/otlp/v1/metrics"}
    assert {a for _, a in seen} == {expected}
