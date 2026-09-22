import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(clock):
    return create_app(clock=clock, frontend_dir=None)


def _client(app, token=None):
    client = TestClient(app)
    if token:
        client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest.fixture
def anon(app):
    return _client(app)


@pytest.fixture
def instructor(app):
    return _client(app, "i1")


@pytest.fixture
def ada(app):
    return _client(app, "s01")


@pytest.fixture
def ben(app):
    return _client(app, "s02")
