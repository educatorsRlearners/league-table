from app.db import resolve_database_url


def test_resolve_database_url_defaults_to_sqlite_memory(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert resolve_database_url(None) == "sqlite:///:memory:"


def test_resolve_database_url_passthrough_sqlite_file():
    assert resolve_database_url("sqlite:///./league_table.db") == "sqlite:///./league_table.db"


def test_resolve_database_url_normalizes_postgres_scheme():
    assert resolve_database_url("postgres://user:pw@host:5432/db") == (
        "postgresql+psycopg://user:pw@host:5432/db"
    )


def test_resolve_database_url_pins_psycopg_driver():
    assert resolve_database_url("postgresql://user:pw@host:5432/db") == (
        "postgresql+psycopg://user:pw@host:5432/db"
    )


def test_resolve_database_url_leaves_explicit_driver_alone():
    assert resolve_database_url("postgresql+psycopg2://user:pw@host:5432/db") == (
        "postgresql+psycopg2://user:pw@host:5432/db"
    )
