"""The read-only DataSource interface every adapter implements, and what a read returns."""

from dataclasses import dataclass
from typing import Protocol

from app.models import Class, Criterion, Issue, Week


class SourceUnavailable(Exception):
    """The data source did not respond."""


@dataclass(frozen=True, slots=True)
class Student:
    id: str
    external_id: str
    class_id: str
    display_name: str
    nickname: str | None
    avatar_url: str | None
    active: bool


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    student_id: str
    criterion_id: str
    week_id: str
    earned: float | None
    possible: float | None
    recorded_at: str


class DataSource(Protocol):
    kind: str
    label: str

    def list_classes(self) -> list[Class]: ...

    def list_students(self, class_id: str) -> list[Student]: ...

    def list_criteria(self, class_id: str) -> list[Criterion]: ...

    def list_weeks(self, term_id: str) -> list[Week]: ...

    def get_entries(self, class_id: str) -> list[Entry]: ...


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One successful read of a class, cached by the service."""

    at: float
    cls: Class
    students: list[Student]
    criteria: list[Criterion]  # ordered by sort_order
    weeks: list[Week]  # oldest first
    entries: list[Entry]
    issues: list[Issue]
    stale: bool = False
