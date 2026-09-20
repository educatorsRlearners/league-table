"""Reads the data source through a cache, so the UI never waits on it and never goes blank."""

import math
import threading
from dataclasses import replace
from typing import Callable

from app.datasource import DataSource, SourceUnavailable, Snapshot
from app.errors import RefreshTooSoon
from app.models import Issue

CACHE_TTL_SECONDS = 60
REFRESH_COOLDOWN_SECONDS = 10

Clock = Callable[[], float]


def _number(value: float) -> str:
    return f"{value:g}"


def data_check(students, entries) -> list[Issue]:
    """Validate a read and list the problems instead of failing the whole table."""
    known = {s.id for s in students}
    issues = []
    for entry in entries:
        if entry.student_id not in known:
            issues.append(Issue(level="error", where=entry.id, message=f'Unknown student ID "{entry.student_id}"'))
        elif entry.earned is None or not math.isfinite(entry.earned):
            issues.append(Issue(level="error", where=entry.id, message=f"Non-numeric score for {entry.student_id}"))
        elif entry.possible is not None and entry.earned > entry.possible:
            issues.append(
                Issue(
                    level="warning",
                    where=entry.id,
                    message=f"{entry.student_id}: {_number(entry.earned)} earned of {_number(entry.possible)} possible",
                )
            )
    return issues


class LeagueService:
    def __init__(
        self,
        source: DataSource,
        clock: Clock,
        *,
        ttl: float = CACHE_TTL_SECONDS,
        cooldown: float = REFRESH_COOLDOWN_SECONDS,
    ):
        self.source = source
        self._clock = clock
        self._ttl = ttl
        self._cooldown = cooldown
        self._class_ids = {c.id for c in source.list_classes()}
        self._cache: dict[str, Snapshot] = {}
        self._last_refresh: dict[str, float] = {}
        self._lock = threading.RLock()

    def has_class(self, class_id: str) -> bool:
        return class_id in self._class_ids

    def cached(self, class_id: str) -> Snapshot | None:
        """The last good snapshot, if any. Never reads the source."""
        return self._cache.get(class_id)

    def snapshot(self, class_id: str, *, force: bool = False) -> Snapshot:
        """A fresh-enough snapshot; re-reads the source when the cache has expired.

        If the source fails and a snapshot exists, that snapshot is returned marked
        stale. With nothing cached the failure propagates as SourceUnavailable.
        """
        with self._lock:
            cached = self._cache.get(class_id)
            if cached and not force and self._clock() - cached.at < self._ttl:
                return cached
            try:
                fresh = self._read(class_id)
            except SourceUnavailable:
                if cached is None:
                    raise
                stale = replace(cached, stale=True)
                self._cache[class_id] = stale
                return stale
            self._cache[class_id] = fresh
            return fresh

    def refresh(self, class_id: str) -> Snapshot:
        """Re-read now, at most once per cooldown. Raises RefreshTooSoon inside it."""
        with self._lock:
            now = self._clock()
            last = self._last_refresh.get(class_id)
            if last is not None and now - last < self._cooldown:
                raise RefreshTooSoon(math.ceil(self._cooldown - (now - last)))
            self._last_refresh[class_id] = now
            return self.snapshot(class_id, force=True)

    def _read(self, class_id: str) -> Snapshot:
        cls = next(c for c in self.source.list_classes() if c.id == class_id)
        students = self.source.list_students(class_id)
        criteria = sorted(self.source.list_criteria(class_id), key=lambda c: c.sort_order)
        weeks = sorted(self.source.list_weeks(cls.term_id), key=lambda w: w.week_number)
        entries = self.source.get_entries(class_id)
        return Snapshot(
            at=self._clock(),
            cls=cls,
            students=students,
            criteria=criteria,
            weeks=weeks,
            entries=entries,
            issues=data_check(students, entries),
        )
