"""Standard JSON response envelope: { success, data, error }.

Every API response uses this shape (template contract). Success -> data populated,
error null; failure -> data null, error populated. Routers return ``ok(data)``;
failures return ``fail(...)`` (a JSONResponse with the right status code); and the
middleware wraps uncaught HTTPExceptions/validation errors in the same shape.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None) -> dict:
    return {"success": True, "data": data, "error": None}


def error_body(message: str, code: Any = None, details: Any = None) -> dict:
    err: dict = {"message": message}
    if code is not None:
        err["code"] = code
    if details is not None:
        err["details"] = details
    return {"success": False, "data": None, "error": err}


def fail(message: str, status_code: int = 400, code: Any = None, details: Any = None) -> JSONResponse:
    return JSONResponse(error_body(message, code=code, details=details), status_code=status_code)
