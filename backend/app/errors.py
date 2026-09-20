from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.datasource import SourceUnavailable


class RefreshTooSoon(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Please wait {retry_after}s before refreshing again.")


def unprocessable(loc: tuple[str, ...], message: str, value=None) -> RequestValidationError:
    """A 422 in FastAPI's own shape, for problems that need data to detect."""
    return RequestValidationError(
        [{"type": "value_error", "loc": loc, "msg": message, "input": value}]
    )


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(SourceUnavailable)
    async def source_unavailable(request: Request, exc: SourceUnavailable):
        return JSONResponse(status_code=503, content={"detail": "The data source did not respond."})

    @app.exception_handler(RefreshTooSoon)
    async def refresh_too_soon(request: Request, exc: RefreshTooSoon):
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc)},
            headers={"Retry-After": str(exc.retry_after)},
        )
