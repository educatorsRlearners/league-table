import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.datasource import DataSource
from app.deps import AppContext, SessionStore
from app.errors import install_handlers
from app.identity import AccessCodeIdentity, IdentityProvider
from app.models import DemoAccount
from app.routers import auth, classes, commitments, data, ranking
from app.service import LeagueService
from app.store import AppStore, MemoryStore

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
FRONTEND_PAGE = "/League%20Table.dc.html"

DESCRIPTION = """\
The backend the League Table frontend expects. Scoring, the commitments adjustment, ranking
and tie-breaking run on the server; the browser only renders the result. The contract is
`openapi.yaml`.
"""


def create_app(
    db: DataSource | None = None,
    store: AppStore | None = None,
    clock: Callable[[], float] = time.time,
    identity: IdentityProvider | None = None,
    instructor_passcode: str | None = None,
    demo_accounts: list[DemoAccount] | None = None,
    frontend_dir: Path | None = FRONTEND_DIR,
) -> FastAPI:
    """Build the app. With no arguments it runs on the seeded demo class and an in-memory store.

    `db` is any DataSource and `store` any AppStore; `clock` returns epoch seconds. All three
    can be swapped in tests. The instructor passcode comes from `INSTRUCTOR_PASSCODE` unless
    given; only demo data has a default. The frontend in `frontend_dir` is served from the same
    origin as the API, so the session cookie works; pass None to serve the API alone.
    """
    if db is None:
        from app.toy_seed import build_toy

        today = datetime.fromtimestamp(clock(), tz=timezone.utc).date()
        toy = build_toy(today)
        db, store, demo_accounts = toy.db, toy.store, toy.demo_accounts
        instructor_passcode = instructor_passcode or toy.instructor_passcode
    store = store if store is not None else MemoryStore()
    if identity is None:
        passcode = instructor_passcode or os.environ.get("INSTRUCTOR_PASSCODE")
        if not passcode:
            raise RuntimeError("Set INSTRUCTOR_PASSCODE: the instructor signs in with it.")
        identity = AccessCodeIdentity(store, passcode)

    app = FastAPI(
        title="League Table API",
        version="0.2.0",
        description=DESCRIPTION,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.state.ctx = AppContext(
        db=db,
        store=store,
        service=LeagueService(db, clock),
        sessions=SessionStore(),
        identity=identity,
        clock=clock,
        demo_accounts=demo_accounts or [],
    )
    install_handlers(app)

    api = APIRouter(prefix="/api")
    for module in (auth, classes, ranking, commitments, data):
        api.include_router(module.router)
    api.include_router(commitments.me)
    app.include_router(api)

    if frontend_dir is not None:

        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse(FRONTEND_PAGE)

        # Mounted last so it never shadows an API route.
        app.mount("/", StaticFiles(directory=frontend_dir), name="frontend")
    return app
