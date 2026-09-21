from datetime import datetime, timezone

from fastapi import Depends

from app.datasource import Snapshot
from app.commitments import InvalidHours, validate_adjustment
from app.deps import AppContext, class_router, get_ctx, require_instructor
from app.errors import unprocessable
from app.explainer import build_explainer
from app.models import (
    AdjustmentSettings, ClassBootstrap, Criterion, Error, Explainer, SaveSettingsRequest, Settings, Week,
)
from app.ranking import TIE_BREAKER_KEYS
from app.scoring import normalise_weights
from app.store import AdjustmentSettings as StoredAdjustment
from app.store import LogEntry, Settings as StoredSettings

router = class_router()

NOT_FOUND = {404: {"model": Error, "description": "Unknown class."}}
UNAUTHORIZED = {401: {"model": Error, "description": "No valid session."}}
UNAVAILABLE = {503: {"model": Error, "description": "The data source did not respond and nothing is cached."}}


def utc(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def current_weights(ctx: AppContext, snapshot: Snapshot) -> dict[str, float]:
    """Saved weights, or each criterion's default weight if none are saved. Totals 100."""
    saved = ctx.store.get_settings(snapshot.cls.id).weights
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


FORBIDDEN = {403: {"model": Error, "description": "The caller's role does not allow this."}}


def settings_body(ctx: AppContext, snapshot: Snapshot) -> Settings:
    adjustment = ctx.store.get_settings(snapshot.cls.id).adjustment
    return Settings(
        weights=current_weights(ctx, snapshot),
        adjustment=AdjustmentSettings(
            type_weights=adjustment.type_weights, rate=adjustment.rate,
            cap=adjustment.cap, flag_hours=adjustment.flag_hours,
        ),
    )


@router.get(
    "/settings",
    tags=["Class"],
    operation_id="getSettings",
    summary="Criterion weights and adjustment parameters (instructor only)",
    response_model=Settings,
    dependencies=[Depends(require_instructor)],
    responses=UNAUTHORIZED | NOT_FOUND | UNAVAILABLE | FORBIDDEN,
)
def get_settings(class_id: str, ctx: AppContext = Depends(get_ctx)):
    return settings_body(ctx, ctx.service.snapshot(class_id))


@router.put(
    "/settings",
    tags=["Class"],
    operation_id="saveSettings",
    summary="Save criterion weights and adjustment parameters (instructor only)",
    response_model=Settings,
    responses=UNAUTHORIZED | NOT_FOUND | UNAVAILABLE | FORBIDDEN,
)
def save_settings(
    class_id: str,
    body: SaveSettingsRequest,
    account=Depends(require_instructor),
    ctx: AppContext = Depends(get_ctx),
):
    """Every field is optional; what is left out keeps its value. A change re-ranks every week."""
    snapshot = ctx.service.snapshot(class_id)
    current = ctx.store.get_settings(class_id)

    weights = current.weights
    if body.weights is not None:
        keys = [c.key for c in snapshot.criteria]
        unknown = [key for key in body.weights if key not in keys]
        if unknown:
            raise unprocessable(("body", "weights"), f"Unknown criterion: {', '.join(unknown)}", body.weights)
        if sum(body.weights.values()) == 0:
            raise unprocessable(("body", "weights"), "At least one weight must be above zero.", body.weights)
        # Criteria left out are stored as zero, so the saved map always covers every criterion.
        weights = normalise_weights({key: body.weights.get(key, 0.0) for key in keys})

    adjustment = current.adjustment
    if body.adjustment is not None:
        patch = body.adjustment.model_dump(exclude_none=True)
        merged = {
            "type_weights": {**adjustment.type_weights, **patch.pop("type_weights", {})},
            "rate": adjustment.rate, "cap": adjustment.cap, "flag_hours": adjustment.flag_hours,
        } | patch
        try:
            adjustment = validate_adjustment(StoredAdjustment(**merged))
        except InvalidHours as error:
            raise unprocessable(("body", "adjustment"), str(error), patch)

    saved = StoredSettings(weights=weights, adjustment=adjustment)
    ctx.store.save_settings(
        class_id, saved,
        LogEntry("", account.id, "settings_changed", None, None,
                 {"adjustment": _plain(current.adjustment)}, {"adjustment": _plain(adjustment)}, ctx.now()),
    )
    return settings_body(ctx, snapshot)


def _plain(adjustment: StoredAdjustment) -> dict:
    return {
        "type_weights": dict(adjustment.type_weights), "rate": adjustment.rate,
        "cap": adjustment.cap, "flag_hours": adjustment.flag_hours,
    }


@router.get(
    "/explainer",
    tags=["Class"],
    operation_id="getExplainer",
    summary="The scoring formula and its current parameters",
    description="The same for everyone; it holds no one's hours.",
    response_model=Explainer,
    responses=UNAUTHORIZED | NOT_FOUND,
)
def get_explainer(class_id: str, ctx: AppContext = Depends(get_ctx)):
    return build_explainer(ctx.store.get_settings(class_id).adjustment)
