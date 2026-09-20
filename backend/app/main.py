import time
from typing import Callable

from fastapi import APIRouter, FastAPI

from app.datasource import DataSource
from app.deps import AppContext, SessionStore
from app.errors import install_handlers
from app.mock_db import InMemorySettings, MockDatabase
from app.routers import auth, classes, data, ranking
from app.service import LeagueService

DESCRIPTION = """\
The backend the League Table frontend expects. Scoring, ranking and tie-breaking run
on the server; the browser only renders the result. The contract is `openapi.yaml`.
"""


def create_app(
    db: DataSource | None = None,
    settings: InMemorySettings | None = None,
    clock: Callable[[], float] = time.time,
    verify_google_token: Callable[[str], str | None] = auth.mock_verify_google_token,
) -> FastAPI:
    """Build the app. With no arguments it runs on the seeded mock database.

    `db` is any DataSource, `clock` returns epoch seconds; both can be swapped in tests.
    """
    db = db if db is not None else MockDatabase.toy()

    app = FastAPI(
        title="League Table API",
        version="0.1.0",
        description=DESCRIPTION,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.state.ctx = AppContext(
        db=db,
        settings=settings if settings is not None else InMemorySettings(),
        service=LeagueService(db, clock),
        sessions=SessionStore(),
        verify_google_token=verify_google_token,
    )
    install_handlers(app)

    api = APIRouter(prefix="/api")
    for module in (auth, classes, ranking, data):
        api.include_router(module.router)
    app.include_router(api)
    return app
