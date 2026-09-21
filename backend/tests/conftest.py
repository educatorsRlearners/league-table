import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from factories import ADA, BEN, CY, INSTRUCTOR, build_test_db, build_test_store, signed_in


class FakeClock:
    """Injectable clock so cache and rate-limit behaviour can be tested without sleeping."""

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
def db():
    return build_test_db()


@pytest.fixture
def store():
    return build_test_store()


@pytest.fixture
def app(db, store, clock):
    return create_app(db=db, store=store, clock=clock, instructor_passcode=INSTRUCTOR)


@pytest.fixture
def anon(app):
    """A client with no session cookie."""
    return TestClient(app)


@pytest.fixture
def instructor(app):
    return signed_in(app, INSTRUCTOR)


@pytest.fixture
def ada(app):
    """Student s01."""
    return signed_in(app, ADA)


@pytest.fixture
def ben(app):
    """Student s02."""
    return signed_in(app, BEN)


@pytest.fixture
def cy(app):
    """Student s03."""
    return signed_in(app, CY)


@pytest.fixture
def toy_app(clock):
    """The app with its default seeded demo data."""
    return create_app(clock=clock)


@pytest.fixture
def toy_instructor(toy_app):
    return signed_in(toy_app, "demo-instructor")
