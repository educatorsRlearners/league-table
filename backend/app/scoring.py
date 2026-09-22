"""Pure scoring logic ported from frontend/services/scoring.js. No I/O.

Operates on plain dicts (as stored) so both the service layer and tests use it.
Field names follow the frontend normalised model: entries carry
``criterion_key``, baselines carry ``work_hours``/``childcare_hours``/
``eldercare_hours`` + ``status``/``effective_from_week``, weekly updates carry
``week_number`` + hour fields + ``reversed_at``.
"""

from __future__ import annotations

import math

ZERO_HOURS: dict[str, float] = {"work": 0, "childcare": 0, "eldercare": 0}


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def normalise(earned, possible):
    if possible is None or possible <= 0:
        return None
    if earned is None:
        return None
    return (100 * earned) / possible


def aggregate(entries) -> dict:
    out: dict[str, dict] = {}
    for e in entries:
        earned = _get(e, "earned")
        possible = _get(e, "possible")
        if earned is None or possible is None:
            continue
        key = _get(e, "criterion_key", _get(e, "criterion_id")) or ""
        slot = out.get(key)
        if slot is None:
            slot = out[key] = {"earned": 0, "possible": 0}
        slot["earned"] += earned
        slot["possible"] += possible
    return out


def score_student(*, entries, criteria, weights) -> dict:
    """Weighted raw score; missing criteria excluded + rescaled (never zero)."""
    agg = aggregate(entries)

    def present(c) -> bool:
        key = _get(c, "key")
        a = agg.get(key)
        return bool(a and a["possible"] > 0 and (weights.get(key, 0) or 0) > 0)

    present_keys = {_get(c, "key") for c in criteria if present(c)}
    weight_sum = sum(weights.get(k, 0) or 0 for k in present_keys)

    parts = []
    for c in criteria:
        key = _get(c, "key")
        label = _get(c, "label", key)
        a = agg.get(key)
        weight = weights.get(key, 0) or 0
        missing = not (a and a["possible"] > 0)
        if missing:
            normalised = None
            earned = None
            possible = None
        else:
            assert a is not None
            normalised = normalise(a["earned"], a["possible"])
            earned = a["earned"]
            possible = a["possible"]
        effective = 0 if missing or weight_sum == 0 else (weight / weight_sum) * 100
        parts.append(
            {
                "key": key,
                "label": label,
                "earned": earned,
                "possible": possible,
                "normalised": normalised,
                "weight": weight,
                "effectiveWeight": effective,
                "points": 0 if missing or normalised is None else (normalised * effective) / 100,
                "missing": missing,
            }
        )
    score = sum(p["points"] for p in parts)
    return {
        "score": None if weight_sum == 0 else score,
        "parts": parts,
        "missingKeys": [p["key"] for p in parts if p["missing"] and p["weight"] > 0],
    }


def resolve_hours(*, baseline, weekly_updates=None, week_number: int) -> dict:
    """Which hours apply in a given week. Mirrors scoring.js resolveHours."""
    updates = weekly_updates or []
    approved = baseline is not None and _get(baseline, "status") == "approved"
    if not approved:
        source = _get(baseline, "status", None) if baseline else "none"
        return {"hours": dict(ZERO_HOURS), "source": source or "none"}
    update = next(
        (
            u
            for u in updates
            if _get(u, "week_number") == week_number and not _get(u, "reversed_at")
        ),
        None,
    )
    if update is not None:
        return {
            "hours": {
                "work": _get(update, "work_hours", 0) or 0,
                "childcare": _get(update, "childcare_hours", 0) or 0,
                "eldercare": _get(update, "eldercare_hours", 0) or 0,
            },
            "source": "weekly",
        }
    effective_from = _get(baseline, "effective_from_week", 1) or 1
    if week_number >= effective_from:
        return {
            "hours": {
                "work": _get(baseline, "work_hours", 0) or 0,
                "childcare": _get(baseline, "childcare_hours", 0) or 0,
                "eldercare": _get(baseline, "eldercare_hours", 0) or 0,
            },
            "source": "baseline",
        }
    return {"hours": dict(ZERO_HOURS), "source": "before-effective"}


