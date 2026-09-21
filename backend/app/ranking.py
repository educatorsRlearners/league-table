"""Turns a snapshot into a ranked table: windows, the adjustment, ties, gaps and movement.

Each week is scored on its own (criteria, then the commitments factor, capped at 100).
A window of several weeks averages the weekly adjusted scores, so a week's factor and cap
apply to that week only and an average never exceeds 100.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import fmean

from app.commitments import Adjuster, Adjustment
from app.datasource import Snapshot
from app.models import Criterion, NameMode, ScorePart, WindowMode, Week
from app.scoring import display_name, normalise, score_student

# Criteria that order students who are still level after the raw score, in priority order.
TIE_BREAKER_KEYS = ("attendance", "homework")
DEFAULT_ROLLING_WEEKS = 4


@dataclass(slots=True)
class WeekResult:
    week: Week
    raw: float
    parts: list[ScorePart]
    missing_keys: list[str]
    adjustment: Adjustment


@dataclass(slots=True)
class Ranked:
    student_id: str
    full_name: str
    display_name: str
    score: float  # the adjusted score, which the table ranks on
    raw: float
    parts: list[ScorePart]
    missing_keys: list[str]
    weeks: list[WeekResult] = field(default_factory=list)
    rank: int = 0
    tied: bool = False

    @property
    def capped(self) -> bool:
        return any(w.adjustment.capped for w in self.weeks)


def round1(value: float) -> float:
    """Round to one decimal, halves up. Ties are decided on the rounded score."""
    return math.floor(value * 10 + 0.5) / 10


def window_week_ids(
    weeks: list[Week], week_id: str, window: WindowMode, rolling_weeks: int = DEFAULT_ROLLING_WEEKS
) -> list[str]:
    """`weeks` is oldest first. Cumulative runs from week 1 through `week_id`, rolling covers
    the last `rolling_weeks` weeks ending there."""
    ids = [w.id for w in weeks]
    if week_id not in ids:
        return []
    end = ids.index(week_id) + 1
    if window == "cumulative":
        return ids[:end]
    if window == "rolling":
        return ids[max(0, end - rolling_weeks) : end]
    return [week_id]


def combine_parts(results: list[WeekResult]) -> list[ScorePart]:
    """One row of criteria for a window: earned and possible are summed for reference, and
    each criterion's points are the mean of its weekly points, so they add up to the mean raw score."""
    if len(results) == 1:
        return results[0].parts
    combined = []
    for weekly in zip(*(r.parts for r in results)):
        present = [p for p in weekly if not p.missing]
        earned = sum(p.earned for p in present) if present else None
        possible = sum(p.possible for p in present) if present else None
        combined.append(
            weekly[0].model_copy(
                update={
                    "earned": earned,
                    "possible": possible,
                    "normalised": normalise(earned, possible),
                    "effective_weight": fmean(p.effective_weight for p in weekly),
                    "points": fmean(p.points for p in weekly),
                    "missing": not present,
                }
            )
        )
    return combined


def rank_table(
    snapshot: Snapshot,
    *,
    week_id: str,
    window: WindowMode,
    criteria: list[Criterion],
    weights: dict[str, float],
    name_mode: NameMode,
    adjuster: Adjuster,
    rolling_weeks: int = DEFAULT_ROLLING_WEEKS,
) -> list[Ranked]:
    """Score every student with entries in the window and rank them, best first."""
    weeks_by_id = {w.id: w for w in snapshot.weeks}
    window_ids = window_week_ids(snapshot.weeks, week_id, window, rolling_weeks)
    criterion_ids = {c.id for c in criteria}

    entries = defaultdict(lambda: defaultdict(list))  # student -> week -> entries
    for entry in snapshot.entries:
        if entry.week_id in window_ids and entry.criterion_id in criterion_ids:
            entries[entry.student_id][entry.week_id].append(entry)

    rows = []
    for student in snapshot.students:
        by_week = entries.get(student.id)
        if not by_week:
            continue
        results = []
        for wid in window_ids:  # oldest first
            if wid not in by_week:
                continue  # a week with no entries is left out of the average, not scored as zero
            scored = score_student(by_week[wid], criteria, weights)
            week = weeks_by_id[wid]
            results.append(
                WeekResult(week, scored.score, scored.parts, scored.missing_keys,
                           adjuster.apply(student.id, week, scored.score))
            )
        parts = combine_parts(results)
        rows.append(
            Ranked(
                student_id=student.id,
                full_name=student.display_name,
                display_name=display_name(student, name_mode),
                score=fmean(r.adjustment.adjusted for r in results),
                raw=fmean(r.raw for r in results),
                parts=parts,
                missing_keys=[p.key for p in parts if p.missing and p.weight > 0],
                weeks=results,
            )
        )
    return assign_ranks(rows)


def assign_ranks(rows: list[Ranked]) -> list[Ranked]:
    """Order by adjusted score, then raw score, then the tie-breaker criteria. Competition
    ranking (1, 1, 3): students still level after all of that share a rank."""

    def level(row: Ranked):
        normalised = {p.key: p.normalised for p in row.parts}
        tie_values = tuple(
            -(normalised[key] if normalised.get(key) is not None else -1) for key in TIE_BREAKER_KEYS
        )
        return (-round1(row.score), -round1(row.raw), *tie_values)

    # Full name, not the shown name, so switching name mode never reshuffles rows.
    ordered = sorted(rows, key=lambda row: (*level(row), row.full_name.casefold(), row.student_id))

    last_level = None
    last_rank = 0
    for index, row in enumerate(ordered):
        current = level(row)
        if last_level is not None and current == last_level:
            row.rank, row.tied = last_rank, True
        else:
            row.rank, row.tied = index + 1, False
            last_rank, last_level = row.rank, current
    # The first member of a tie group is tied too.
    for above, below in zip(ordered, ordered[1:]):
        if above.rank == below.rank:
            above.tied = True
    return ordered


def _nearest_above(rows: list[Ranked], index: int) -> int | None:
    """Index of the closest row with a better rank, skipping a tie partner."""
    for i in range(index - 1, -1, -1):
        if rows[i].rank < rows[index].rank:
            return i
    return None


def gap_to_next(rows: list[Ranked], index: int) -> float | None:
    """Points needed to reach the next rank up; None at the top."""
    above = _nearest_above(rows, index)
    return None if above is None else max(0.0, rows[above].score - rows[index].score)


def gap_to_below(rows: list[Ranked], index: int) -> float | None:
    """Lead over the next rank down; None at the bottom."""
    for i in range(index + 1, len(rows)):
        if rows[i].rank > rows[index].rank:
            return max(0.0, rows[index].score - rows[i].score)
    return None


def above_name(rows: list[Ranked], index: int) -> str | None:
    above = _nearest_above(rows, index)
    return None if above is None else rows[above].display_name


def previous_ranks(
    snapshot: Snapshot,
    *,
    week_id: str,
    window: WindowMode,
    criteria: list[Criterion],
    weights: dict[str, float],
    adjuster: Adjuster,
    rolling_weeks: int = DEFAULT_ROLLING_WEEKS,
) -> dict[str, int]:
    """Adjusted ranks in the previous week's table, same criteria, weights and window mode."""
    week_ids = [w.id for w in snapshot.weeks]
    index = week_ids.index(week_id)
    if index == 0:
        return {}
    table = rank_table(
        snapshot,
        week_id=week_ids[index - 1],
        window=window,
        criteria=criteria,
        weights=weights,
        name_mode="full",
        adjuster=adjuster,
        rolling_weeks=rolling_weeks,
    )
    return {row.student_id: row.rank for row in table}
