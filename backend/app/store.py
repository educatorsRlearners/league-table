"""The read-write AppStore: accounts, commitments, approvals, the change log and settings.

Scores come from the read-only `DataSource`; everything a person enters or an instructor
decides lives here. `MemoryStore` is the in-memory adapter used for demos and tests. Any
other adapter (SQLite, later) implements the same `AppStore` protocol and must pass
`tests/test_store_contract.py`.

Every method that changes a commitment takes the change-log entry to write with it, so a
change and its log entry are saved together or not at all.
"""

import threading
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

Role = Literal["instructor", "student"]
BaselineStatus = Literal["pending", "approved", "rejected", "superseded"]
Hours = dict[str, float]

# The commitment types are a configured list, so a fourth can be added without a schema change.
COMMITMENT_TYPES: tuple[tuple[str, str], ...] = (
    ("work", "Work"),
    ("childcare", "Child care"),
    ("eldercare", "Elder care"),
)
TYPE_KEYS = tuple(key for key, _ in COMMITMENT_TYPES)


@dataclass(frozen=True, slots=True)
class StoredAccount:
    id: str
    role: Role
    student_id: str | None
    external_id: str
    access_code_hash: str | None  # None for the instructor, who signs in with the passcode


@dataclass(frozen=True, slots=True)
class Baseline:
    """One set of weekly hours for the whole semester, pending the instructor's decision.

    `superseded` covers two cases: a pending baseline replaced by a newer submission
    (it has no effective week and never counts), and an approved baseline replaced by a
    later approval (it still counts for the weeks before the new one starts).
    """

    id: str
    student_id: str
    hours: Hours
    status: BaselineStatus
    submitted_at: str
    effective_from_week: int | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    decision_seq: int | None = None  # order of approval; the latest approval wins where they overlap


@dataclass(frozen=True, slots=True)
class WeeklyUpdate:
    """One submission of hours for one week. `hours=None` means "reset to the baseline".

    Submissions are kept, never overwritten: the active one for a week is the latest that
    has not been reversed, so reversing it restores the value before it.
    """

    id: str
    student_id: str
    week_id: str
    hours: Hours | None
    entered_at: str
    entry_id: str  # the change-log entry written with it
    reversed_by: str | None = None
    reversed_at: str | None = None


@dataclass(frozen=True, slots=True)
class LogEntry:
    id: str
    actor_id: str
    action: str
    student_id: str | None
    week_id: str | None
    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None
    at: str
    flagged: bool = False


@dataclass(frozen=True, slots=True)
class AdjustmentSettings:
    """The parameters a, r and f_max of the adjustment, plus the review flag."""

    type_weights: Hours = field(default_factory=lambda: {key: 1.0 for key in TYPE_KEYS})
    rate: float = 0.01
    cap: float = 1.25
    flag_hours: float = 10.0  # flag a weekly entry that differs from the baseline by more than this


@dataclass(frozen=True, slots=True)
class Settings:
    weights: dict[str, float] | None = None  # criterion weights; None means the criteria's defaults
    adjustment: AdjustmentSettings = field(default_factory=AdjustmentSettings)


class AppStore(Protocol):
    kind: str

    def get_account(self, account_id: str) -> StoredAccount | None: ...

    def get_account_by_code(self, access_code_hash: str) -> StoredAccount | None: ...

    def list_accounts(self) -> list[StoredAccount]: ...

    def list_baselines(self, student_id: str | None = None) -> list[Baseline]: ...

    def get_baseline(self, baseline_id: str) -> Baseline | None: ...

    def save_baseline(self, student_id: str, hours: Hours, at: str, entry: LogEntry) -> Baseline:
        """Store a new pending baseline, superseding any pending one, and log it."""

    def decide_baseline(
        self,
        baseline_id: str,
        *,
        status: Literal["approved", "rejected"],
        effective_from_week: int | None,
        decided_by: str,
        at: str,
        entry: LogEntry,
    ) -> Baseline:
        """Approve or reject a pending baseline and log it. Approving supersedes the old approved one."""

    def list_weekly_updates(self, student_id: str | None = None) -> list[WeeklyUpdate]: ...

    def save_weekly_update(
        self, student_id: str, week_id: str, hours: Hours | None, at: str, entry: LogEntry
    ) -> WeeklyUpdate: ...

    def reverse_weekly_update(self, update_id: str, *, reversed_by: str, at: str, entry: LogEntry) -> WeeklyUpdate: ...

    def append_log(self, entry: LogEntry) -> LogEntry: ...

    def list_log(self, student_id: str | None = None) -> list[LogEntry]:
        """Oldest first."""

    def get_settings(self, class_id: str) -> Settings: ...

    def save_settings(self, class_id: str, settings: Settings, entry: LogEntry | None = None) -> Settings: ...


