"""Time commitments: what a student enters, and what the instructor approves and reverses.

The edit window, the approval rules and the caps are all enforced here, from the Weeks
calendar and the server clock, never the browser.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.commitments import (
    STEP, PER_TYPE_MAX, TOTAL_MAX, CommitmentBook, InvalidHours, adjust, current_week, editable_weeks,
    factor_for, validate_hours, weighted_hours,
)
from app.datasource import Snapshot
from app.deps import (
    AppContext, class_router, current_account, get_ctx, require_instructor, require_student,
)
from app.errors import unprocessable
from app.models import (
    Approvals, Baseline, CommitmentType, DecisionRequest, EditWindow, Error, HoursRequest, HourLimits,
    LogEntry, MyCommitments, PendingApproval, Preview, PreviewRequest, StudentCommitments, WeekFactor,
    WeeklyUpdate,
)
from app.ranking import rank_table
from app.routers.classes import FORBIDDEN, NOT_FOUND, UNAUTHORIZED, UNAVAILABLE, current_weights
from app.store import COMMITMENT_TYPES, Hours, StoredAccount
from app.store import Baseline as StoredBaseline
from app.store import LogEntry as StoredLogEntry
from app.store import WeeklyUpdate as StoredUpdate

me = APIRouter(prefix="/me", dependencies=[Depends(current_account)])
router = class_router()

LOCKED = "Only the current and previous week can be edited."
NO_CLASS = {404: {"model": Error, "description": "The student is not in a class."}}


def clean(hours: Hours) -> Hours:
    try:
        return validate_hours(hours)
    except InvalidHours as error:
        raise unprocessable(("body", "hours"), str(error), hours)


def to_baseline(baseline: StoredBaseline) -> Baseline:
    return Baseline(
        id=baseline.id, student_id=baseline.student_id, hours=baseline.hours, status=baseline.status,
        effective_from_week=baseline.effective_from_week, submitted_at=baseline.submitted_at,
        decided_at=baseline.decided_at,
    )


def student_snapshot(ctx: AppContext, account: StoredAccount) -> tuple[str, Snapshot]:
    class_id = ctx.class_id_of(account.student_id)
    if class_id is None:
        raise HTTPException(status_code=404, detail="You are not in a class.")
    return class_id, ctx.service.snapshot(class_id)


def week_by_number(snapshot: Snapshot, number: int):
    week = next((w for w in snapshot.weeks if w.week_number == number), None)
    if week is None:
        raise HTTPException(status_code=404, detail="Unknown week.")
    return week


def review_flag(book: CommitmentBook, params, student_id: str, week, hours: Hours | None) -> bool:
    """A weekly entry that differs from the baseline by more than the threshold, in total hours."""
    baseline = book.baseline_for(student_id, week.week_number)
    if baseline is None or hours is None:
        return False
    return abs(sum(hours.values()) - sum(baseline.hours.values())) > params.flag_hours


# The student's own screens


@me.get(
    "/commitments",
    tags=["Commitments"],
    operation_id="getMyCommitments",
    summary="Your baseline, weekly updates and factor by week (student only)",
    response_model=MyCommitments,
    responses=UNAUTHORIZED | FORBIDDEN | NO_CLASS,
)
def get_my_commitments(account: StoredAccount = Depends(require_student), ctx: AppContext = Depends(get_ctx)):
    class_id, snapshot = student_snapshot(ctx, account)
    sid = account.student_id
    adjuster = ctx.adjuster(class_id)
    book, params = adjuster.book, adjuster.params

    weeks = snapshot.weeks
    current = current_week(weeks, ctx.today())
    today_week = current or weeks[-1]
    baselines = ctx.store.list_baselines(sid)
    in_effect = book.baseline_for(sid, today_week.week_number)
    editable = editable_weeks(weeks, ctx.today())
    editable_ids = {w.id for w in editable}

    updates = []
    factors = []
    for week in weeks:
        update = book.active_update(sid, week.id)
        if update is not None:
            updates.append(
                WeeklyUpdate(
                    week_id=week.id, week_number=week.week_number, hours=update.hours,
                    entered_at=update.entered_at, editable=week.id in editable_ids,
                )
            )
        hours = book.hours_for(sid, week)
        total = sum(weighted_hours(hours, params).values()) if hours is not None else 0.0
        factors.append(
            WeekFactor(
                week_id=week.id, week_number=week.week_number,
                source="none" if hours is None else "weekly" if update is not None and update.hours is not None else "baseline",
                hours=hours, weighted_hours=total, factor=factor_for(total, params) if hours is not None else 1.0,
            )
        )

    return MyCommitments(
        types=[CommitmentType(key=k, label=label) for k, label in COMMITMENT_TYPES],
        limits=HourLimits(step=STEP, per_type_max=PER_TYPE_MAX, total_max=TOTAL_MAX),
        baseline=to_baseline(baselines[-1]) if baselines else None,
        in_effect=to_baseline(in_effect) if in_effect else None,
        weekly_updates=updates,
        weeks=factors,
        edit_window=EditWindow(
            current_week_id=current.id if current else None, editable_week_ids=[w.id for w in editable]
        ),
    )


@me.put(
    "/commitments/baseline",
    tags=["Commitments"],
    operation_id="saveMyBaseline",
    summary="Submit a semester baseline for approval (student only)",
    description=(
        "Starts as `pending` and has no effect until the instructor approves it. Submitting "
        "again while one is pending replaces it; submitting after an approval is a baseline "
        "change that also waits for approval."
    ),
    response_model=Baseline,
    responses=UNAUTHORIZED | FORBIDDEN | NO_CLASS,
)
def save_my_baseline(body: HoursRequest, account: StoredAccount = Depends(require_student), ctx: AppContext = Depends(get_ctx)):
    student_snapshot(ctx, account)
    hours = clean(body.hours)
    sid, now = account.student_id, ctx.now()
    previous = ctx.store.list_baselines(sid)
    old = {"hours": previous[-1].hours, "status": previous[-1].status} if previous else None
    saved = ctx.store.save_baseline(
        sid, hours, now, StoredLogEntry("", account.id, "baseline_submitted", sid, None, old, {"hours": hours}, now)
    )
    return to_baseline(saved)


@me.put(
    "/commitments/weeks/{week_number}",
    tags=["Commitments"],
    operation_id="saveMyWeek",
    summary="Set your hours for one week (student only)",
    description=(
        "Replaces the baseline hours for that week. Only the current and previous week can be "
        "edited; any other week is refused with 403, using the server's clock. The update takes "
        "effect at once, but only counts once an approved baseline covers that week."
    ),
    response_model=WeeklyUpdate,
    responses=UNAUTHORIZED
    | FORBIDDEN
    | {404: {"model": Error, "description": "Unknown week."}},
)
def save_my_week(
    week_number: int, body: HoursRequest,
    account: StoredAccount = Depends(require_student), ctx: AppContext = Depends(get_ctx),
):
    class_id, snapshot = student_snapshot(ctx, account)
    week = week_by_number(snapshot, week_number)
    window = editable_weeks(snapshot.weeks, ctx.today())
    if week not in window:
        raise HTTPException(status_code=403, detail=LOCKED)
    hours = clean(body.hours)

    sid, now = account.student_id, ctx.now()
    adjuster = ctx.adjuster(class_id)
    before = adjuster.book.hours_for(sid, week)
    flagged = review_flag(adjuster.book, adjuster.params, sid, week, hours)
    update = ctx.store.save_weekly_update(
        sid, week.id, hours, now,
        StoredLogEntry("", account.id, "weekly_update", sid, week.id,
                       None if before is None else {"hours": before}, {"hours": hours}, now, flagged),
    )
    return WeeklyUpdate(
        week_id=week.id, week_number=week.week_number, hours=update.hours,
        entered_at=update.entered_at, editable=True,
    )


@me.delete(
    "/commitments/weeks/{week_number}",
    tags=["Commitments"],
    operation_id="resetMyWeek",
    summary="Reset one week to your baseline (student only)",
    status_code=204,
    response_class=Response,
    responses=UNAUTHORIZED
    | FORBIDDEN
    | {404: {"model": Error, "description": "Unknown week."}},
)
def reset_my_week(week_number: int, account: StoredAccount = Depends(require_student), ctx: AppContext = Depends(get_ctx)):
    class_id, snapshot = student_snapshot(ctx, account)
    week = week_by_number(snapshot, week_number)
    if week not in editable_weeks(snapshot.weeks, ctx.today()):
        raise HTTPException(status_code=403, detail=LOCKED)
    sid, now = account.student_id, ctx.now()
    active = ctx.adjuster(class_id).book.active_update(sid, week.id)
    if active is None or active.hours is None:
        return Response(status_code=204)  # already following the baseline
    ctx.store.save_weekly_update(
        sid, week.id, None, now,
        StoredLogEntry("", account.id, "weekly_reset", sid, week.id, {"hours": active.hours}, None, now),
    )
    return Response(status_code=204)


@me.post(
    "/commitments/preview",
    tags=["Commitments"],
    operation_id="previewMyAdjustment",
    summary="Your factor and adjusted score for hours you have not saved (student only)",
    description="Shows what the hours would give once an approved baseline covers the week. Nothing is stored.",
    response_model=Preview,
    responses=UNAUTHORIZED | FORBIDDEN | NO_CLASS | {404: {"model": Error, "description": "No scores for that week."}},
)
def preview(body: PreviewRequest, account: StoredAccount = Depends(require_student), ctx: AppContext = Depends(get_ctx)):
    class_id, snapshot = student_snapshot(ctx, account)
    sid = account.student_id
    scored_weeks = [w for w in snapshot.weeks if any(e.student_id == sid and e.week_id == w.id for e in snapshot.entries)]
    if body.week_id is not None:
        week = next((w for w in snapshot.weeks if w.id == body.week_id), None)
        if week is None:
            raise HTTPException(status_code=404, detail="Unknown week.")
    elif scored_weeks:
        week = scored_weeks[-1]
    else:
        raise HTTPException(status_code=404, detail="You have no scores yet.")
    hours = clean(body.hours)

    adjuster = ctx.adjuster(class_id)
    rows = rank_table(
        snapshot, week_id=week.id, window="week", criteria=snapshot.criteria,
        weights=current_weights(ctx, snapshot), name_mode="full", adjuster=adjuster,
    )
    row = next((r for r in rows if r.student_id == sid), None)
    if row is None:
        raise HTTPException(status_code=404, detail="You have no scores that week.")
    result = adjust(row.raw, hours, adjuster.params)
    return Preview(
        week_id=week.id, raw_score=result.raw, weighted_hours=result.weighted_total,
        factor=result.factor, adjusted_score=result.adjusted, capped=result.capped,
    )


# The instructor's screens


def names_by_student(snapshot: Snapshot) -> dict[str, str]:
    return {s.id: s.display_name for s in snapshot.students}


@router.get(
    "/approvals",
    tags=["Commitments"],
    operation_id="listApprovals",
    summary="Baselines waiting for a decision (instructor only)",
    response_model=Approvals,
    dependencies=[Depends(require_instructor)],
    responses=UNAUTHORIZED | FORBIDDEN | NOT_FOUND | UNAVAILABLE,
)
def list_approvals(class_id: str, ctx: AppContext = Depends(get_ctx)):
    snapshot = ctx.service.snapshot(class_id)
    names = names_by_student(snapshot)
    book = ctx.adjuster(class_id).book
    current = current_week(snapshot.weeks, ctx.today())
    last = snapshot.weeks[-1].week_number
    pending = []
    for baseline in ctx.store.list_baselines():
        if baseline.status != "pending" or baseline.student_id not in names:
            continue
        in_force = book.baseline_for(baseline.student_id, last)
        pending.append(
            PendingApproval(
                id=baseline.id, student_id=baseline.student_id, display_name=names[baseline.student_id],
                hours=baseline.hours, submitted_at=baseline.submitted_at, is_change=in_force is not None,
                current=in_force.hours if in_force else None,
                suggested_effective_week=current.week_number if current else None,
            )
        )
    return Approvals(pending=pending, current_week=current.week_number if current else None)


@router.post(
    "/approvals/{approval_id}",
    tags=["Commitments"],
    operation_id="decideApproval",
    summary="Approve a baseline from a week, or reject it (instructor only)",
    response_model=Baseline,
    dependencies=[Depends(require_instructor)],
    responses=UNAUTHORIZED
    | FORBIDDEN
    | UNAVAILABLE
    | {
        404: {"model": Error, "description": "Unknown class or approval."},
        409: {"model": Error, "description": "That baseline has already been decided."},
    },
)
def decide_approval(
    class_id: str, approval_id: str, body: DecisionRequest,
    account: StoredAccount = Depends(require_instructor), ctx: AppContext = Depends(get_ctx),
):
    snapshot = ctx.service.snapshot(class_id)
    baseline = ctx.store.get_baseline(approval_id)
    if baseline is None or baseline.student_id not in names_by_student(snapshot):
        raise HTTPException(status_code=404, detail="Unknown approval.")
    if baseline.status != "pending":
        raise HTTPException(status_code=409, detail="That baseline has already been decided.")

    approve = body.decision == "approve"
    effective = None
    if approve:
        current = current_week(snapshot.weeks, ctx.today())
        effective = body.effective_week if body.effective_week is not None else (current.week_number if current else None)
        if effective is None:
            raise unprocessable(("body", "effective_week"), "Choose the week the baseline counts from.", None)
        if effective > snapshot.weeks[-1].week_number:
            raise unprocessable(("body", "effective_week"), "That week is not in the term.", effective)

    now = ctx.now()
    new = {"status": "approved", "effective_from_week": effective, "hours": baseline.hours} if approve else {
        "status": "rejected", "hours": baseline.hours,
    }
    decided = ctx.store.decide_baseline(
        approval_id, status="approved" if approve else "rejected", effective_from_week=effective,
        decided_by=account.id, at=now,
        entry=StoredLogEntry(
            "", account.id, "baseline_approved" if approve else "baseline_rejected",
            baseline.student_id, None, {"status": "pending"}, new, now,
        ),
    )
    return to_baseline(decided)


@router.post(
    "/students/{student_id}/weeks/{week_number}/reverse",
    tags=["Commitments"],
    operation_id="reverseWeeklyUpdate",
    summary="Reverse a student's weekly update (instructor only)",
    description="Restores the value before the update, whether an earlier update or the baseline. The reversal is logged.",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require_instructor)],
    responses=UNAUTHORIZED
    | FORBIDDEN
    | UNAVAILABLE
    | {404: {"model": Error, "description": "Unknown class, student or week, or nothing to reverse."}},
)
def reverse_weekly_update(
    class_id: str, student_id: str, week_number: int,
    account: StoredAccount = Depends(require_instructor), ctx: AppContext = Depends(get_ctx),
):
    snapshot = ctx.service.snapshot(class_id)
    if student_id not in names_by_student(snapshot):
        raise HTTPException(status_code=404, detail="Unknown student.")
    week = week_by_number(snapshot, week_number)
    adjuster = ctx.adjuster(class_id)
    update = adjuster.book.active_update(student_id, week.id)
    if update is None:
        raise HTTPException(status_code=404, detail="There is no weekly update to reverse.")

    after = CommitmentBook(
        ctx.store.list_baselines(), [u for u in ctx.store.list_weekly_updates() if u.id != update.id]
    ).hours_for(student_id, week)
    now = ctx.now()
    ctx.store.reverse_weekly_update(
        update.id, reversed_by=account.id, at=now,
        entry=StoredLogEntry(
            "", account.id, "weekly_reversed", student_id, week.id,
            None if update.hours is None else {"hours": update.hours},
            None if after is None else {"hours": after}, now,
        ),
    )
    return Response(status_code=204)


@router.get(
    "/change-log",
    tags=["Commitments"],
    operation_id="getChangeLog",
    summary="Every commitment change, newest first (instructor only)",
    response_model=list[LogEntry],
    dependencies=[Depends(require_instructor)],
    responses=UNAUTHORIZED | FORBIDDEN | NOT_FOUND | UNAVAILABLE,
)
def get_change_log(
    class_id: str,
    student_id: str | None = Query(default=None, description="Only this student's entries."),
    limit: int = Query(default=200, ge=1, le=1000),
    ctx: AppContext = Depends(get_ctx),
):
    snapshot = ctx.service.snapshot(class_id)
    names = names_by_student(snapshot)
    week_numbers = {w.id: w.week_number for w in snapshot.weeks}
    account_names = {
        a.id: "Instructor" if a.role == "instructor" else names.get(a.student_id, "Student")
        for a in ctx.store.list_accounts()
    }
    latest = {}  # the update that is active for each student and week
    for update in ctx.store.list_weekly_updates():
        if update.reversed_at is None:
            latest[(update.student_id, update.week_id)] = update.entry_id

    entries = [e for e in ctx.store.list_log(student_id) if e.student_id is None or e.student_id in names]
    return [
        LogEntry(
            id=e.id, actor_id=e.actor_id, actor_name=account_names.get(e.actor_id, "Unknown"), action=e.action,
            student_id=e.student_id, student_name=names.get(e.student_id), week_id=e.week_id,
            week_number=week_numbers.get(e.week_id), old_values=e.old_values, new_values=e.new_values,
            at=e.at, flagged=e.flagged,
            reversible=e.action in ("weekly_update", "weekly_reset")
            and latest.get((e.student_id, e.week_id)) == e.id,
        )
        for e in reversed(entries)
    ][:limit]


@router.get(
    "/commitments",
    tags=["Commitments"],
    operation_id="listStudentCommitments",
    summary="Every student's baseline status, hours and factor (instructor only)",
    response_model=list[StudentCommitments],
    dependencies=[Depends(require_instructor)],
    responses=UNAUTHORIZED | FORBIDDEN | NOT_FOUND | UNAVAILABLE,
)
def list_student_commitments(class_id: str, ctx: AppContext = Depends(get_ctx)):
    snapshot = ctx.service.snapshot(class_id)
    adjuster = ctx.adjuster(class_id)
    week = current_week(snapshot.weeks, ctx.today()) or snapshot.weeks[-1]
    rows = []
    for student in snapshot.students:
        baselines = ctx.store.list_baselines(student.id)
        submitted = [b for b in baselines if not (b.status == "superseded" and b.effective_from_week is None)]
        latest = submitted[-1] if submitted else None
        hours = adjuster.book.hours_for(student.id, week)
        total = sum(weighted_hours(hours, adjuster.params).values()) if hours is not None else 0.0
        in_force = adjuster.book.baseline_for(student.id, week.week_number)
        if in_force is not None or (latest is not None and latest.status in ("approved", "superseded")):
            status = "approved"
        else:
            status = "none" if latest is None else latest.status
        shown = in_force or latest
        rows.append(
            StudentCommitments(
                student_id=student.id, display_name=student.display_name, status=status,
                hours=shown.hours if shown else None,
                effective_from_week=shown.effective_from_week if shown else None,
                weighted_hours=total, factor=factor_for(total, adjuster.params) if hours is not None else 1.0,
            )
        )
    return rows
