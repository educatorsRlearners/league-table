"""Read-only DataSource interface. Mirrors frontend DataSource contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models import Class, Criterion, Issue, Week


class SourceUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Student:
    id: str
    external_id: str
    class_id: str
    display_name: str
    nickname: str | None = None
    avatar_url: str | None = None
    active: bool = True
    joined_week: int = 1


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    student_id: str
    criterion_id: str
    week_id: str
    earned: float | None
    possible: float | None
    recorded_at: str
    criterion_key: str = ""

    def __post_init__(self):
        if not self.criterion_key:
            object.__setattr__(self, "criterion_key", self.criterion_id)


class DataSource(Protocol):
    kind: str
    label: str

    def list_classes(self, instructor_id: str | None = None) -> list[Class]: ...
    def list_students(self, class_id: str) -> list[Student]: ...
    def list_criteria(self, class_id: str) -> list[Criterion]: ...
    def list_weeks(self, term_id: str | None = None) -> list[Week]: ...
    def get_entries(self, class_id: str, week_ids: list[str] | None = None,
                    criterion_keys: list[str] | None = None) -> list[Entry]: ...
    def list_accounts(self) -> list[dict]: ...


@dataclass(frozen=True, slots=True)
class Snapshot:
    at: float
    class_id: str
    students: list[Student]
    criteria: list[Criterion]
    weeks: list[Week]
    entries: list[Entry]
    baselines: list[dict]
    weekly_updates: list[dict]
    settings: dict
    issues: list[Issue]
    stale: bool = False
