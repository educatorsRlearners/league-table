"""In-memory stand-ins for the real database, to be replaced later.

`MockDatabase` implements the read-only `DataSource` interface (the "toy adapter"),
and `InMemorySettings` holds the app's own writable settings, kept apart from the
score data as the spec requires.
"""

from dataclasses import dataclass, field

from app.datasource import Entry, SourceUnavailable, Student
from app.models import Class, Criterion, Role, Week


@dataclass
class MockAccount:
    id: str
    role: Role
    student_id: str | None
    external_id: str
    email: str
    password: str


@dataclass
class MockDatabase:
    kind: str = "toy"
    label: str = "Demo data"
    classes: list[Class] = field(default_factory=list)
    students: list[Student] = field(default_factory=list)
    criteria: list[Criterion] = field(default_factory=list)
    weeks: list[Week] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    accounts: list[MockAccount] = field(default_factory=list)
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

    def list_accounts(self) -> list[MockAccount]:
        return list(self.accounts)


class InMemorySettings:
    """Saved criterion weights per class. Lost on restart, like everything in the mock."""

    def __init__(self) -> None:
        self._weights: dict[str, dict[str, float]] = {}

    def get_weights(self, class_id: str) -> dict[str, float] | None:
        saved = self._weights.get(class_id)
        return dict(saved) if saved is not None else None

    def save_weights(self, class_id: str, weights: dict[str, float]) -> None:
        self._weights[class_id] = dict(weights)
