"""Snapshot cache + shared ranking/risk helpers. Mirrors api.js load()/buildRows."""

from __future__ import annotations

import math
import threading
from typing import Callable

from app.datasource import DataSource, Snapshot, SourceUnavailable
from app.errors import RefreshTooSoon
from app.models import Issue
from app.risk import evaluate_signals
from app.scoring import (
    adjust,
    commitment_factor,
    display_name,
    gap_to_below,
    gap_to_next,
    mean,
    normalise_weights,
    rank_rows,
    resolve_hours,
    score_student,
    weighted_hours,
)

CACHE_TTL_SECONDS = 60
REFRESH_COOLDOWN_SECONDS = 10
DEFAULT_ROLLING_N = 4
LEVEL_ORDER = ["Not flagged", "Watch", "At risk", "High risk"]

Clock = Callable[[], float]


def data_check(students, entries) -> list[Issue]:
    ids = {s.id for s in students}
    issues = []
    for e in entries:
        if e.student_id not in ids:
            issues.append(Issue(level="error", where=e.id, message=f'Unknown student ID "{e.student_id}"'))
        elif not isinstance(e.earned, (int, float)) or (isinstance(e.earned, float) and (math.isnan(e.earned))):
            issues.append(Issue(level="error", where=e.id, message=f"Non-numeric score for {e.student_id}"))
        elif e.possible is not None and e.earned > e.possible:
            issues.append(Issue(level="warning", where=e.id,
                                message=f"{e.student_id}: {e.earned:g} earned of {e.possible:g} possible"))
    return issues


def window_weeks(weeks, week_id: str, window_mode: str, rolling_n: int = DEFAULT_ROLLING_N):
    idx = next((i for i, w in enumerate(weeks) if w.id == week_id), -1)
    if idx < 0:
        return []
    if window_mode == "cumulative":
        return weeks[: idx + 1]
    if window_mode == "rolling":
        return weeks[max(0, idx + 1 - rolling_n): idx + 1]
    return [weeks[idx]]


def latest_complete_week_id(snapshot: Snapshot) -> str | None:
    counts: dict[str, int] = {}
    for e in snapshot.entries:
        counts[e.week_id] = counts.get(e.week_id, 0) + 1
    if not counts:
        return snapshot.weeks[0].id if snapshot.weeks else None
    peak = max(counts.values())
    complete = [w for w in snapshot.weeks if counts.get(w.id, 0) >= peak * 0.8]
    any_weeks = [w for w in snapshot.weeks if w.id in counts]
    pool = complete or any_weeks
    return pool[-1].id if pool else None


def evaluation_week_number(snapshot: Snapshot) -> int:
    wid = latest_complete_week_id(snapshot)
    week = next((w for w in snapshot.weeks if w.id == wid), None)
    return week.week_number if week else snapshot.weeks[0].week_number


def resolved_weights(snapshot: Snapshot, keys: list[str], override: dict | None) -> dict:
    defaults = {c.key: c.default_weight for c in snapshot.criteria}
    base = override if override is not None else (snapshot.settings.get("weights") or defaults)
    return normalise_weights({k: (base.get(k, 0) or 0) for k in keys})


def _criteria_by_key(snapshot: Snapshot) -> dict:
    return {c.key: c for c in snapshot.criteria}


