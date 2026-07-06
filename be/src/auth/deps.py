"""FastAPI auth dependencies.

``current_user`` reads a Bearer token, verifies it, and returns the User row (401 on
failure). ``require_role(...)`` builds a dependency that also enforces a minimum role.
Kept import-light so the module loads even if FastAPI isn't the caller.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from src.auth.tokens import verify_token
from src.db.models_org import User
from src.db.session import session_scope

_ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def current_user(authorization: str | None = Header(default=None)) -> dict:
    """Return the authenticated user as a plain dict, or raise 401."""
    uid = verify_token(_extract_bearer(authorization))
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    with session_scope() as s:
        u = s.get(User, uid)
        if u is None:
            raise HTTPException(status_code=401, detail="User no longer exists")
        return {"id": u.id, "org_id": u.org_id, "name": u.name, "email": u.email,
                "role": u.role}


def require_role(min_role: str):
    """Dependency factory enforcing a minimum role (viewer < editor < owner)."""
    needed = _ROLE_RANK.get(min_role, 0)

    def _dep(user: dict = Depends(current_user)) -> dict:
        if _ROLE_RANK.get(user.get("role"), 0) < needed:
            raise HTTPException(status_code=403, detail=f"Requires {min_role} role")
        return user

    return _dep
