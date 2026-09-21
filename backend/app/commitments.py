"""The time-commitment adjustment: pure rules, no I/O.

    H = sum(a_k * h_k)          weighted commitment hours for the week
    f = min(1 + r * H, f_max)   the factor, capped
    adjusted = min(100, raw * f)

A student whose baseline is not approved (for that week) has a factor of 1.00 whatever
they entered. All of it works on the normalised types, never on an adapter's.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

from app.models import Week
from app.store import TYPE_KEYS, AdjustmentSettings, Baseline, Hours, WeeklyUpdate

STEP = 0.5
PER_TYPE_MAX = 80.0
TOTAL_MAX = 120.0
FULL_MARKS = 100.0


class InvalidHours(ValueError):
    """The hours break a rule; the message says which and is safe to show."""


def validate_hours(hours: dict[str, float]) -> Hours:
    """Every type as a number, in half-hour steps, within the limits. Missing types are 0."""
    unknown = sorted(set(hours) - set(TYPE_KEYS))
    if unknown:
        raise InvalidHours(f"Unknown commitment type: {', '.join(unknown)}")
    clean: Hours = {}
    for key in TYPE_KEYS:
        value = float(hours.get(key, 0.0))
        if not math.isfinite(value) or value < 0:
            raise InvalidHours(f"{key}: hours must be zero or more.")
        if value > PER_TYPE_MAX:
            raise InvalidHours(f"{key}: at most {PER_TYPE_MAX:g} hours a week.")
        if (value / STEP) != round(value / STEP):
            raise InvalidHours(f"{key}: hours go up in steps of {STEP:g}.")
        clean[key] = value
    if sum(clean.values()) > TOTAL_MAX:
        raise InvalidHours(f"At most {TOTAL_MAX:g} hours a week in total.")
    return clean


def validate_adjustment(settings: AdjustmentSettings) -> AdjustmentSettings:
    if set(settings.type_weights) != set(TYPE_KEYS):
        raise InvalidHours("Give a weight for every commitment type.")
    if any(not math.isfinite(w) or w < 0 for w in settings.type_weights.values()):
        raise InvalidHours("Type weights must be zero or more.")
    if not math.isfinite(settings.rate) or not 0 <= settings.rate <= 1:
        raise InvalidHours("The rate must be between 0 and 1.")
    if not math.isfinite(settings.cap) or not 1 <= settings.cap <= 3:
        raise InvalidHours("The cap must be between 1 and 3.")
    if not math.isfinite(settings.flag_hours) or settings.flag_hours < 0:
        raise InvalidHours("The review threshold must be zero or more.")
    return settings


def weighted_hours(hours: Hours, params: AdjustmentSettings) -> Hours:
    """Hours by type after each type's weight `a`."""
    return {key: params.type_weights.get(key, 1.0) * hours.get(key, 0.0) for key in TYPE_KEYS}


def factor_for(total_weighted_hours: float, params: AdjustmentSettings) -> float:
    return min(1 + params.rate * total_weighted_hours, params.cap)


@dataclass(frozen=True, slots=True)
class Adjustment:
    hours: Hours | None  # what applies that week; None when no approved baseline does
    weighted: Hours
    weighted_total: float
    factor: float
    raw: float
    adjusted: float
    capped: bool  # the adjusted score was clipped at 100


def adjust(raw: float, hours: Hours | None, params: AdjustmentSettings) -> Adjustment:
    if hours is None:
        weighted = {key: 0.0 for key in TYPE_KEYS}
        total, factor = 0.0, 1.0
    else:
        weighted = weighted_hours(hours, params)
        total = sum(weighted.values())
        factor = factor_for(total, params)
    scaled = raw * factor
    return Adjustment(
        hours=hours, weighted=weighted, weighted_total=total, factor=factor, raw=raw,
        adjusted=min(FULL_MARKS, scaled), capped=scaled > FULL_MARKS + 1e-9,
    )


class CommitmentBook:
    """Who has which hours in which week, from the stored baselines and weekly updates."""

    def __init__(self, baselines: list[Baseline], updates: list[WeeklyUpdate]) -> None:
        self._baselines: dict[str, list[Baseline]] = {}
        for baseline in baselines:
            self._baselines.setdefault(baseline.student_id, []).append(baseline)
        self._updates: dict[tuple[str, str], list[WeeklyUpdate]] = {}
        for update in updates:
            self._updates.setdefault((update.student_id, update.week_id), []).append(update)

    def baseline_for(self, student_id: str, week_number: int) -> Baseline | None:
        """The approved baseline in force that week: the latest approval that has started."""
        started = [
            b
            for b in self._baselines.get(student_id, [])
            if b.status in ("approved", "superseded")
            and b.effective_from_week is not None
            and b.effective_from_week <= week_number
        ]
        return max(started, key=lambda b: b.decision_seq or 0, default=None)

    def active_update(self, student_id: str, week_id: str) -> WeeklyUpdate | None:
        live = [u for u in self._updates.get((student_id, week_id), []) if u.reversed_at is None]
        return live[-1] if live else None

    def hours_for(self, student_id: str, week: Week) -> Hours | None:
        """The hours that count for that week, or None (factor 1.00) without an approved baseline."""
        baseline = self.baseline_for(student_id, week.week_number)
        if baseline is None:
            return None
        update = self.active_update(student_id, week.id)
        return baseline.hours if update is None or update.hours is None else update.hours


class Adjuster:
    """Applies the settings and the book to a student's raw score for a week."""

    def __init__(self, params: AdjustmentSettings, book: CommitmentBook) -> None:
        self.params = params
        self.book = book

    def apply(self, student_id: str, week: Week, raw: float) -> Adjustment:
        return adjust(raw, self.book.hours_for(student_id, week), self.params)


def week_span(weeks: list[Week], index: int) -> tuple[date, date]:
    """First day, and the day after the last, of a week: it runs until the next one starts."""
    start = weeks[index].start_date
    end = weeks[index + 1].start_date if index + 1 < len(weeks) else start + timedelta(days=7)
    return start, end


def current_week(weeks: list[Week], today: date) -> Week | None:
    """The week that contains `today` on the server's clock, or None outside the term."""
    for index, week in enumerate(weeks):
        start, end = week_span(weeks, index)
        if start <= today < end:
            return week
    return None


def editable_weeks(weeks: list[Week], today: date) -> list[Week]:
    """A student can edit the current week and the previous one. Older weeks are locked."""
    current = current_week(weeks, today)
    if current is None:
        return []
    index = weeks.index(current)
    return weeks[max(0, index - 1) : index + 1]
