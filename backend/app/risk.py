"""Risk engine ported from frontend/services/risk.js. Pure functions, no I/O."""

from __future__ import annotations

SIGNAL_KEYS = [
    "downward_trend",
    "missed_engagement",
    "low_projected_grade",
    "heavy_commitments",
    "missing_data",
]

SIGNAL_LABELS = {
    "downward_trend": "Downward trend",
    "missed_engagement": "Missed or low engagement",
    "low_projected_grade": "Low projected grade",
    "heavy_commitments": "Heavy outside commitments",
    "missing_data": "Missing data",
}

DEFAULT_THRESHOLDS = {
    "declineWeeks": 3,
    "missedAssignments": 2,
    "attendancePct": 70,
    "participationPct": 50,
    "projectedGrade": 60,
    "commitmentHours": 20,
    "missingWeeks": 2,
}

DEFAULT_ACTIVE = {k: True for k in SIGNAL_KEYS}
LEVELS = ["Not flagged", "Watch", "At risk", "High risk"]


def level_for(count: int) -> str:
    if count >= 3:
        return "High risk"
    return LEVELS[count] if 0 <= count < len(LEVELS) else "Not flagged"


def _round1(n):
    return None if n is None else round(n * 10) / 10


def _pct(earned, possible):
    return (100 * earned) / possible if possible and possible > 0 else None


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _decline_run(weekly) -> int:
    scored = [w for w in weekly if _get(w, "raw") is not None]
    run = 0
    for i in range(len(scored) - 1, 0, -1):
        curr = _get(scored[i], "raw")
        prev = _get(scored[i - 1], "raw")
        if curr is None or prev is None:
            break
        if curr < prev - 1e-9:
            run += 1
        else:
            break
    return run


def _missing_run(weekly) -> int:
    best = 0
    run = 0
    for w in weekly:
        if _get(w, "hasEntries"):
            run = 0
        else:
            run += 1
            best = max(best, run)
    return best


def _missed_assignments(weekly) -> int:
    count = 0
    for w in weekly:
        by_key = _get(w, "byKey", {}) or {}
        slot = by_key.get("homework")
        if slot and (slot.get("possible", 0) or 0) > 0 and (slot.get("earned", 0) or 0) == 0:
            count += 1
    return count


def _weeks_set(weekly) -> int:
    count = 0
    for w in weekly:
        by_key = _get(w, "byKey", {}) or {}
        slot = by_key.get("homework")
        if slot and (slot.get("possible", 0) or 0) > 0:
            count += 1
    return count


def _totals_for(weekly, key: str) -> dict:
    earned = 0
    possible = 0
    for w in weekly:
        by_key = _get(w, "byKey", {}) or {}
        slot = by_key.get(key)
        if not slot:
            continue
        earned += slot.get("earned", 0) or 0
        possible += slot.get("possible", 0) or 0
    return {"earned": earned, "possible": possible}


