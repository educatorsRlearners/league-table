"""Read-write AppStore matching frontend createToyAppStore contract.

League settings: {weights|None, typeWeights, rate, cap, tieBreakers}
Baselines: {id, student_id, work_hours, childcare_hours, eldercare_hours,
  status, effective_from_week, submitted_at, decided_by, decided_at}
Weekly updates: {id, student_id, week_id, week_number, work_hours,
  childcare_hours, eldercare_hours, entered_at, reversed_by, reversed_at}
Risk settings: {thresholds, active}; risk snapshots: evaluation payloads.
Notes: {id, instructor_id, class_id, student_id, body, created_at}.

SqlAlchemyStore is the only implementation: it talks to whatever database
`DATABASE_URL` points at (see app/db.py), SQLite by default. It is written
against SQLAlchemy Core/ORM only, so a Postgres (or any other) URL works
without code changes here.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.db import Base, make_engine, make_session_factory
from app.db_models import (
    BaselineRow,
    LeagueSettingsRow,
    NoteRow,
    RiskSettingsRow,
    WeeklyUpdateRow,
)
from app.risk import DEFAULT_ACTIVE, DEFAULT_THRESHOLDS


def default_league_settings() -> dict:
    return {
        "typeWeights": {"work": 1, "childcare": 1, "eldercare": 1},
        "rate": 0.01,
        "cap": 1.25,
        "tieBreakers": ["attendance", "homework"],
    }


def default_risk_settings() -> dict:
    return {"thresholds": dict(DEFAULT_THRESHOLDS), "active": dict(DEFAULT_ACTIVE)}


class AppStore(Protocol):
    kind: str
    label: str

    def get_league_settings(self, class_id: str) -> dict: ...
    def save_league_settings(self, class_id: str, patch: dict) -> dict: ...
    def list_baselines(self, class_id: str) -> list[dict]: ...
    def list_weekly_updates(self, class_id: str) -> list[dict]: ...
    def get_commitments(self, class_id: str, student_id: str) -> dict: ...
    def get_risk_settings(self, class_id: str) -> dict: ...
    def save_risk_settings(self, class_id: str, patch: dict) -> dict: ...
    def add_note(self, *, class_id: str, student_id: str, instructor_id: str, body: str, at: str | None = None) -> dict: ...
    def list_notes(self, class_id: str, student_id: str | None, instructor_id: str) -> list[dict]: ...


_BASELINE_FIELDS = (
    "id", "student_id", "work_hours", "childcare_hours", "eldercare_hours",
    "status", "effective_from_week", "submitted_at", "decided_by", "decided_at",
)
_UPDATE_FIELDS = (
    "id", "student_id", "week_id", "week_number", "work_hours",
    "childcare_hours", "eldercare_hours", "entered_at", "reversed_by", "reversed_at",
)
_NOTE_FIELDS = ("id", "instructor_id", "class_id", "student_id", "body", "created_at")


def _row_to_dict(row, fields: tuple[str, ...]) -> dict:
    return {f: getattr(row, f) for f in fields}


class SqlAlchemyStore:
    kind = "sql"
    label = "SQL database"

    def __init__(self, engine: Engine | None = None, database_url: str | None = None,
                class_ids: list[str] | None = None, seed: dict | None = None) -> None:
        self._lock = threading.RLock()
        self._engine = engine or make_engine(database_url)
        Base.metadata.create_all(self._engine)
        self._Session = make_session_factory(self._engine)
        self._seed(class_ids or [], seed or {})

    # session helper

    def _session(self):
        return self._Session()

    # seeding (mirrors the old MemoryStore's constructor)

    def _seed(self, class_ids: list[str], seed: dict) -> None:
        with self._lock, self._session() as session:
            for cid in class_ids:
                if session.get(LeagueSettingsRow, cid) is None:
                    settings = seed.get("settings", {}).get(cid, default_league_settings())
                    weights = seed.get("weights", {}).get(cid)
                    session.add(LeagueSettingsRow(
                        class_id=cid, type_weights=settings["typeWeights"], rate=settings["rate"],
                        cap=settings["cap"], tie_breakers=settings["tieBreakers"], weights=weights,
                    ))
                if session.get(RiskSettingsRow, cid) is None:
                    rs = seed.get("risk_settings", {}).get(cid, default_risk_settings())
                    session.add(RiskSettingsRow(class_id=cid, thresholds=rs["thresholds"], active=rs["active"]))
                for b in seed.get("baselines", {}).get(cid, []):
                    if session.scalar(select(BaselineRow).where(BaselineRow.id == b["id"])) is None:
                        session.add(BaselineRow(class_id=cid, **{k: b[k] for k in _BASELINE_FIELDS}))
                for u in seed.get("weekly_updates", {}).get(cid, []):
                    if session.scalar(select(WeeklyUpdateRow).where(WeeklyUpdateRow.id == u["id"])) is None:
                        session.add(WeeklyUpdateRow(class_id=cid, **{k: u[k] for k in _UPDATE_FIELDS}))
            for n in seed.get("notes", []):
                if session.scalar(select(NoteRow).where(NoteRow.id == n["id"])) is None:
                    session.add(NoteRow(**{k: n[k] for k in _NOTE_FIELDS}))
            session.commit()

    def _get_or_create_league_row(self, session, class_id: str) -> LeagueSettingsRow:
        row = session.get(LeagueSettingsRow, class_id)
        if row is None:
            defaults = default_league_settings()
            row = LeagueSettingsRow(class_id=class_id, type_weights=defaults["typeWeights"],
                                    rate=defaults["rate"], cap=defaults["cap"],
                                    tie_breakers=defaults["tieBreakers"], weights=None)
            session.add(row)
            session.commit()
        if session.get(RiskSettingsRow, class_id) is None:
            rs = default_risk_settings()
            session.add(RiskSettingsRow(class_id=class_id, thresholds=rs["thresholds"], active=rs["active"]))
            session.commit()
        return row

    @staticmethod
    def _league_dict(row: LeagueSettingsRow) -> dict:
        return {
            "typeWeights": dict(row.type_weights),
            "rate": row.rate,
            "cap": row.cap,
            "tieBreakers": list(row.tie_breakers),
            "weights": dict(row.weights) if row.weights is not None else None,
        }

    # league settings

    def get_league_settings(self, class_id: str) -> dict:
        with self._lock, self._session() as session:
            row = self._get_or_create_league_row(session, class_id)
            return self._league_dict(row)

    def save_league_settings(self, class_id: str, patch: dict) -> dict:
        with self._lock, self._session() as session:
            row = self._get_or_create_league_row(session, class_id)
            if "weights" in patch and patch["weights"] is not None:
                row.weights = dict(patch["weights"])
            for key, column in (("typeWeights", "type_weights"), ("rate", "rate"),
                                ("cap", "cap"), ("tieBreakers", "tie_breakers")):
                if key in patch and patch[key] is not None:
                    setattr(row, column, patch[key])
            session.commit()
            session.refresh(row)
            return self._league_dict(row)

    # commitments

    def list_baselines(self, class_id: str) -> list[dict]:
        with self._lock, self._session() as session:
            rows = session.scalars(
                select(BaselineRow).where(BaselineRow.class_id == class_id).order_by(BaselineRow.pk)
            ).all()
            return [_row_to_dict(r, _BASELINE_FIELDS) for r in rows]

    def list_weekly_updates(self, class_id: str) -> list[dict]:
        with self._lock, self._session() as session:
            rows = session.scalars(
                select(WeeklyUpdateRow).where(WeeklyUpdateRow.class_id == class_id).order_by(WeeklyUpdateRow.pk)
            ).all()
            return [_row_to_dict(r, _UPDATE_FIELDS) for r in rows]

    def get_commitments(self, class_id: str, student_id: str) -> dict:
        with self._lock, self._session() as session:
            baselines = session.scalars(
                select(BaselineRow)
                .where(BaselineRow.class_id == class_id, BaselineRow.student_id == student_id,
                       BaselineRow.status != "superseded")
                .order_by(BaselineRow.pk)
            ).all()
            baseline = _row_to_dict(baselines[-1], _BASELINE_FIELDS) if baselines else None
            updates = session.scalars(
                select(WeeklyUpdateRow)
                .where(WeeklyUpdateRow.class_id == class_id, WeeklyUpdateRow.student_id == student_id)
                .order_by(WeeklyUpdateRow.pk)
            ).all()
            return {"baseline": baseline, "weeklyUpdates": [_row_to_dict(u, _UPDATE_FIELDS) for u in updates]}

    # risk

    def get_risk_settings(self, class_id: str) -> dict:
        with self._lock, self._session() as session:
            row = session.get(RiskSettingsRow, class_id)
            if row is None:
                defaults = default_risk_settings()
                row = RiskSettingsRow(class_id=class_id, thresholds=defaults["thresholds"], active=defaults["active"])
                session.add(row)
                session.commit()
            return {"thresholds": dict(row.thresholds), "active": dict(row.active)}

    def save_risk_settings(self, class_id: str, patch: dict) -> dict:
        with self._lock, self._session() as session:
            row = session.get(RiskSettingsRow, class_id)
            if row is None:
                defaults = default_risk_settings()
                row = RiskSettingsRow(class_id=class_id, thresholds=defaults["thresholds"], active=defaults["active"])
                session.add(row)
            row.thresholds = {**row.thresholds, **(patch.get("thresholds") or {})}
            row.active = {**row.active, **(patch.get("active") or {})}
            session.commit()
            session.refresh(row)
            return {"thresholds": dict(row.thresholds), "active": dict(row.active)}

    # notes

    def add_note(self, *, class_id: str, student_id: str, instructor_id: str, body: str, at: str | None = None) -> dict:
        with self._lock, self._session() as session:
            existing_ids = session.scalars(select(NoteRow.id)).all()
            seq = 0
            for note_id in existing_ids:
                try:
                    seq = max(seq, int(str(note_id)[1:]))
                except ValueError:
                    pass
            row = NoteRow(
                id=f"n{seq + 1}", instructor_id=instructor_id, class_id=class_id, student_id=student_id,
                body=body, created_at=at or datetime.now(UTC).isoformat(),
            )
            session.add(row)
            session.commit()
            return _row_to_dict(row, _NOTE_FIELDS)

    def list_notes(self, class_id: str, student_id: str | None, instructor_id: str) -> list[dict]:
        with self._lock, self._session() as session:
            query = select(NoteRow).where(NoteRow.class_id == class_id, NoteRow.instructor_id == instructor_id)
            if student_id:
                query = query.where(NoteRow.student_id == student_id)
            rows = session.scalars(query.order_by(NoteRow.pk)).all()
            return [_row_to_dict(r, _NOTE_FIELDS) for r in rows]
