import json
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Query
from pydantic import TypeAdapter, ValidationError

from app.datasource import Snapshot
from app.deps import AppContext, class_router, current_account, get_ctx
from app.errors import unprocessable
from app.models import (
    Criterion, Error, Explanation, NameMode, Ranking, RankingRow, WeekBreakdown, Weights, WindowMode,
)
from app.ranking import (
    DEFAULT_ROLLING_WEEKS, above_name, gap_to_below, gap_to_next, previous_ranks, rank_table,
)
from app.store import StoredAccount
from app.routers.classes import NOT_FOUND, UNAUTHORIZED, UNAVAILABLE, current_weights, utc
from app.scoring import normalise_weights

router = class_router()

_weights_adapter = TypeAdapter(Weights)


@dataclass
class ViewOptions:
    """The query parameters the ranking and explanation share, as sent."""

    week: str
    window: WindowMode
    criteria: list[str] | None
    weights: dict[str, float] | None
    name_mode: NameMode
    rolling_weeks: int = DEFAULT_ROLLING_WEEKS


def view_options(
    week: str = Query(description="ID of the week to rank. With `window=cumulative`, the last week included."),
    window: WindowMode = Query(default="week", description="`week` scores only that week; `cumulative` averages week 1 through `week`; `rolling` averages the last `rolling_weeks` weeks ending at `week`."),
    rolling_weeks: int = Query(default=DEFAULT_ROLLING_WEEKS, ge=2, le=16, description="How many weeks a `rolling` window covers."),
    criteria: str | None = Query(default=None, description="Criterion keys to include, comma-separated. Omitted or empty means all."),
    weights: str | None = Query(default=None, description="JSON object of criterion key to weight, to preview unsaved weights."),
    name_mode: NameMode = Query(default="full", description="How names are shown in `display_name`."),
) -> ViewOptions:
    keys = [key.strip() for key in criteria.split(",") if key.strip()] if criteria else None
    return ViewOptions(week, window, keys or None, parse_weights(weights), name_mode, rolling_weeks)


def parse_weights(raw: str | None) -> dict[str, float] | None:
    if raw is None:
        return None
    message = "Must be a JSON object mapping criterion key to a non-negative number."
    try:
        return _weights_adapter.validate_python(json.loads(raw))
    except (ValueError, ValidationError):
        raise unprocessable(("query", "weights"), message, raw)


@dataclass
class View:
    """What the caller asked for, checked against the class and ready to score."""

    week_id: str
    window: WindowMode
    criteria: list[Criterion]
    weights: dict[str, float]  # selected criteria only, rescaled to total 100
    name_mode: NameMode
    rolling_weeks: int


def resolve_view(ctx: AppContext, snapshot: Snapshot, options: ViewOptions) -> View:
    if options.week not in {w.id for w in snapshot.weeks}:
        raise HTTPException(status_code=404, detail="Unknown week.")

    known = {c.key for c in snapshot.criteria}
    if options.criteria:
        unknown = [key for key in options.criteria if key not in known]
        if unknown:
            raise unprocessable(("query", "criteria"), f"Unknown criterion: {', '.join(unknown)}", options.criteria)
        selected = [c for c in snapshot.criteria if c.key in options.criteria]
    else:
        selected = list(snapshot.criteria)

    if options.weights is not None:
        unknown = [key for key in options.weights if key not in known]
        if unknown:
            raise unprocessable(("query", "weights"), f"Unknown criterion: {', '.join(unknown)}", options.weights)
        base = options.weights
    else:
        base = current_weights(ctx, snapshot)

    # Criteria not listed get weight 0; only the selected criteria share the 100 points.
    weights = normalise_weights({c.key: base.get(c.key, 0.0) for c in selected})
    return View(options.week, options.window, selected, weights, options.name_mode, options.rolling_weeks)