def evaluate_signals(*, weekly, hours: float = 0, thresholds: dict | None = None, active: dict | None = None) -> dict:
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    weekly = list(weekly or [])
    scored = [w for w in weekly if _get(w, "raw") is not None]

    run = _decline_run(weekly)
    missed = _missed_assignments(weekly)
    set_count = _weeks_set(weekly)
    attendance = _totals_for(weekly, "attendance")
    attendance_pct = _pct(attendance["earned"], attendance["possible"])
    participation = _totals_for(weekly, "participation")
    participation_pct = _pct(participation["earned"], participation["possible"])
    projected = None
    if scored:
        vals = [_get(w, "raw") for w in scored]
        nums = [v for v in vals if v is not None]
        projected = (sum(nums) / len(nums)) if nums else None
    gap = _missing_run(weekly)

    maybe_reasons = [
        f"attendance {_round1(attendance_pct)}% is under {t['attendancePct']}%" if attendance_pct is not None and attendance_pct < t["attendancePct"] else None,
        f"{missed} assignments not handed in" if missed >= t["missedAssignments"] else None,
        f"participation {_round1(participation_pct)}% is under {t['participationPct']}%" if participation_pct is not None and participation_pct < t["participationPct"] else None,
    ]
    reasons: list[str] = [r for r in maybe_reasons if r]

    plural = lambda n: "" if n == 1 else "s"  # noqa: E731
    defs = {
        "downward_trend": {
            "on": run >= t["declineWeeks"],
            "summary": f"The weighted score has fallen {run} weeks running."
            if run >= t["declineWeeks"]
            else f"The score has fallen {run} week{plural(run)} running; the threshold is {t['declineWeeks']}.",
            "evidence": [
                {"label": f"Week {_get(w, 'week_number')}", "value": str(_round1(_get(w, 'raw')))}
                for w in scored[-6:]
            ],
        },
        "missed_engagement": {
            "on": len(reasons) > 0,
            "summary": f"Triggered by {'; '.join(reasons)}."
            if reasons
            else "Attendance, homework and participation are all above their thresholds.",
            "evidence": [
                {"label": "Assignments not handed in", "value": f"{missed} of {set_count}"},
                {"label": "Attendance to date", "value": "—" if attendance_pct is None else f"{_round1(attendance_pct)}%"},
                {"label": "Participation to date", "value": "—" if participation_pct is None else f"{_round1(participation_pct)}%"},
            ],
        },
        "low_projected_grade": {
            "on": projected is not None and projected < t["projectedGrade"],
            "summary": "No scores yet, so no projection."
            if projected is None
            else f"The score to date averages {_round1(projected)}, against a pass threshold of {t['projectedGrade']}.",
            "evidence": [
                {"label": "Weeks counted", "value": str(len(scored))},
                {"label": "Projected grade", "value": "—" if projected is None else str(_round1(projected))},
                {"label": "Pass threshold", "value": str(t["projectedGrade"])},
            ],
        },
        "heavy_commitments": {
            "on": (hours or 0) >= t["commitmentHours"],
            "summary": f"{_round1(hours)} weighted hours of work and care a week, at or above the {t['commitmentHours']}-hour threshold."
            if (hours or 0) >= t["commitmentHours"]
            else f"{_round1(hours)} weighted hours a week, under the {t['commitmentHours']}-hour threshold.",
            "evidence": [
                {"label": "Weighted hours this week", "value": str(_round1(hours))},
                {"label": "Threshold", "value": f"{t['commitmentHours']} hours"},
            ],
        },
        "missing_data": {
            "on": gap >= t["missingWeeks"],
            "summary": f"{gap} consecutive weeks with no entries at all."
            if gap >= t["missingWeeks"]
            else f"The longest gap is {gap} week{plural(gap)}; the threshold is {t['missingWeeks']}.",
            "evidence": [
                {"label": f"Week {_get(w, 'week_number')}", "value": "recorded" if _get(w, "hasEntries") else "no entries"}
                for w in weekly[-6:]
            ],
        },
    }

    active = active or {}
    signals = [
        {
            "key": key,
            "label": SIGNAL_LABELS[key],
            "active": active.get(key, True) is not False,
            "on": (active.get(key, True) is not False) and bool(defs[key]["on"]),
            "summary": defs[key]["summary"],
            "evidence": defs[key]["evidence"],
        }
        for key in SIGNAL_KEYS
    ]
    on = [s for s in signals if s["on"]]
    return {
        "signals": signals,
        "signals_on": [s["key"] for s in on],
        "level": level_for(len(on)),
        "oneAway": None if len(on) >= 3 else level_for(len(on) + 1),
        "metrics": {
            "declineRun": run,
            "missedAssignments": missed,
            "attendancePct": _round1(attendance_pct),
            "participationPct": _round1(participation_pct),
            "projected": _round1(projected),
            "hours": _round1(hours),
            "missingRun": gap,
        },
    }


def diff_state(prior: dict | None, current: dict) -> str:
    was = bool(prior and len(prior.get("signals_on", [])) > 0)
    is_now = len(current.get("signals_on", [])) > 0
    if is_now and not was:
        return "new"
    if is_now and was:
        return "still"
    if not is_now and was:
        return "cleared"
    return "quiet"
