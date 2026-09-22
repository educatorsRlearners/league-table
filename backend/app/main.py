import time
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.deps import AppContext, set_ctx
from app.errors import install_handlers
from app.routers import classes, data, ranking, risk
from app.service import LeagueService
from app.store import MemoryStore

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
FRONTEND_PAGE = "/League%20Table.dc.html"

DESCRIPTION = """\
Backend contract derived exclusively from the frontend API client
(`frontend/services/api.js`, `mockSource.js`, `scoring.js`, `risk.js`,
`tests.js`, and callers in `frontend/League Table.dc.html`).
"""


def create_app(
    db=None,
    store=None,
    clock: Callable[[], float] = time.time,
    frontend_dir: Path | None = FRONTEND_DIR,
) -> FastAPI:
    if db is None or store is None:
        from app.toy_seed import build_toy

        toy = build_toy()
        db = db or toy.db
        if store is None:
            store = MemoryStore(class_ids=[c.id for c in toy.db.classes], seed=toy.seed)
    app = FastAPI(
        title="League Table Backend (as expected by frontend/services/api.js)",
        version="1.0.0",
        description=DESCRIPTION,
        servers=[{"url": "http://localhost:8000"}],
    )
    ctx = AppContext(db=db, store=store, service=LeagueService(db, store, clock), clock=clock)
    set_ctx(ctx)
    app.state.ctx = ctx
    install_handlers(app)

    for module in (classes, ranking, risk, data):
        app.include_router(module.router)

    # Align the served OpenAPI with openapi.yaml: global Bearer auth.
    def _openapi():
        if app.openapi_schema:
            return app.openapi_schema
        from fastapi.openapi.utils import get_openapi

        schema = get_openapi(title=app.title, version=app.version,
                             description=app.description, routes=app.routes, servers=[{"url": "http://localhost:8000"}])
        schema["security"] = [{"bearerAuth": []}]
        schema["components"].setdefault("securitySchemes", {})["bearerAuth"] = {
            "type": "http", "scheme": "bearer", "bearerFormat": "JWT",
            "description": "JWT identifying the caller. Server derives role, studentId and class membership.",
        }
        app.openapi_schema = schema
        return schema

    app.openapi = _openapi  # type: ignore[method-assign]

    if frontend_dir is not None and Path(frontend_dir).exists():
        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse(FRONTEND_PAGE)

        app.mount("/", StaticFiles(directory=frontend_dir), name="frontend")
    return app
