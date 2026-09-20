"""Shared FastAPI dependencies: the app context, the signed-in account and role checks."""

import secrets
from dataclasses import dataclass
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import APIKeyCookie

from app.datasource import DataSource
from app.mock_db import InMemorySettings, MockAccount
from app.models import SourceInfo
from app.service import LeagueService

SESSION_COOKIE = "session"

session_cookie = APIKeyCookie(name=SESSION_COOKIE, scheme_name="sessionCookie", auto_error=False)


class SessionStore:
    """Server-side sessions: an opaque random token mapped to an account id."""

    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}

    def create(self, account_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = account_id
        return token

    def account_id(self, token: str | None) -> str | None:
        return self._sessions.get(token) if token else None

    def destroy(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)


@dataclass
class AppContext:
    db: DataSource
    settings: InMemorySettings
    service: LeagueService
    sessions: SessionStore
    verify_google_token: Callable[[str], str | None]

    def accounts(self) -> list[MockAccount]:
        return getattr(self.db, "list_accounts", lambda: [])()

    def source_info(self) -> SourceInfo:
        return SourceInfo(kind=self.db.kind, label=self.db.label, demo=self.db.kind == "toy")


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def current_account(
    token: str | None = Depends(session_cookie), ctx: AppContext = Depends(get_ctx)
) -> MockAccount:
    account_id = ctx.sessions.account_id(token)
    account = next((a for a in ctx.accounts() if a.id == account_id), None)
    if account is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return account


def require_teacher(account: MockAccount = Depends(current_account)) -> MockAccount:
    if account.role != "teacher":
        raise HTTPException(status_code=403, detail="Only a teacher can do this.")
    return account


def class_router() -> APIRouter:
    """A router under /classes/{class_id} that needs a session and an existing class."""
    return APIRouter(
        prefix="/classes/{class_id}", dependencies=[Depends(current_account), Depends(valid_class)]
    )


def valid_class(class_id: str, ctx: AppContext = Depends(get_ctx)) -> str:
    if not ctx.service.has_class(class_id):
        raise HTTPException(status_code=404, detail="Unknown class.")
    return class_id
