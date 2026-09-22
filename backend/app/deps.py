"""Shared context + helpers for routers."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from app.auth import Caller
from app.datasource import Snapshot
from app.service import LeagueService

_ctx = None


@dataclass
class AppContext:
    db: Any
    store: Any
    service: LeagueService
    clock: Callable[[], float]

    def source_info(self) -> dict:
        return {"kind": self.db.kind, "label": self.db.label,
                "demo": self.db.kind == "toy", "store": self.store.label}

    def now_ms(self) -> int:
        return int(self.clock() * 1000)


def get_ctx() -> AppContext:
    assert _ctx is not None, "app context not initialised"
    return _ctx


def set_ctx(ctx: AppContext) -> None:
    global _ctx
    _ctx = ctx


def need_class(ctx: AppContext, class_id: str) -> Snapshot:
    if not ctx.service.has_class(class_id):
        raise HTTPException(status_code=404, detail="Unknown class.")
    return ctx.service.snapshot(class_id)


def student_class_ids(ctx: AppContext, student_id: str) -> list[str]:
    out: list[str] = []
    try:
        classes = ctx.db.list_classes()
    except Exception:
        return out
    for c in classes:
        try:
            if any(s.id == student_id for s in ctx.db.list_students(c.id)):
                out.append(c.id)
        except Exception:
            continue
    return out


def ensure_student_in_class(ctx: AppContext, caller: Caller, class_id: str) -> None:
    if caller.role != "student":
        return
    if caller.classId == class_id:
        return
    # fall back to membership lookup (token class may be stale)
    if class_id in student_class_ids(ctx, caller.studentId or ""):
        return
    raise HTTPException(status_code=403, detail="That class is not yours to read.")


_weights_adapter = TypeAdapter(dict[str, float])


def parse_criteria(raw: str | list[str] | None) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        keys: list[str] = []
        for item in raw:
            keys.extend([k.strip() for k in str(item).split(",") if k.strip()])
        return keys or None
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return keys or None


def parse_weights(raw: str | dict | None) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="weights must be a JSON object.")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="weights must be a JSON object.")
    try:
        return _weights_adapter.validate_python(data)
    except ValidationError:
        raise HTTPException(status_code=422, detail="weights must map keys to non-negative numbers.")
