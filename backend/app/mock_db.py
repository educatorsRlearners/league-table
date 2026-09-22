"""In-memory toy DataSource. Ported from frontend/services/mockSource.js."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.datasource import Entry, SourceUnavailable, Student
from app.models import Class, Criterion, Week


@dataclass
class MockDatabase:
    kind: str = "toy"
    label: str = "Demo data"
    classes: list[Class] = field(default_factory=list)
    students: list[Student] = field(default_factory=list)
    criteria: list[Criterion] = field(default_factory=list)
    weeks: list[Week] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    accounts: list[dict] = field(default_factory=list)
    fail: bool = False

    def _reachable(self) -> None:
        if self.fail:
            raise SourceUnavailable()

    def list_classes(self, instructor_id: str | None = None) -> list[Class]:
        self._reachable()
        if instructor_id is None:
            return [c.model_copy() for c in self.classes]
        return [c.model_copy() for c in self.classes if c.instructor_id == instructor_id]

    def list_students(self, class_id: str) -> list[Student]:
        self._reachable()
        return [s for s in self.students if s.class_id == class_id]

    def list_criteria(self, class_id: str) -> list[Criterion]:
        self._reachable()
        return [c.model_copy() for c in self.criteria if c.class_id == class_id]

    def list_weeks(self, term_id: str | None = None) -> list[Week]:
        self._reachable()
        if term_id is None:
            return [w.model_copy() for w in self.weeks]
        return [w.model_copy() for w in self.weeks if w.term_id == term_id]

    def get_entries(self, class_id: str, week_ids: list[str] | None = None,
                    criterion_keys: list[str] | None = None) -> list[Entry]:
        self._reachable()
        out = []
        for e in self.entries:
            if e.criterion_key.split(":")[0] if False else None:
                pass
            # entries store class via criterion prefix? use lookup map instead
            out.append(e)
        # filter by class: entries ids start with classId-e
        out = [e for e in out if e.id.startswith(f"{class_id}-e")]
        if week_ids is not None:
            out = [e for e in out if e.week_id in week_ids]
        if criterion_keys is not None:
            out = [e for e in out if e.criterion_key in criterion_keys]
        return list(out)

    def list_accounts(self) -> list[dict]:
        self._reachable()
        return [dict(a) for a in self.accounts]