def weighted_hours(hours: dict | None = None, type_weights: dict | None = None) -> float:
    hours = hours or {}
    type_weights = type_weights or {}
    return sum((type_weights.get(k, 0) or 0) * (hours.get(k, 0) or 0) for k in type_weights)


def commitment_factor(h: float, rate: float, cap: float) -> float:
    return min(1 + rate * h, cap)


def adjust(raw, factor: float) -> dict:
    if raw is None:
        return {"adjusted": None, "capped": False}
    value = raw * factor
    return {"adjusted": min(100, value), "capped": value > 100 + 1e-9}


def mean(values) -> float | None:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _round1(n):
    return None if n is None else round(n * 10) / 10


def rank_rows(rows: list[dict], tie_breakers: list[str] | None = None) -> list[dict]:
    """Competition ranks (1,1,3) on rounded adjusted score; raw + tie-breakers order."""
    tie_breakers = tie_breakers or []
    keyed = [
        {**r, "scoreRounded": -1 if r.get("score") is None else _round1(r["score"]),
         "rawRounded": -1 if r.get("raw") is None else _round1(r["raw"])}
        for r in rows
    ]

    def sort_key(r):
        tie_vals = tuple(-(r.get("normalisedByKey", {}).get(k, -1)) for k in tie_breakers)
        return (-r["scoreRounded"], -r["rawRounded"], *tie_vals, (r.get("display_name") or "").lower())

    # Python sort can't mix easily; do it stepwise with sorted()
    keyed.sort(
        key=lambda r: (
            -r["scoreRounded"],
            -r["rawRounded"],
            *[-r.get("normalisedByKey", {}).get(k, -1) for k in tie_breakers],
            (r.get("display_name") or "").lower(),
        )
    )
    last_score = None
    last_rank = 0
    for i, row in enumerate(keyed):
        if last_score is not None and row["scoreRounded"] == last_score:
            row["rank"] = last_rank
            row["tied"] = True
        else:
            row["rank"] = i + 1
            last_rank = row["rank"]
            last_score = row["scoreRounded"]
            row["tied"] = False
    for i in range(len(keyed) - 1):
        if keyed[i + 1]["rank"] == keyed[i]["rank"]:
            keyed[i]["tied"] = True
    return keyed


def _rounded(row: dict) -> float | None:
    if "scoreRounded" in row and row["scoreRounded"] is not None and row["scoreRounded"] >= 0:
        return float(row["scoreRounded"])
    return _round1(row.get("score"))


def _gap(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    diff = _round1(a - b)
    assert diff is not None
    return max(0.0, diff)


def gap_to_next(rows: list[dict], index: int):
    for i in range(index - 1, -1, -1):
        if rows[i]["rank"] < rows[index]["rank"]:
            return _gap(_rounded(rows[i]), _rounded(rows[index]))
    return None


def gap_to_below(rows: list[dict], index: int):
    for i in range(index + 1, len(rows)):
        if rows[i]["rank"] > rows[index]["rank"]:
            return _gap(_rounded(rows[index]), _rounded(rows[i]))
    return None


def normalise_weights(weights: dict) -> dict:
    keys = list(weights.keys())
    total = sum(weights.get(k, 0) or 0 for k in keys)
    if total == 0:
        return {k: 0 for k in keys}
    return {k: ((weights.get(k, 0) or 0) * 100) / total for k in keys}


def display_name(student, mode: str | None = "full") -> str:
    full = _get(student, "display_name", "")
    if mode == "nickname":
        return _get(student, "nickname") or full
    if mode == "initials":
        bits = (full or "").split(" ")
        if len(bits) > 1:
            return f"{bits[0]} {bits[-1][0]}."
        return bits[0] if bits else ""
    return full


def round1(value: float | None):
    if value is None:
        return None
    return math.floor(value * 10 + 0.5) / 10
