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


def test_change_log_table_is_created_and_round_trips(tmp_path):
    from sqlalchemy import inspect

    from app.store import SqlAlchemyStore

    url = f"sqlite:///{tmp_path / 'log.db'}"
    store = SqlAlchemyStore(database_url=url, class_ids=["c1"])
    assert "change_log" in inspect(store._engine).get_table_names()
    assert store.list_change_log("c1") == []
    store.save_baseline(class_id="c1", student_id="s1", hours={"work": 4}, submitted_at="2026-01-01T00:00:00+00:00")
    store._engine.dispose()

    reopened = SqlAlchemyStore(database_url=url, class_ids=["c1"])
    [entry] = reopened.list_change_log("c1")
    assert entry["action"] == "baseline.submit" and entry["new_values"]["work"] == 4


def test_old_weekly_updates_table_gains_superseded_by_column(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from app.store import SqlAlchemyStore

    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE weekly_updates (pk INTEGER PRIMARY KEY AUTOINCREMENT, id VARCHAR, class_id VARCHAR, "
            "student_id VARCHAR, week_id VARCHAR, week_number INTEGER, work_hours FLOAT, childcare_hours FLOAT, "
            "eldercare_hours FLOAT, entered_at VARCHAR, reversed_by VARCHAR, reversed_at VARCHAR)"
        ))
    engine.dispose()
    store = SqlAlchemyStore(database_url=url, class_ids=["c1"])
    assert "superseded_by" in {c["name"] for c in inspect(store._engine).get_columns("weekly_updates")}


def test_resolve_database_url_leaves_explicit_driver_alone():
    assert resolve_database_url("postgresql+psycopg2://user:pw@host:5432/db") == (
        "postgresql+psycopg2://user:pw@host:5432/db"
    )
