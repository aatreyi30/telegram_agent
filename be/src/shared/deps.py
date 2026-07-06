"""Shared FastAPI dependencies (auth) — re-exported from the auth package so
routers import them from one place (`src.shared.deps`)."""

from src.auth.deps import current_user, require_role

__all__ = ["current_user", "require_role"]
