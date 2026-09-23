"""GET /classes, bootstrap, explainer, settings. Tags: classes, settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import Caller, get_caller, instructor_id_of, require_instructor
from app.deps import get_ctx, need_class, student_class_ids
from app.models import (
    Bootstrap,
    Class,
    Explainer,
    LeagueSettings,
    LeagueSettingsPatch,
    LoginOptions,
)
from app.scoring import commitment_factor, normalise_weights, weighted_hours
from app.service import DEFAULT_ROLLING_N, latest_complete_week_id

router = APIRouter(tags=["classes"])


@router.get("/login/options", response_model=LoginOptions, tags=["login"])
def get_login_options(ctx=Depends(get_ctx)):
    """Public: no Bearer token. Just class/student names for the login
    picker — no scores, hours or other personal data."""
    classes = []
    for c in ctx.db.list_classes():
        students = [s for s in ctx.db.list_students(c.id) if s.active]
        classes.append({
            "id": c.id, "name": c.name, "instructor_id": c.instructor_id,
            "students": [{"id": s.id, "display_name": s.display_name} for s in students],
        })
    return {"classes": classes}


@router.get("/classes", response_model=list[Class], tags=["classes"],
            responses={401: {"description": "Missing/invalid Bearer token"},
                       403: {"description": "Forbidden"}})
def list_classes(instructor_id: str | None = Query(default=None, alias="instructor_id"),
                 caller: Caller = Depends(get_caller), ctx=Depends(get_ctx)):
    iid = instructor_id or instructor_id_of(caller)
    if caller.role == "instructor" and iid != instructor_id_of(caller):
        raise HTTPException(status_code=403, detail="Passing another instructor's id is forbidden.")
    if caller.role == "student":
        raise HTTPException(status_code=403, detail="Instructor only.")
    return [c.model_dump(exclude_none=True) for c in ctx.db.list_classes(iid)]


@router.get("/classes/{classId}/bootstrap", response_model=Bootstrap, tags=["classes"],
            responses={401: {}, 403: {}, 404: {}})
def get_bootstrap(classId: str, caller: Caller = Depends(get_caller), ctx=Depends(get_ctx)):
    snap = need_class(ctx, classId)
    if caller.role == "student" and classId not in student_class_ids(ctx, caller.studentId or "") \
            and caller.classId != classId:
        raise HTTPException(status_code=403, detail="That class is not yours to read.")
    klass = next((c for c in ctx.db.list_classes() if c.id == classId), None)
    classes = ctx.db.list_classes(klass.instructor_id if klass else None)
    settings = snap.settings
    defaults = {c.key: c.default_weight for c in snap.criteria}
    weights = settings.get("weights") or defaults
    labels = {c.key: c.label for c in snap.criteria}
    tie_labels = [(labels.get(k, k)) for k in (settings.get("tieBreakers") or [])]
    try:
        accounts = ctx.db.list_accounts()
    except AttributeError:
        accounts = []
    weeks_with_data = sorted({e.week_id for e in snap.entries})
    return {
        "klass": klass.model_dump(exclude_none=True) if klass else {"id": classId},
        "classes": [c.model_dump(exclude_none=True) for c in classes],
        "weeks": [w.model_dump() for w in snap.weeks],
        "criteria": [c.model_dump() for c in snap.criteria],
        "weights": weights,
        "defaultWeights": defaults,
        "settings": {"typeWeights": settings.get("typeWeights", {}),
                     "rate": settings.get("rate", 0.01), "cap": settings.get("cap", 1.25)},
        "tieBreakers": tie_labels,
        "accounts": accounts,
        "weeksWithData": weeks_with_data,
        "latestCompleteWeekId": latest_complete_week_id(snap),
        "source": ctx.source_info(),
        "lastUpdated": int(snap.at * 1000),
        "issues": [i.model_dump() for i in snap.issues],
        "rollingN": DEFAULT_ROLLING_N,
    }


@router.get("/classes/{classId}/explainer", response_model=Explainer, tags=["classes"],
            responses={401: {}})
def get_explainer(classId: str, caller: Caller = Depends(get_caller), ctx=Depends(get_ctx)):
    snap = need_class(ctx, classId)
    settings = snap.settings
    type_weights = settings.get("typeWeights", {"work": 1, "childcare": 1, "eldercare": 1})
    rate = settings.get("rate", 0.01)
    cap = settings.get("cap", 1.25)
    hours = {"work": 12, "childcare": 6, "eldercare": 0}
    h = weighted_hours(hours, type_weights)
    factor = commitment_factor(h, rate, cap)
    adjusted = min(100, 80 * factor)
    return {
        "typeWeights": type_weights,
        "rate": rate,
        "cap": cap,
        "table": [{"hours": hh, "factor": commitment_factor(hh, rate, cap)} for hh in [0, 10, 20, 25]],
        "example": {"raw": 80, "hours": hours, "weighted_hours": h, "factor": factor, "adjusted": adjusted},
    }


@router.put("/classes/{classId}/settings", response_model=LeagueSettings, tags=["settings"],
            responses={401: {}, 403: {}})
def save_settings(classId: str, patch: LeagueSettingsPatch,
                  caller: Caller = Depends(require_instructor), ctx=Depends(get_ctx)):
    need_class(ctx, classId)
    data = patch.model_dump(exclude_none=True)
    if data.get("weights") is not None:
        data["weights"] = normalise_weights(data["weights"])
    saved = ctx.store.save_league_settings(classId, data)
    # bust cache so bootstrap/ranking use new settings
    ctx.service._cache.pop(classId, None)
    return {
        "weights": saved.get("weights"),
        "typeWeights": saved.get("typeWeights", {"work": 1, "childcare": 1, "eldercare": 1}),
        "rate": saved.get("rate", 0.01),
        "cap": saved.get("cap", 1.25),
        "tieBreakers": saved.get("tieBreakers", []),
    }
