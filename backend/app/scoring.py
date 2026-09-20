"""Pure scoring logic. No I/O and no adapter detail: it works only on normalised types."""

import math
from dataclasses import dataclass
from typing import Iterable

from app.datasource import Entry, Student
from app.models import Criterion, NameMode, ScorePart


def normalise(earned: float | None, possible: float | None) -> float | None:
    if earned is None or possible is None or possible <= 0:
        return None
    return 100 * earned / possible


def aggregate(entries: Iterable[Entry]) -> dict[str, tuple[float, float]]:
    """Sum raw entries into {criterion_id: (earned, possible)} for a window.

    Entries without a usable number are skipped: the data check reports them, and
    they must not turn into a zero.
    """
    totals: dict[str, tuple[float, float]] = {}
    for entry in entries:
        if entry.earned is None or entry.possible is None:
            continue
        if not (math.isfinite(entry.earned) and math.isfinite(entry.possible)):
            continue
        earned, possible = totals.get(entry.criterion_id, (0.0, 0.0))
        totals[entry.criterion_id] = (earned + entry.earned, possible + entry.possible)
    return totals


@dataclass(slots=True)
class Scored:
    score: float
    parts: list[ScorePart]
    missing_keys: list[str]  # weighted criteria the student has no data for


def score_student(
    entries: Iterable[Entry], criteria: list[Criterion], weights: dict[str, float]
) -> Scored:
    """Weighted score for one student.

    A criterion with no data is excluded and the remaining weights are rescaled,
    so absence of data is never scored as zero.
    """
    totals = aggregate(entries)

    def has_data(criterion: Criterion) -> bool:
        total = totals.get(criterion.id)
        return total is not None and total[1] > 0

    weight_sum = sum(
        weights.get(c.key, 0.0) for c in criteria if has_data(c) and weights.get(c.key, 0.0) > 0
    )

    parts = []
    for criterion in criteria:
        weight = weights.get(criterion.key, 0.0)
        missing = not has_data(criterion)
        earned, possible = (None, None) if missing else totals[criterion.id]
        normalised = None if missing else normalise(earned, possible)
        effective = 0.0 if missing or weight_sum == 0 else weight / weight_sum * 100
        parts.append(
            ScorePart(
                key=criterion.key,
                label=criterion.label,
                earned=earned,
                possible=possible,
                normalised=normalised,
                weight=weight,
                effective_weight=effective,
                points=0.0 if normalised is None else normalised * effective / 100,
                missing=missing,
            )
        )

    return Scored(
        score=sum(p.points for p in parts) if weight_sum > 0 else 0.0,
        parts=parts,
        missing_keys=[p.key for p in parts if p.missing and p.weight > 0],
    )


def normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    """Rescale so the values total 100, preserving proportions."""
    total = sum(weights.values())
    if total == 0:
        return {key: 0.0 for key in weights}
    return {key: value * 100 / total for key, value in weights.items()}


def display_name(student: Student, mode: NameMode) -> str:
    if mode == "nickname":
        return student.nickname or student.display_name
    if mode == "initials":
        bits = student.display_name.split()
        return f"{bits[0]} {bits[-1][0]}." if len(bits) > 1 else bits[0]
    return student.display_name
