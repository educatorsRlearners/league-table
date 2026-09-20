"""Turns a snapshot into a ranked table: windows, ties, gaps and movement."""

import math
from collections import defaultdict
from dataclasses import dataclass

from app.datasource import Snapshot
from app.models import Criterion, NameMode, ScorePart, WindowMode, Week
from app.scoring import display_name, score_student

# Criteria that order tied students, in priority order. They decide display order only.
TIE_BREAKER_KEYS = ("attendance", "homework")


@dataclass(slots=True)
class Ranked:
    student_id: str
    full_name: str
    display_name: str
    score: float
    parts: list[ScorePart]
    missing_keys: list[str]
    rank: int = 0
    tied: bool = False


def round1(value: float) -> float:
    """Round to one decimal, halves up. Ties are decided on the rounded score."""
    return math.floor(value * 10 + 0.5) / 10


def window_week_ids(weeks: list[Week], week_id: str, window: WindowMode) -> list[str]:
    """`weeks` is oldest first. Cumulative runs from week 1 through `week_id`."""
    ids = [w.id for w in weeks]
    if week_id not in ids:
        return []
    return ids[: ids.index(week_id) + 1] if window == "cumulative" else [week_id]


def rank_table(
    snapshot: Snapshot,
    *,
    week_id: str,
    window: WindowMode,
    criteria: list[Criterion],
    weights: dict[str, float],
    name_mode: NameMode,
) -> list[Ranked]:
    """Score every student with entries in the window and rank them, best first."""
    week_ids = set(window_week_ids(snapshot.weeks, week_id, window))
    criterion_ids = {c.id for c in criteria}

    entries_by_student = defaultdict(list)
    for entry in snapshot.entries:
        if entry.week_id in week_ids and entry.criterion_id in criterion_ids:
            entries_by_student[entry.student_id].append(entry)

    rows = []
    for student in snapshot.students:
        entries = entries_by_student.get(student.id)
        if not entries:
            continue
        scored = score_student(entries, criteria, weights)
        rows.append(
            Ranked(
                student_id=student.id,
                full_name=student.display_name,
                display_name=display_name(student, name_mode),
                score=scored.score,
                parts=scored.parts,
                missing_keys=scored.missing_keys,
            )
        )
    return assign_ranks(rows)


def assign_ranks(rows: list[Ranked]) -> list[Ranked]:
    """Competition ranking (1, 1, 3). Tie-breakers only decide display order."""

    def sort_key(row: Ranked):
        normalised = {p.key: p.normalised for p in row.parts}
        tie_values = [
            -(normalised[key] if normalised.get(key) is not None else -1) for key in TIE_BREAKER_KEYS
        ]
        # Full name, not the shown name, so switching name mode never reshuffles rows.
        return (-round1(row.score), *tie_values, row.full_name.casefold(), row.student_id)

    ordered = sorted(rows, key=sort_key)

    last_score = None
    last_rank = 0
    for index, row in enumerate(ordered):
        rounded = round1(row.score)
        if last_score is not None and rounded == last_score:
            row.rank, row.tied = last_rank, True
        else:
            row.rank, row.tied = index + 1, False
            last_rank, last_score = row.rank, rounded
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
) -> dict[str, int]:
    """Ranks in the previous week's table, same criteria, weights and window mode."""
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
    )
    return {row.student_id: row.rank for row in table}
