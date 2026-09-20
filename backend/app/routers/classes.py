from datetime import datetime, timezone

from fastapi import Depends

from app.datasource import Snapshot
from app.deps import AppContext, class_router, get_ctx, require_teacher
from app.errors import unprocessable
from app.models import (
    ClassBootstrap, Criterion, Error, SaveWeightsRequest, Week, WeightsResponse,
)
from app.ranking import TIE_BREAKER_KEYS
from app.scoring import normalise_weights

router = class_router()

NOT_FOUND = {404: {"model": Error, "description": "Unknown class."}}
UNAUTHORIZED = {401: {"model": Error, "description": "No valid session."}}
UNAVAILABLE = {503: {"model": Error, "description": "The data source did not respond and nothing is cached."}}


def utc(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def current_weights(ctx: AppContext, snapshot: Snapshot) -> dict[str, float]:
    """Saved weights, or each criterion's default weight if none are saved. Totals 100."""
    saved = ctx.settings.get_weights(snapshot.cls.id)
    if saved is not None:
        return {c.key: saved.get(c.key, 0.0) for c in snapshot.criteria}
    return normalise_weights({c.key: c.default_weight for c in snapshot.criteria})


@router.get(
    "",
    tags=["Class"],
    operation_id="getClass",
    summary="Everything the page needs to start",
    response_model=ClassBootstrap,
    responses=UNAUTHORIZED | NOT_FOUND | UNAVAILABLE,
)
def get_class(class_id: str, ctx: AppContext = Depends(get_ctx)):
    snapshot = ctx.service.snapshot(class_id)
    labels = {c.key: c.label for c in snapshot.criteria}
    return ClassBootstrap(
        class_=snapshot.cls,
        weeks=snapshot.weeks,
        criteria=snapshot.criteria,
        weights=current_weights(ctx, snapshot),
        tie_breakers=[labels[key] for key in TIE_BREAKER_KEYS if key in labels],
        source=ctx.source_info(),
        last_updated=utc(snapshot.at),
        issues=snapshot.issues,
    )


@router.get(
    "/weeks",
    tags=["Class"],
    operation_id="listWeeks",
    summary="Weeks of the term, in order",
    response_model=list[Week],
    responses=UNAUTHORIZED | NOT_FOUND | UNAVAILABLE,
)
def list_weeks(class_id: str, ctx: AppContext = Depends(get_ctx)):
    return ctx.service.snapshot(class_id).weeks


@router.get(
    "/criteria",
    tags=["Class"],
    operation_id="listCriteria",
    summary="Ranking criteria, in display order",
    response_model=list[Criterion],
    responses=UNAUTHORIZED | NOT_FOUND | UNAVAILABLE,
)
def list_criteria(class_id: str, ctx: AppContext = Depends(get_ctx)):
    return ctx.service.snapshot(class_id).criteria


@router.get(
    "/weights",
    tags=["Class"],
    operation_id="getWeights",
    summary="Saved criterion weights",
    response_model=WeightsResponse,
    responses=UNAUTHORIZED | NOT_FOUND | UNAVAILABLE,
)
def get_weights(class_id: str, ctx: AppContext = Depends(get_ctx)):
    snapshot = ctx.service.snapshot(class_id)
    return WeightsResponse(class_id=class_id, weights=current_weights(ctx, snapshot))


@router.put(
    "/weights",
    tags=["Class"],
    operation_id="saveWeights",
    summary="Save criterion weights (teacher only)",
    response_model=WeightsResponse,
    dependencies=[Depends(require_teacher)],
    responses=UNAUTHORIZED
    | NOT_FOUND
    | UNAVAILABLE
    | {403: {"model": Error, "description": "The caller's role does not allow this."}},
)
def save_weights(class_id: str, body: SaveWeightsRequest, ctx: AppContext = Depends(get_ctx)):
    snapshot = ctx.service.snapshot(class_id)
    keys = [c.key for c in snapshot.criteria]

    unknown = [key for key in body.weights if key not in keys]
    if unknown:
        raise unprocessable(("body", "weights"), f"Unknown criterion: {', '.join(unknown)}", body.weights)
    if sum(body.weights.values()) == 0:
        raise unprocessable(("body", "weights"), "At least one weight must be above zero.", body.weights)

    # Criteria left out are stored as zero, so the saved map always covers every criterion.
    weights = normalise_weights({key: body.weights.get(key, 0.0) for key in keys})
    ctx.settings.save_weights(class_id, weights)
    return WeightsResponse(class_id=class_id, weights=weights)
