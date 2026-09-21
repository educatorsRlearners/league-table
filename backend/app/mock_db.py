"""The toy adapter: an in-memory implementation of the read-only `DataSource` interface.

Only scores live here. Accounts, commitments and settings belong to the `AppStore`.
"""

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
    fail: bool = False  # simulate the source being unreachable

    @classmethod
    def toy(cls) -> "MockDatabase":
        from app.toy_seed import build_toy_database

        return build_toy_database()

    def _reachable(self) -> None:
        if self.fail:
            raise SourceUnavailable()

    def list_classes(self) -> list[Class]:
        self._reachable()
        return [c.model_copy() for c in self.classes]

    def list_students(self, class_id: str) -> list[Student]:
        self._reachable()
        return [s for s in self.students if s.class_id == class_id]

    def list_criteria(self, class_id: str) -> list[Criterion]:
        self._reachable()
        return [c.model_copy() for c in self.criteria if c.class_id == class_id]

    def list_weeks(self, term_id: str) -> list[Week]:
        self._reachable()
        return [w.model_copy() for w in self.weeks if w.term_id == term_id]

    def get_entries(self, class_id: str) -> list[Entry]:
        self._reachable()
        criterion_ids = {c.id for c in self.criteria if c.class_id == class_id}
        return [e for e in self.entries if e.criterion_id in criterion_ids]

