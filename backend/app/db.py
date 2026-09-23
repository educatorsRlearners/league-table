"""Database engine/session setup for the SQL-backed AppStore.

The connection target is database-agnostic: any SQLAlchemy URL works
(SQLite today, Postgres etc. later) and is picked purely by the
``DATABASE_URL`` environment variable, or an explicit override passed by
callers (mainly tests).
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

ENV_VAR = "DATABASE_URL"
# In-memory SQLite by default: matches the old MemoryStore's behaviour of
# starting empty on every process (and every test) and persisting nothing.
DEFAULT_DATABASE_URL = "sqlite:///:memory:"


class Base(DeclarativeBase):
    pass


def resolve_database_url(url: str | None = None) -> str:
    return url or os.environ.get(ENV_VAR) or DEFAULT_DATABASE_URL


def make_engine(url: str | None = None) -> Engine:
    resolved = resolve_database_url(url)
    connect_args: dict = {}
    engine_kwargs: dict = {}
    if resolved.startswith("sqlite"):
        # Sessions are opened/closed per call from any thread (FastAPI's
        # threadpool), so SQLite's same-thread check has to be relaxed.
        connect_args["check_same_thread"] = False
        if ":memory:" in resolved:
            # An in-memory SQLite DB is per-connection; pin the pool to a
            # single, shared connection so all sessions see the same data.
            engine_kwargs["poolclass"] = StaticPool
    return create_engine(resolved, connect_args=connect_args, **engine_kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
