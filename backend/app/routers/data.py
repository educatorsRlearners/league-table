from fastapi import Depends

from app.deps import AppContext, class_router, get_ctx, require_teacher
from app.models import Error, RefreshResult, Status
from app.routers.classes import NOT_FOUND, UNAUTHORIZED, UNAVAILABLE, utc

router = class_router()


@router.get(
    "/status",
    tags=["Data"],
    operation_id="getStatus",
    summary="Data freshness and validation issues",
    response_model=Status,
    responses=UNAUTHORIZED | NOT_FOUND,
)
def get_status(class_id: str, ctx: AppContext = Depends(get_ctx)):
    """Read from the cache; never triggers a fetch from the data source."""
    snapshot = ctx.service.cached(class_id)
    return Status(
        last_updated=utc(snapshot.at) if snapshot else None,
        stale=snapshot.stale if snapshot else False,
        issues=snapshot.issues if snapshot else [],
        source=ctx.source_info(),
    )


@router.post(
    "/refresh",
    tags=["Data"],
    operation_id="refresh",
    summary="Re-read the data source now (teacher only)",
    response_model=RefreshResult,
    dependencies=[Depends(require_teacher)],
    responses=UNAUTHORIZED
    | NOT_FOUND
    | UNAVAILABLE
    | {
        403: {"model": Error, "description": "The caller's role does not allow this."},
        429: {"model": Error, "description": "Refreshed too recently."},
    },
)
def refresh(class_id: str, ctx: AppContext = Depends(get_ctx)):
    """Bypasses the cache. Limited to one call per 10 seconds; if the source fails
    but a snapshot exists, succeeds with `stale: true`."""
    snapshot = ctx.service.refresh(class_id)
    return RefreshResult(last_updated=utc(snapshot.at), issues=snapshot.issues, stale=snapshot.stale)