@router.get(
    "/ranking",
    tags=["Ranking"],
    operation_id="getRanking",
    summary="The ranked table for a week or cumulative window",
    response_model=Ranking,
    responses=UNAUTHORIZED | NOT_FOUND | UNAVAILABLE,
)
def get_ranking(class_id: str, options: ViewOptions = Depends(view_options), ctx: AppContext = Depends(get_ctx)):
    snapshot = ctx.service.snapshot(class_id)
    view = resolve_view(ctx, snapshot, options)
    adjuster = ctx.adjuster(class_id)
    rows = rank_table(
        snapshot, week_id=view.week_id, window=view.window, criteria=view.criteria, weights=view.weights,
        name_mode=view.name_mode, adjuster=adjuster, rolling_weeks=view.rolling_weeks,
    )
    before = previous_ranks(
        snapshot, week_id=view.week_id, window=view.window, criteria=view.criteria, weights=view.weights,
        adjuster=adjuster, rolling_weeks=view.rolling_weeks,
    )
    return Ranking(
        class_id=class_id,
        week_id=view.week_id,
        window_mode=view.window,
        rolling_weeks=view.rolling_weeks if view.window == "rolling" else None,
        criteria_keys=[c.key for c in view.criteria],
        weights=view.weights,
        rows=[
            RankingRow(
                student_id=row.student_id,
                display_name=row.display_name,
                score=row.score,
                rank=row.rank,
                tied=row.tied,
                rank_delta=before[row.student_id] - row.rank if row.student_id in before else None,
                missing=row.missing_keys,
                gap_to_next=gap_to_next(rows, i),
                gap_to_below=gap_to_below(rows, i),
            )
            for i, row in enumerate(rows)
        ],
        last_updated=utc(snapshot.at),
        stale=snapshot.stale,
        issues=snapshot.issues,
    )


@router.get(
    "/students/{student_id}/explanation",
    tags=["Ranking"],
    operation_id="getExplanation",
    summary="How one student's rank was reached, criterion by criterion",
    response_model=Explanation,
    responses=UNAUTHORIZED
    | UNAVAILABLE
    | {
        403: {"model": Error, "description": "A student asked for someone else's breakdown."},
        404: {"model": Error, "description": "Unknown class or student, or no entries in this window."},
    },
)
def get_explanation(
    class_id: str,
    student_id: str,
    options: ViewOptions = Depends(view_options),
    account: StoredAccount = Depends(current_account),
    ctx: AppContext = Depends(get_ctx),
):
    # Checked before anything is read, so a student learns nothing about other students' ids.
    if account.role == "student" and account.student_id != student_id:
        raise HTTPException(status_code=403, detail="A student may only open their own breakdown.")

    snapshot = ctx.service.snapshot(class_id)
    view = resolve_view(ctx, snapshot, options)
    rows = rank_table(
        snapshot, week_id=view.week_id, window=view.window, criteria=view.criteria, weights=view.weights,
        name_mode=view.name_mode, adjuster=ctx.adjuster(class_id), rolling_weeks=view.rolling_weeks,
    )
    index = next((i for i, row in enumerate(rows) if row.student_id == student_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="No entries for that student in this window.")

    row = rows[index]
    single = len(row.weeks) == 1
    only = row.weeks[0].adjustment
    return Explanation(
        student_id=student_id,
        display_name=row.display_name,
        rank=row.rank,
        tied=row.tied,
        score=row.score,
        raw_score=row.raw,
        factor=only.factor if single else None,
        weighted_hours=only.weighted_total if single else None,
        hours=only.weighted if single else None,
        capped=row.capped,
        parts=row.parts,
        weeks=[
            WeekBreakdown(
                week_id=w.week.id, week_number=w.week.week_number, raw_score=w.raw,
                weighted_hours=w.adjustment.weighted_total, factor=w.adjustment.factor,
                adjusted_score=w.adjustment.adjusted, capped=w.adjustment.capped,
            )
            for w in row.weeks
        ],
        gap_to_next=gap_to_next(rows, index),
        gap_to_below=gap_to_below(rows, index),
        above=above_name(rows, index),
        week_id=view.week_id,
        window_mode=view.window,
        rolling_weeks=view.rolling_weeks if view.window == "rolling" else None,
    )
