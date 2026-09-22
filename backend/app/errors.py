import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.datasource import SourceUnavailable

logger = logging.getLogger(__name__)


class RefreshTooSoon(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Please wait {retry_after}s before refreshing again.")


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(SourceUnavailable)
    async def source_unavailable(request: Request, exc: SourceUnavailable):
        return JSONResponse(status_code=503, content={"message": "The data source did not respond."})

    @app.exception_handler(RefreshTooSoon)
    async def refresh_too_soon(request: Request, exc: RefreshTooSoon):
        return JSONResponse(
            status_code=429,
            content={"message": str(exc)},
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"message": str(exc.errors())})

    # Normalise all HTTP errors to {"message": ...} per openapi.yaml Error schema.
    @app.exception_handler(HTTPException)
    async def http_normaliser(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"message": detail},
                            headers=exc.headers or {})


    # Catch-all: every unexpected failure stays contract-consistent with the
    # documented Error schema instead of leaking FastAPI's default 500 body.
    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"message": "Something went wrong."})
