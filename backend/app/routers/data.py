"""Cache status + refresh. Tag: cache."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import Caller, get_caller
from app.deps import get_ctx, need_class
from app.models import RefreshResult, StatusResult

router = APIRouter(tags=["cache"])


@router.post("/classes/{classId}/refresh", response_model=RefreshResult, tags=["cache"],
             responses={401: {}, 429: {}, 503: {}})
def refresh(classId: str, caller: Caller = Depends(get_caller), ctx=Depends(get_ctx)):
    need_class(ctx, classId)
    snap = ctx.service.refresh(classId)
    return {"lastUpdated": int(snap.at * 1000),
            "issues": [i.model_dump() for i in snap.issues], "stale": snap.stale}


@router.get("/classes/{classId}/status", response_model=StatusResult, tags=["cache"],
            responses={401: {}})
def get_status(classId: str, caller: Caller = Depends(get_caller), ctx=Depends(get_ctx)):
    snap = ctx.service.cached(classId)
    return {"lastUpdated": int(snap.at * 1000) if snap else None,
            "stale": bool(snap.stale) if snap else False,
            "issues": [i.model_dump() for i in snap.issues] if snap else [],
            "source": ctx.source_info()}
