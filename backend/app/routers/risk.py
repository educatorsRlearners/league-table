"""Commitments, risk, standing, notes. Tags: commitments, risk, students."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.auth import Caller, get_caller, instructor_id_of, require_instructor
from app.deps import get_ctx, need_class
from app.faults import maybe_fail_commitment
from app.models import (
    Baseline,
    BaselineDecisionRequest,
    ChangeLogEntry,
    CommitmentHoursInput,
    Commitments,
    Digest,
    Note,
    NoteRequest,
    PendingBaseline,
    RiskRecord,
    RiskSettings,
    RiskSettingsPatch,
    Standing,
    StudentWeeklyUpdate,
    WeeklyUpdate,
)
from app.risk import LEVELS as LEVEL_ORDER
from app.risk import diff_state, evaluate_signals
from app.scoring import commitment_factor, resolve_hours, weighted_hours
from app.service import (
    DEFAULT_COMMITMENT_CAP,
    DEFAULT_COMMITMENT_RATE,
    calendar_week_number,
    editable_week_numbers,
    evaluation_week_number,
    hours_at,
    risk_weekly,
)

router = APIRouter()
HELP_TEXT = "Office hours are Tuesdays 2–4pm, and the advising team can be reached at advising@example.edu."  # noqa: RUF001


def _require_self_if_student(caller: Caller, student_id: str, detail: str) -> None:
    """Instructors may read any student; a student may read only themselves."""
    if caller.role == "student" and caller.studentId != student_id:
        raise HTTPException(status_code=403, detail=detail)


def _require_the_student(caller: Caller, student_id: str, detail: str) -> None:
    """Only the named student may act (instructors may not)."""
    if caller.role != "student" or caller.studentId != student_id:
        raise HTTPException(status_code=403, detail=detail)


def _display_name_for(students_by_id: dict, student_id: str) -> str:
    student = students_by_id.get(student_id)
    return student.display_name if student else student_id


def _commitments_payload(ctx, snap, student_id: str) -> dict:
    comm = ctx.store.get_commitments(snap.class_id, student_id)
    active_baseline, updates = comm["activeBaseline"], comm["weeklyUpdates"]
    settings = snap.settings
    type_weights = settings.get("typeWeights", {})
    rate = settings.get("rate", DEFAULT_COMMITMENT_RATE)
    cap = settings.get("cap", DEFAULT_COMMITMENT_CAP)
    by_week = []
    for w in snap.weeks:
        resolved = resolve_hours(baseline=active_baseline, weekly_updates=updates, week_number=w.week_number)
        h = weighted_hours(resolved["hours"], type_weights)
        by_week.append({"week_number": w.week_number, "hours": resolved["hours"],
                        "source": resolved["source"], "weighted_hours": h,
                        "factor": commitment_factor(h, rate, cap)})
    return {"studentId": student_id, "baseline": comm["baseline"], "activeBaseline": active_baseline,
            "weeklyUpdates": updates, "byWeek": by_week,
            "editableWeeks": editable_week_numbers(snap.weeks, ctx.clock())}


@router.get("/me/commitments", response_model=Commitments, tags=["commitments"],
            responses={401: {}, 403: {}})
def get_commitments(classId: str = Query(alias="classId"), studentId: str = Query(alias="studentId"),
                    caller: Caller = Depends(get_caller), ctx=Depends(get_ctx)):
    _require_self_if_student(caller, studentId, "A student may only read their own commitments.")
    snap = need_class(ctx, classId)
    return _commitments_payload(ctx, snap, studentId)


@router.put("/me/commitments/baseline", response_model=Commitments, tags=["commitments"],
            responses={400: {}, 401: {}, 403: {}, 404: {}})
def save_baseline(classId: str = Query(alias="classId"), studentId: str = Query(alias="studentId"),
                  body: CommitmentHoursInput = Body(...),
                  caller: Caller = Depends(get_caller), ctx=Depends(get_ctx)):
    _require_the_student(caller, studentId, "Only the student may submit their own baseline.")
    need_class(ctx, classId)
    ctx.store.save_baseline(class_id=classId, student_id=studentId, hours=body.model_dump(), actor_id=studentId,
                            submitted_at=ctx.now_iso())
    ctx.service.invalidate(classId)
    snap = need_class(ctx, classId)
    return _commitments_payload(ctx, snap, studentId)


@router.put("/me/commitments/weeks/{weekNumber}", response_model=Commitments, tags=["commitments"],
            responses={400: {}, 401: {}, 403: {}, 404: {}})
def save_weekly_update(weekNumber: int, classId: str = Query(alias="classId"), studentId: str = Query(alias="studentId"),
                       body: CommitmentHoursInput = Body(...),
                       caller: Caller = Depends(get_caller), ctx=Depends(get_ctx)):
    _require_the_student(caller, studentId, "Only the student may edit their own hours.")
    maybe_fail_commitment()
    snap = need_class(ctx, classId)
    week = next((w for w in snap.weeks if w.week_number == weekNumber), None)
    if week is None:
        raise HTTPException(status_code=404, detail="No such week.")
    editable = editable_week_numbers(snap.weeks, ctx.clock())
    if weekNumber not in editable:
        raise HTTPException(status_code=400,
                            detail=f"Only week {' or '.join(str(n) for n in editable)} can be edited right now.")
    ctx.store.save_weekly_update(class_id=classId, student_id=studentId, week_id=week.id, week_number=weekNumber,
                                 hours=body.model_dump(), actor_id=studentId, entered_at=ctx.now_iso())
    ctx.service.invalidate(classId)
    snap = need_class(ctx, classId)
    return _commitments_payload(ctx, snap, studentId)


@router.get("/classes/{classId}/commitments/pending", response_model=list[PendingBaseline], tags=["commitments"],
            responses={401: {}, 403: {}})
def list_pending_baselines(classId: str, caller: Caller = Depends(require_instructor), ctx=Depends(get_ctx)):
    snap = need_class(ctx, classId)
    students_by_id = {s.id: s for s in snap.students}
    rows = ctx.store.list_pending_baselines(classId)
    return [
        {"baseline": b, "student_id": b["student_id"],
         "display_name": _display_name_for(students_by_id, b["student_id"])}
        for b in rows
    ]


@router.get("/classes/{classId}/commitments/weekly-updates", response_model=list[StudentWeeklyUpdate],
            tags=["commitments"], responses={401: {}, 403: {}})
def list_weekly_updates(classId: str, caller: Caller = Depends(require_instructor), ctx=Depends(get_ctx)):
    snap = need_class(ctx, classId)
    students_by_id = {s.id: s for s in snap.students}
    rows = ctx.store.list_weekly_updates(classId)
    return [
        {"update": u, "student_id": u["student_id"],
         "display_name": _display_name_for(students_by_id, u["student_id"])}
        for u in reversed(rows)
    ]


@router.get("/classes/{classId}/commitments/change-log", response_model=list[ChangeLogEntry],
            tags=["commitments"], responses={401: {}, 403: {}, 404: {}})
def get_change_log(classId: str, studentId: str | None = Query(default=None, alias="studentId"),
                   caller: Caller = Depends(require_instructor), ctx=Depends(get_ctx)):
    need_class(ctx, classId)
    return ctx.store.list_change_log(classId, studentId)


@router.post("/classes/{classId}/commitments/baselines/{baselineId}/decide", response_model=Baseline,
             tags=["commitments"], responses={400: {}, 401: {}, 403: {}, 404: {}, 409: {}})
def decide_baseline(classId: str, baselineId: str, body: BaselineDecisionRequest,
                    caller: Caller = Depends(require_instructor), ctx=Depends(get_ctx)):
    snap = need_class(ctx, classId)
    effective = body.effectiveFromWeek
    if body.decision == "approved":
        if effective is None:
            effective = calendar_week_number(snap.weeks, ctx.clock())
        max_week = snap.weeks[-1].week_number if snap.weeks else None
        if effective is None or effective < 1 or (max_week is not None and effective > max_week):
            raise HTTPException(status_code=400, detail="effectiveFromWeek must be a valid week number.")
    try:
        result = ctx.store.decide_baseline(class_id=classId, baseline_id=baselineId, status=body.decision,
                                           effective_from_week=effective, decided_by=instructor_id_of(caller),
                                           decided_at=ctx.now_iso())
    except KeyError:
        raise HTTPException(status_code=404, detail="No such pending baseline.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    ctx.service.invalidate(classId)
    return result


@router.post("/classes/{classId}/commitments/weekly-updates/{updateId}/reverse", response_model=WeeklyUpdate,
             tags=["commitments"], responses={401: {}, 403: {}, 404: {}, 409: {}})
def reverse_weekly_update(classId: str, updateId: str,
                          caller: Caller = Depends(require_instructor), ctx=Depends(get_ctx)):
    need_class(ctx, classId)
    try:
        result = ctx.store.reverse_weekly_update(class_id=classId, update_id=updateId,
                                                  reversed_by=instructor_id_of(caller),
                                                  reversed_at=ctx.now_iso())
    except KeyError:
        raise HTTPException(status_code=404, detail="No such weekly update.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    ctx.service.invalidate(classId)
    return result


def _note_counts_by_student(notes: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n in notes:
        counts[n["student_id"]] = counts.get(n["student_id"], 0) + 1
    return counts


def _digest_group(ctx, klass, instructor_id: str, week: int | None) -> dict:
    current = ctx.service.evaluate_class(klass.id, week)
    if current["week"] > 1:
        prior = ctx.service.evaluate_class(klass.id, current["week"] - 1)
    else:
        prior = {"week": None, "rows": []}
    prior_by_id = {r["student_id"]: r for r in prior["rows"]}
    note_counts = _note_counts_by_student(ctx.store.list_notes(klass.id, None, instructor_id))
    rows = []
    for r in current["rows"]:
        status = diff_state(prior_by_id.get(r["student_id"]), r)
        if status == "quiet":
            continue
        rows.append({"student_id": r["student_id"], "display_name": r["display_name"],
                     "level": r["level"], "status": status,
                     "priorLevel": (prior_by_id.get(r["student_id"]) or {}).get("level"),
                     "signals": [s["label"] for s in r["signals"] if s["on"]],
                     "notes": note_counts.get(r["student_id"], 0)})
    level_rank = {lvl: i for i, lvl in enumerate(LEVEL_ORDER)}
    rows.sort(key=lambda r: (-level_rank.get(r["level"], 0), r["display_name"].lower()))
    return {"classId": klass.id, "className": klass.name, "week": current["week"],
            "comparedWith": prior["week"], "rows": rows}


@router.get("/instructor/digest", response_model=Digest, tags=["risk"],
            responses={401: {}, 403: {}})
def get_digest(week: int | None = Query(default=None, alias="week",
                                        description="Week number. Defaults to each class's own latest complete week."),
               caller: Caller = Depends(require_instructor), ctx=Depends(get_ctx)):
    instructor_id = instructor_id_of(caller)
    groups = [_digest_group(ctx, klass, instructor_id, week) for klass in ctx.db.list_classes(instructor_id)]
    return {"instructorId": instructor_id, "groups": groups, "computedAt": ctx.now_iso()}


def _risk_record(ctx, classId: str, studentId: str, caller: Caller) -> dict:
    snap = need_class(ctx, classId)
    student = next((s for s in snap.students if s.id == studentId), None)
    if student is None:
        raise HTTPException(status_code=404, detail="No such student in this class.")
    risk_settings = ctx.store.get_risk_settings(classId)

    def evaluate_at(week_number: int) -> dict:
        return evaluate_signals(weekly=risk_weekly(snap, student, week_number),
                                hours=hours_at(snap, student, week_number),
                                thresholds=risk_settings["thresholds"], active=risk_settings["active"])

    week = evaluation_week_number(snap)
    current = evaluate_at(week)
    joined = student.joined_week or 1
    history = [{"week_number": w, "level": ev["level"], "count": len(ev["signals_on"])}
               for w in range(max(joined, 2), week + 1) for ev in [evaluate_at(w)]]
    klass = next((c for c in ctx.db.list_classes() if c.id == classId), None)
    notes = ctx.store.list_notes(classId, studentId, instructor_id_of(caller)) if caller.role == "instructor" else []
    return {"classId": classId, "className": klass.name if klass else classId,
            "student_id": studentId, "display_name": student.display_name, "week": week,
            "level": current["level"], "oneAway": current["oneAway"], "signals": current["signals"],
            "metrics": current["metrics"], "thresholds": risk_settings["thresholds"],
            "history": history, "notes": notes}


@router.get("/classes/{classId}/students/{studentId}/risk", response_model=RiskRecord, tags=["risk"],
            responses={401: {}, 403: {}, 404: {}})
def get_risk_record(classId: str, studentId: str,
                    caller: Caller = Depends(get_caller), ctx=Depends(get_ctx)):
    _require_self_if_student(caller, studentId, "A student may only open their own standing.")
    return _risk_record(ctx, classId, studentId, caller)


@router.post("/classes/{classId}/students/{studentId}/notes", response_model=Note,
             status_code=201, tags=["risk"], responses={400: {}, 401: {}, 403: {}})
def add_note(classId: str, studentId: str, body: NoteRequest,
             caller: Caller = Depends(require_instructor), ctx=Depends(get_ctx)):
    need_class(ctx, classId)
    text = (body.body or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="A note needs some text.")
    return ctx.store.add_note(class_id=classId, student_id=studentId,
                              instructor_id=instructor_id_of(caller), body=text,
                              at=ctx.now_iso())


@router.get("/classes/{classId}/risk-settings", response_model=RiskSettings, tags=["risk"],
            responses={401: {}, 403: {}})
def get_risk_settings(classId: str, caller: Caller = Depends(require_instructor), ctx=Depends(get_ctx)):
    need_class(ctx, classId)
    return ctx.store.get_risk_settings(classId)


@router.put("/classes/{classId}/risk-settings", response_model=RiskSettings, tags=["risk"],
            responses={401: {}, 403: {}})
def save_risk_settings(classId: str, patch: RiskSettingsPatch,
                       caller: Caller = Depends(require_instructor), ctx=Depends(get_ctx)):
    need_class(ctx, classId)
    return ctx.store.save_risk_settings(classId, patch.model_dump(exclude_none=True))


@router.get("/me/standing", response_model=Standing, tags=["students"],
            responses={401: {}, 403: {}})
def get_standing(classId: str = Query(alias="classId"), studentId: str = Query(alias="studentId"),
                 caller: Caller = Depends(get_caller), ctx=Depends(get_ctx)):
    _require_self_if_student(caller, studentId, "A student may only read their own standing.")
    record = _risk_record(ctx, classId, studentId,
                          Caller(role="student", studentId=studentId, classId=classId))
    return {"student_id": record["student_id"], "display_name": record["display_name"],
            "week": record["week"], "level": record["level"],
            "signals": [s for s in record["signals"] if s["on"]],
            "metrics": record["metrics"], "help": HELP_TEXT}
