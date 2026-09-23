"""SQLAlchemy tables backing the SQL AppStore. See app/store.py's module
docstring for the dict shapes these mirror."""

from __future__ import annotations

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LeagueSettingsRow(Base):
    __tablename__ = "league_settings"

    class_id: Mapped[str] = mapped_column(String, primary_key=True)
    type_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    rate: Mapped[float] = mapped_column(Float, default=0.01)
    cap: Mapped[float] = mapped_column(Float, default=1.25)
    tie_breakers: Mapped[list] = mapped_column(JSON, default=list)
    weights: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class RiskSettingsRow(Base):
    __tablename__ = "risk_settings"

    class_id: Mapped[str] = mapped_column(String, primary_key=True)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[dict] = mapped_column(JSON, default=dict)


class BaselineRow(Base):
    __tablename__ = "baselines"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String, unique=True, index=True)
    class_id: Mapped[str] = mapped_column(String, index=True)
    student_id: Mapped[str] = mapped_column(String, index=True)
    work_hours: Mapped[float] = mapped_column(Float)
    childcare_hours: Mapped[float] = mapped_column(Float)
    eldercare_hours: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)
    effective_from_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[str] = mapped_column(String)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String, nullable=True)


class WeeklyUpdateRow(Base):
    __tablename__ = "weekly_updates"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String, unique=True, index=True)
    class_id: Mapped[str] = mapped_column(String, index=True)
    student_id: Mapped[str] = mapped_column(String, index=True)
    week_id: Mapped[str] = mapped_column(String)
    week_number: Mapped[int] = mapped_column(Integer)
    work_hours: Mapped[float] = mapped_column(Float)
    childcare_hours: Mapped[float] = mapped_column(Float)
    eldercare_hours: Mapped[float] = mapped_column(Float)
    entered_at: Mapped[str] = mapped_column(String)
    reversed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reversed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class NoteRow(Base):
    __tablename__ = "notes"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String, unique=True, index=True)
    instructor_id: Mapped[str] = mapped_column(String, index=True)
    class_id: Mapped[str] = mapped_column(String, index=True)
    student_id: Mapped[str] = mapped_column(String, index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String)