class MemoryStore:
    """In memory: lost on restart, so a demo always starts clean."""

    kind = "memory"

    def __init__(self, accounts: list[StoredAccount] | None = None) -> None:
        self._lock = threading.RLock()
        self._accounts = list(accounts or [])
        self._baselines: list[Baseline] = []
        self._updates: list[WeeklyUpdate] = []
        self._log: list[LogEntry] = []
        self._settings: dict[str, Settings] = {}
        self._next = {"baseline": 0, "update": 0, "log": 0, "decision": 0}

    def _id(self, kind: str, prefix: str) -> str:
        self._next[kind] += 1
        return f"{prefix}{self._next[kind]}"

    def _log_entry(self, entry: LogEntry) -> LogEntry:
        stored = replace(entry, id=self._id("log", "l"))
        self._log.append(stored)
        return stored

    # accounts

    def get_account(self, account_id: str) -> StoredAccount | None:
        return next((a for a in self._accounts if a.id == account_id), None)

    def get_account_by_code(self, access_code_hash: str) -> StoredAccount | None:
        return next(
            (a for a in self._accounts if a.access_code_hash and a.access_code_hash == access_code_hash), None
        )

    def list_accounts(self) -> list[StoredAccount]:
        return list(self._accounts)

    # baselines

    def list_baselines(self, student_id: str | None = None) -> list[Baseline]:
        with self._lock:
            return [b for b in self._baselines if student_id is None or b.student_id == student_id]

    def get_baseline(self, baseline_id: str) -> Baseline | None:
        with self._lock:
            return next((b for b in self._baselines if b.id == baseline_id), None)

    def save_baseline(self, student_id: str, hours: Hours, at: str, entry: LogEntry) -> Baseline:
        with self._lock:
            self._baselines = [
                replace(b, status="superseded") if b.student_id == student_id and b.status == "pending" else b
                for b in self._baselines
            ]
            baseline = Baseline(
                id=self._id("baseline", "b"), student_id=student_id, hours=dict(hours),
                status="pending", submitted_at=at,
            )
            self._baselines.append(baseline)
            self._log_entry(entry)
            return baseline

    def decide_baseline(self, baseline_id, *, status, effective_from_week, decided_by, at, entry) -> Baseline:
        with self._lock:
            current = self.get_baseline(baseline_id)
            if current is None or current.status != "pending":
                raise LookupError("Only a pending baseline can be decided.")
            decided = replace(
                current, status=status, decided_by=decided_by, decided_at=at,
                effective_from_week=effective_from_week if status == "approved" else None,
                decision_seq=self._next_decision() if status == "approved" else None,
            )
            self._baselines = [
                decided if b.id == baseline_id
                else replace(b, status="superseded")
                if status == "approved" and b.student_id == current.student_id and b.status == "approved"
                else b
                for b in self._baselines
            ]
            self._log_entry(entry)
            return decided

    def _next_decision(self) -> int:
        self._next["decision"] += 1
        return self._next["decision"]

    # weekly updates

    def list_weekly_updates(self, student_id: str | None = None) -> list[WeeklyUpdate]:
        with self._lock:
            return [u for u in self._updates if student_id is None or u.student_id == student_id]

    def save_weekly_update(self, student_id, week_id, hours, at, entry) -> WeeklyUpdate:
        with self._lock:
            logged = self._log_entry(entry)
            update = WeeklyUpdate(
                id=self._id("update", "u"), student_id=student_id, week_id=week_id,
                hours=None if hours is None else dict(hours), entered_at=at, entry_id=logged.id,
            )
            self._updates.append(update)
            return update

    def reverse_weekly_update(self, update_id, *, reversed_by, at, entry) -> WeeklyUpdate:
        with self._lock:
            current = next((u for u in self._updates if u.id == update_id), None)
            if current is None or current.reversed_at is not None:
                raise LookupError("There is no weekly update to reverse.")
            reversed_ = replace(current, reversed_by=reversed_by, reversed_at=at)
            self._updates = [reversed_ if u.id == update_id else u for u in self._updates]
            self._log_entry(entry)
            return reversed_

    # log

    def append_log(self, entry: LogEntry) -> LogEntry:
        with self._lock:
            return self._log_entry(entry)

    def list_log(self, student_id: str | None = None) -> list[LogEntry]:
        with self._lock:
            return [e for e in self._log if student_id is None or e.student_id == student_id]

    # settings

    def get_settings(self, class_id: str) -> Settings:
        with self._lock:
            return self._settings.get(class_id, Settings())

    def save_settings(self, class_id: str, settings: Settings, entry: LogEntry | None = None) -> Settings:
        with self._lock:
            self._settings[class_id] = settings
            if entry is not None:
                self._log_entry(entry)
            return settings