def student_weeks(snapshot: Snapshot, student, wks, criteria, criteria_keys: list[str], weights: dict):
    baseline = next((b for b in snapshot.baselines if b["student_id"] == student.id and b["status"] != "superseded"), None)
    updates = [u for u in snapshot.weekly_updates if u["student_id"] == student.id]
    type_weights = snapshot.settings.get("typeWeights", {"work": 1, "childcare": 1, "eldercare": 1})
    rate = snapshot.settings.get("rate", 0.01)
    cap = snapshot.settings.get("cap", 1.25)
    out = []
    for w in wks:
        entries = [e for e in snapshot.entries
                   if e.week_id == w.id and e.student_id == student.id and e.criterion_key in criteria_keys]
        if not entries:
            continue
        result = score_student(entries=[{"criterion_key": e.criterion_key, "earned": e.earned, "possible": e.possible}
                                        for e in entries],
                               criteria=[{"key": c.key, "label": c.label} for c in criteria],
                               weights=weights)
        if result["score"] is None:
            continue
        resolved = resolve_hours(baseline=baseline, weekly_updates=updates, week_number=w.week_number)
        h = weighted_hours(resolved["hours"], type_weights)
        factor = commitment_factor(h, rate, cap)
        adj = adjust(result["score"], factor)
        out.append({
            "week_id": w.id, "week_number": w.week_number, "raw": result["score"],
            "hours": resolved["hours"], "hours_source": resolved["source"],
            "weighted_hours": h, "factor": factor, "adjusted": adj["adjusted"], "capped": adj["capped"],
            "parts": result["parts"], "missingKeys": result["missingKeys"],
        })
    return out


def build_rows(snapshot: Snapshot, *, week_id: str, window_mode: str = "week",
               rolling_n: int = DEFAULT_ROLLING_N, weights: dict, criteria_keys: list[str],
               name_mode: str = "full") -> list[dict]:
    criteria = [c for c in snapshot.criteria if c.key in criteria_keys]
    wks = window_weeks(snapshot.weeks, week_id, window_mode, rolling_n)
    tie_breakers = snapshot.settings.get("tieBreakers", []) or []
    rows = []
    for s in snapshot.students:
        week_rows = student_weeks(snapshot, s, wks, criteria, criteria_keys, weights)
        if not week_rows:
            continue
        last = week_rows[-1]
        norm_by_key = {p["key"]: (p["normalised"] if p["normalised"] is not None else -1) for p in last["parts"]}
        rows.append({
            "student_id": s.id,
            "display_name": display_name({"display_name": s.display_name, "nickname": s.nickname}, name_mode),
            "full_name": s.display_name,
            "score": mean([r["adjusted"] for r in week_rows]),
            "raw": mean([r["raw"] for r in week_rows]),
            "factor": mean([r["factor"] for r in week_rows]),
            "weighted_hours": mean([r["weighted_hours"] for r in week_rows]),
            "capped": any(r["capped"] for r in week_rows),
            "hours_source": last["hours_source"],
            "weeks": week_rows,
            "parts": last["parts"],
            "missingKeys": last["missingKeys"],
            "normalisedByKey": norm_by_key,
        })
    ranked = rank_rows(rows, tie_breakers)
    for i, r in enumerate(ranked):
        r["gap_to_next"] = gap_to_next(ranked, i)
        r["gap_to_below"] = gap_to_below(ranked, i)
    return ranked


def risk_weekly(snapshot: Snapshot, student, up_to_week: int) -> list[dict]:
    defaults = {c.key: c.default_weight for c in snapshot.criteria}
    w100 = normalise_weights(snapshot.settings.get("weights") or defaults)
    out = []
    for w in snapshot.weeks:
        joined = getattr(student, "joined_week", 1) or 1
        if not (joined <= w.week_number <= up_to_week):
            continue
        entries = [e for e in snapshot.entries if e.week_id == w.id and e.student_id == student.id]
        by_key: dict[str, dict] = {}
        for e in entries:
            slot = by_key.setdefault(e.criterion_key, {"earned": 0, "possible": 0})
            slot["earned"] += e.earned or 0
            slot["possible"] += e.possible or 0
        result = None
        if entries:
            result = score_student(
                entries=[{"criterion_key": e.criterion_key, "earned": e.earned, "possible": e.possible} for e in entries],
                criteria=[{"key": c.key, "label": c.label} for c in snapshot.criteria],
                weights=w100)
        out.append({"week_number": w.week_number, "raw": result["score"] if result else None,
                    "hasEntries": len(entries) > 0, "byKey": by_key})
    return out


