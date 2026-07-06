"""Exception handlers that render errors in the { success, data, error } envelope."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.shared.response import error_body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(_request, exc: StarletteHTTPException):
        return JSONResponse(error_body(str(exc.detail), code=exc.status_code),
                            status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(_request, exc: RequestValidationError):
        return JSONResponse(error_body("Validation error", code=422, details=exc.errors()),
                            status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_request, exc: Exception):  # never leak a traceback
        return JSONResponse(error_body("Internal server error", code=500), status_code=500)
