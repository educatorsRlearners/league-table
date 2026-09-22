"""Error-schema contract: every failure mode returns the documented Error body.

Companion to the catch-all-handler fix: an unexpected exception must produce
``{"message": ...}`` (the ``Error`` schema in openapi.yaml), not FastAPI's
default 500 body — and a class that disappears from the source must produce
a 404 Error body instead of an uncaught StopIteration.
"""

from fastapi.testclient import TestClient


def _boom_client(app):
    @app.get("/__test__/boom", include_in_schema=False)
    def boom():
        raise RuntimeError("unexpected test failure")

    return TestClient(app, raise_server_exceptions=False)


def test_unexpected_exception_returns_error_schema(app, instructor):
    client = _boom_client(app)
    client.headers.update({"Authorization": "Bearer i1"})
    res = client.get("/__test__/boom")
    assert res.status_code == 500
    body = res.json()
    assert set(body) == {"message"}, body
    assert isinstance(body["message"], str)


def test_unexpected_exception_without_auth_still_error_schema(app):
    client = _boom_client(app)
    res = client.get("/__test__/boom")
    # No auth layer on the probe route, so the 500 handler is what answers.
    assert res.status_code == 500
    assert set(res.json()) == {"message"}


def test_missing_class_returns_404_error_schema(app, instructor):
    res = instructor.get("/classes/no-such-class/bootstrap")
    assert res.status_code == 404
    assert set(res.json()) == {"message"}


def test_read_of_vanished_class_returns_404_not_500(app, instructor, monkeypatch):
    """A class visible to has_class but absent from _read's listing → 404."""
    svc = app.state.ctx.service
    real_list = svc.source.list_classes

    monkeypatch.setattr(svc, "has_class", lambda class_id: True)
    monkeypatch.setattr(
        svc.source,
        "list_classes",
        lambda *a, **k: [c for c in real_list(*a, **k) if c.id != "c2"],
    )
    # has_class claims c2 exists but _read's listing lacks it: _read must
    # raise a documented error, not an uncaught StopIteration.
    res = instructor.get("/classes/c2/bootstrap")
    assert res.status_code == 404
    assert set(res.json()) == {"message"}