def hours_at(snapshot: Snapshot, student, week_number: int) -> float:
    baseline = next((b for b in snapshot.baselines if b["student_id"] == student.id and b["status"] != "superseded"), None)
    updates = [u for u in snapshot.weekly_updates if u["student_id"] == student.id]
    resolved = resolve_hours(baseline=baseline, weekly_updates=updates, week_number=week_number)
    return weighted_hours(resolved["hours"], snapshot.settings.get("typeWeights", {}))


class LeagueService:
    def __init__(self, source: DataSource, store, clock: Clock,
                 ttl: float = CACHE_TTL_SECONDS, cooldown: float = REFRESH_COOLDOWN_SECONDS):
        self.source = source
        self.store = store
        self._clock = clock
        self._ttl = ttl
        self._cooldown = cooldown
        self._cache: dict[str, Snapshot] = {}
        self._last_refresh: dict[str, float] = {}
        self._lock = threading.RLock()

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def has_class(self, class_id: str) -> bool:
        try:
            return any(c.id == class_id for c in self.source.list_classes())
        except SourceUnavailable:
            return class_id in self._cache

    def cached(self, class_id: str) -> Snapshot | None:
        return self._cache.get(class_id)

    def snapshot(self, class_id: str, *, force: bool = False) -> Snapshot:
        with self._lock:
            cached = self._cache.get(class_id)
            if cached and not force and (self._clock() - cached.at) < self._ttl:
                return cached
            try:
                fresh = self._read(class_id)
            except SourceUnavailable:
                if cached is None:
                    raise
                stale = Snapshot(at=cached.at, class_id=cached.class_id, students=cached.students,
                                 criteria=cached.criteria, weeks=cached.weeks, entries=cached.entries,
                                 baselines=cached.baselines, weekly_updates=cached.weekly_updates,
                                 settings=cached.settings, issues=cached.issues, stale=True)
                self._cache[class_id] = stale
                return stale
            self._cache[class_id] = fresh
            return fresh

    def refresh(self, class_id: str) -> Snapshot:
        with self._lock:
            now = self._clock()
            last = self._last_refresh.get(class_id)
            if last is not None and now - last < self._cooldown:
                raise RefreshTooSoon(math.ceil(self._cooldown - (now - last)))
            self._last_refresh[class_id] = now
            return self.snapshot(class_id, force=True)

    def _read(self, class_id: str) -> Snapshot:
        classes = self.source.list_classes()
        klass = next(c for c in classes if c.id == class_id)
        students = self.source.list_students(class_id)
        criteria = sorted(self.source.list_criteria(class_id), key=lambda c: c.sort_order)
        weeks = sorted(self.source.list_weeks(klass.term_id), key=lambda w: w.week_number)
        entries = self.source.get_entries(class_id)
        baselines = self.store.list_baselines(class_id)
        updates = self.store.list_weekly_updates(class_id)
        settings = self.store.get_league_settings(class_id)
        issues = data_check(students, entries)
        return Snapshot(at=self._clock(), class_id=class_id, students=students, criteria=criteria,
                        weeks=weeks, entries=entries, baselines=baselines, weekly_updates=updates,
                        settings=settings, issues=issues, stale=False)

    def evaluate_class(self, class_id: str, up_to_week: int | None = None) -> dict:
        snap = self.snapshot(class_id)
        risk_settings = self.store.get_risk_settings(class_id)
        week = up_to_week if up_to_week is not None else evaluation_week_number(snap)
        rows = []
        for s in snap.students:
            weekly = risk_weekly(snap, s, week)
            ev = evaluate_signals(weekly=weekly, hours=hours_at(snap, s, week),
                                  thresholds=risk_settings["thresholds"], active=risk_settings["active"])
            rows.append({"student_id": s.id, "display_name": s.display_name,
                         "week_number": week, **ev})
        return {"week": week, "settings": risk_settings, "rows": rows}
