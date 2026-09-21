"""Shared FastAPI dependencies: the app context, the signed-in account and role checks."""

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import APIKeyCookie

from app.commitments import Adjuster, CommitmentBook, current_week
from app.datasource import DataSource, Snapshot
from app.identity import IdentityProvider
from app.models import DemoAccount, SourceInfo
from app.service import LeagueService
from app.store import AppStore, StoredAccount

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
    store: AppStore
    service: LeagueService
    sessions: SessionStore
    identity: IdentityProvider
    clock: Callable[[], float]
    demo_accounts: list[DemoAccount] = field(default_factory=list)

    def source_info(self) -> SourceInfo:
        return SourceInfo(kind=self.db.kind, label=self.db.label, demo=self.db.kind == "toy")

    def now(self) -> str:
        """The server clock as an ISO 8601 UTC string, for stamping stored changes."""
        return datetime.fromtimestamp(self.clock(), tz=timezone.utc).isoformat()

    def today(self) -> date:
        return datetime.fromtimestamp(self.clock(), tz=timezone.utc).date()

    def adjuster(self, class_id: str) -> Adjuster:
        """The adjustment as currently set and approved, read fresh so an edit shows at once."""
        settings = self.store.get_settings(class_id)
        book = CommitmentBook(self.store.list_baselines(), self.store.list_weekly_updates())
        return Adjuster(settings.adjustment, book)

    def class_id_of(self, student_id: str) -> str | None:
        for cls in self.db.list_classes():
            if any(s.id == student_id for s in self.service.snapshot(cls.id).students):
                return cls.id
        return None

    def current_week_of(self, snapshot: Snapshot):
        return current_week(snapshot.weeks, self.today())


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def current_account(
    token: str | None = Depends(session_cookie), ctx: AppContext = Depends(get_ctx)
) -> StoredAccount:
    account_id = ctx.sessions.account_id(token)
    account = ctx.store.get_account(account_id) if account_id else None
    if account is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return account


def require_instructor(account: StoredAccount = Depends(current_account)) -> StoredAccount:
    if account.role != "instructor":
        raise HTTPException(status_code=403, detail="Only the instructor can do this.")
    return account


def require_student(account: StoredAccount = Depends(current_account)) -> StoredAccount:
    if account.role != "student" or account.student_id is None:
        raise HTTPException(status_code=403, detail="Only a student can do this.")
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
