"""Ranking + explanation. Tag: ranking."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.auth import Caller, get_caller
from app.deps import (
    ensure_student_in_class,
    get_ctx,
    need_class,
    parse_criteria,
    parse_weights,
)
from app.models import Explanation
from app.service import DEFAULT_ROLLING_N, build_rows, resolved_weights, window_weeks

router = APIRouter(tags=["ranking"])


def _resolve(snap, criteria_keys, weights):
    keys = criteria_keys if criteria_keys else [c.key for c in snap.criteria]
    known = {c.key for c in snap.criteria}
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown criterion: {', '.join(unknown)}")
    if weights is not None:
        unknown_w = [k for k in weights if k not in known]
        if unknown_w:
            raise HTTPException(status_code=422, detail=f"Unknown criterion: {', '.join(unknown_w)}")
    return keys, resolved_weights(snap, keys, weights)


def _scope(row: dict, caller: Caller) -> dict:
    public = {
        "student_id": row["student_id"],
        "display_name": row["display_name"],
        "score": row["score"],
        "rank": row["rank"],
        "tied": row["tied"],
        "rank_delta": row.get("rank_delta"),
        "gap_to_next": row.get("gap_to_next"),
        "gap_to_below": row.get("gap_to_below"),
        "missing": row.get("missing", row.get("missingKeys", [])),
        "is_self": caller.role == "student" and caller.studentId == row["student_id"],
    }
    if caller.role == "instructor" or row["student_id"] == caller.studentId:
        public.update({"raw": row["raw"], "factor": row["factor"],
                       "weighted_hours": row["weighted_hours"], "capped": row["capped"],
                       "hours_source": row.get("hours_source")})
    return public


@router.get("/classes/{classId}/ranking", tags=["ranking"],
            responses={401: {}, 403: {}})
def get_ranking(
    classId: str,
    week: Annotated[str, Query(description="Week id (e.g. `w5`).")],
    criteria: Annotated[list[str] | None, Query(description="Criterion keys. Repeat or comma-separated.")] = None,
    window: Annotated[str, Query(description="week, rolling or cumulative.")] = "week",
    rollingN: Annotated[int, Query(description="Rolling window size.", ge=1, le=16)] = DEFAULT_ROLLING_N,
    weights: Annotated[str | None, Query(description="Weight override map (serialised JSON object).")] = None,
    nameMode: Annotated[str, Query(description="full, initials or nickname.")] = "full",
    caller: Caller = Depends(get_caller), ctx=Depends(get_ctx),
):
    snap = need_class(ctx, classId)
    ensure_student_in_class(ctx, caller, classId)
    if window not in ("week", "rolling", "cumulative"):
        raise HTTPException(status_code=422, detail="window must be week, rolling or cumulative.")
    if nameMode not in ("full", "initials", "nickname"):
        raise HTTPException(status_code=422, detail="nameMode must be full, initials or nickname.")
    criteria_keys = parse_criteria(criteria)
    weights_map = parse_weights(weights)
    keys, w = _resolve(snap, criteria_keys, weights_map)
    if week not in {ww.id for ww in snap.weeks}:
        return JSONResponse({"classId": classId, "weekId": week, "windowMode": window, "rollingN": rollingN,
                "criteriaKeys": keys, "weights": w, "rows": [], "weekCount": 0,
                "lastUpdated": int(snap.at * 1000), "stale": snap.stale,
                "issues": [i.model_dump() for i in snap.issues]})
    rows = build_rows(snap, week_id=week, window_mode=window, rolling_n=rollingN,
                      weights=w, criteria_keys=keys, name_mode=nameMode)
    idx = next(i for i, ww in enumerate(snap.weeks) if ww.id == week)
    prev_map = {}
    if idx > 0:
        prev = build_rows(snap, week_id=snap.weeks[idx - 1].id, window_mode=window,
                          rolling_n=rollingN, weights=w, criteria_keys=keys, name_mode=nameMode)
        prev_map = {r["student_id"]: r["rank"] for r in prev}
    decorated = []
    for r in rows:
        scoped = _scope({**r, "rank_delta": (prev_map[r["student_id"]] - r["rank"]
                                             if r["student_id"] in prev_map else None),
                         "missing": r.get("missingKeys", [])}, caller)
        decorated.append(scoped)
    return JSONResponse({"classId": classId, "weekId": week, "windowMode": window, "rollingN": rollingN,
            "criteriaKeys": keys, "weights": w, "rows": decorated,
            "weekCount": len(window_weeks(snap.weeks, week, window, rollingN)),
            "lastUpdated": int(snap.at * 1000), "stale": snap.stale,
            "issues": [i.model_dump() for i in snap.issues]})


@router.get("/classes/{classId}/students/{studentId}/explanation", response_model=Explanation,
            tags=["students"], responses={401: {}, 403: {}, 404: {}})
def get_explanation(
    classId: str,
    studentId: str,
    week: Annotated[str, Query(description="Week id.")],
    criteria: Annotated[list[str] | None, Query(description="Criterion keys.")] = None,
    window: Annotated[str, Query(description="week, rolling or cumulative.")] = "week",
    rollingN: Annotated[int, Query(description="Rolling window size.", ge=1, le=16)] = DEFAULT_ROLLING_N,
    weights: Annotated[str | None, Query(description="Weight override map (serialised JSON object).")] = None,
    nameMode: Annotated[str, Query(description="full, initials or nickname.")] = "full",
    caller: Caller = Depends(get_caller), ctx=Depends(get_ctx),
):
    if caller.role == "student" and caller.studentId != studentId:
        raise HTTPException(status_code=403, detail="A student may only open their own breakdown.")
    snap = need_class(ctx, classId)
    if window not in ("week", "rolling", "cumulative"):
        raise HTTPException(status_code=422, detail="window must be week, rolling or cumulative.")
    if nameMode not in ("full", "initials", "nickname"):
        raise HTTPException(status_code=422, detail="nameMode must be full, initials or nickname.")
    criteria_keys = parse_criteria(criteria)
    weights_map = parse_weights(weights)
    keys, w = _resolve(snap, criteria_keys, weights_map)
    rows = build_rows(snap, week_id=week, window_mode=window, rolling_n=rollingN,
                      weights=w, criteria_keys=keys, name_mode=nameMode)
    i = next((n for n, r in enumerate(rows) if r["student_id"] == studentId), None)
    if i is None:
        raise HTTPException(status_code=404, detail="No entries for that student in this window.")
    row = rows[i]
    focus = row["weeks"][-1]
    focus_parts = [{
        "key": p["key"], "label": p["label"], "earned": p["earned"], "possible": p["possible"],
        "normalised": p["normalised"], "weight": p["weight"],
        "effectiveWeight": p["effectiveWeight"], "points": p["points"], "missing": p["missing"],
    } for p in focus["parts"]]
    return {
        "student_id": studentId,
        "display_name": row["display_name"],
        "rank": row["rank"],
        "tied": row["tied"],
        "score": row["score"],
        "raw": row["raw"],
        "focusRaw": focus["raw"],
        "focusAdjusted": focus["adjusted"],
        "focusCapped": focus["capped"],
        "factor": row["factor"],
        "weighted_hours": row["weighted_hours"],
        "capped": row["capped"],
        "hours": focus["hours"],
        "hours_source": focus["hours_source"],
        "typeWeights": snap.settings.get("typeWeights", {}),
        "rate": snap.settings.get("rate", 0.01),
        "cap": snap.settings.get("cap", 1.25),
        "focusWeek": focus["week_number"],
        "parts": focus_parts,
        "weeks": [{"week_number": r["week_number"], "raw": r["raw"],
                   "weighted_hours": r["weighted_hours"], "factor": r["factor"],
                   "adjusted": r["adjusted"], "capped": r["capped"]} for r in row["weeks"]],
        "gap_to_next": row.get("gap_to_next"),
        "gap_to_below": row.get("gap_to_below"),
        "above": next((r["display_name"] for r in reversed(rows[:i]) if r["rank"] < row["rank"]), None),
        "weekId": week,
        "windowMode": window,
    }
