from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.datasource import SourceUnavailable


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
