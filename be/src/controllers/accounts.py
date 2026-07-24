"""Account data logic — login, users CRUD, org settings.

Separate from service.py (read-only view models) because this reads/writes the
Organization + User tables and touches auth. All password handling goes through
src.auth.security; tokens through src.auth.tokens.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from src.auth.security import hash_password, verify_password
from src.auth.tokens import issue_token
from src.db.models import Channel
from src.db.models_org import Organization, User, UserRole
from src.db.session import session_scope

_VALID_ROLES = {UserRole.OWNER, UserRole.EDITOR, UserRole.VIEWER}


def _user_dict(u: User) -> dict:
    return {"id": u.id, "org_id": u.org_id, "name": u.name, "email": u.email,
            "role": u.role, "has_password": bool(u.password_hash),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None}


# ------------------------- auth ------------------------- #
def login(email: str, password: str) -> dict | None:
    """Return {token, user} on success, else None."""
    with session_scope() as s:
        u = s.scalar(select(User).where(func.lower(User.email) == (email or "").lower()))
        if u is None or not verify_password(password, u.password_hash):
            return None
        u.last_login_at = datetime.now(timezone.utc)
        token = issue_token(u.id)
        return {"token": token, "user": _user_dict(u)}


def change_password(user_id: int, old_password: str, new_password: str) -> dict:
    if not new_password or len(new_password) < 6:
        return {"ok": False, "error": "New password must be at least 6 characters."}
    with session_scope() as s:
        u = s.get(User, user_id)
        if u is None:
            return {"ok": False, "error": "User not found."}
        if not verify_password(old_password, u.password_hash):
            return {"ok": False, "error": "Current password is incorrect."}
        u.password_hash = hash_password(new_password)
        return {"ok": True}


# ------------------------- users ------------------------- #
def list_users(org_id: int) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(User).where(User.org_id == org_id).order_by(User.id)).all()
        return [_user_dict(u) for u in rows]


def create_user(org_id: int, name: str, email: str, password: str, role: str) -> dict:
    if role not in _VALID_ROLES:
        return {"ok": False, "error": f"Invalid role '{role}'."}
    if not email or not password or len(password) < 6:
        return {"ok": False, "error": "Email and a password (6+ chars) are required."}
    with session_scope() as s:
        exists = s.scalar(select(User).where(User.org_id == org_id,
                                             func.lower(User.email) == email.lower()))
        if exists:
            return {"ok": False, "error": "A user with that email already exists."}
        u = User(org_id=org_id, name=name or email, email=email, role=role,
                 password_hash=hash_password(password))
        s.add(u)
        s.flush()
        return {"ok": True, "user": _user_dict(u)}


def update_user(user_id: int, *, role: str | None = None, password: str | None = None,
                name: str | None = None) -> dict:
    if role is not None and role not in _VALID_ROLES:
        return {"ok": False, "error": f"Invalid role '{role}'."}
    with session_scope() as s:
        u = s.get(User, user_id)
        if u is None:
            return {"ok": False, "error": "User not found."}
        if role is not None:
            u.role = role
        if name is not None:
            u.name = name
        if password:
            if len(password) < 6:
                return {"ok": False, "error": "Password must be at least 6 characters."}
            u.password_hash = hash_password(password)
        return {"ok": True, "user": _user_dict(u)}


def delete_user(user_id: int, acting_user_id: int) -> dict:
    with session_scope() as s:
        u = s.get(User, user_id)
        if u is None:
            return {"ok": False, "error": "User not found."}
        if u.id == acting_user_id:
            return {"ok": False, "error": "You cannot delete your own account."}
        if u.role == UserRole.OWNER:
            owners = s.scalar(select(func.count()).select_from(User)
                              .where(User.org_id == u.org_id, User.role == UserRole.OWNER))
            if owners <= 1:
                return {"ok": False, "error": "Cannot delete the last owner."}
        s.delete(u)
        return {"ok": True}


# ------------------------- org ------------------------- #
def get_org(org_id: int) -> dict:
    with session_scope() as s:
        o = s.get(Organization, org_id)
        if o is None:
            return {}
        n_ch = s.scalar(select(func.count()).select_from(Channel).where(Channel.org_id == org_id))
        return {"id": o.id, "key": o.key, "name": o.name,
                "affiliate_provider": o.affiliate_provider, "settings": o.settings or {},
                "channels": n_ch}


_EDITABLE_SETTINGS = {"grabon_shortener_url", "grabon_amazon_tag", "grabon_flipkart_params",
                      "grabon_myntra_deeplink", "grabon_shorten_all", "preferred_categories",
                      "auto_discover_competitors", "post_templates"}


def update_org(org_id: int, *, name: str | None = None, affiliate_provider: str | None = None,
               settings: dict | None = None) -> dict:
    with session_scope() as s:
        o = s.get(Organization, org_id)
        if o is None:
            return {"ok": False, "error": "Org not found."}
        if name is not None:
            o.name = name
        if affiliate_provider is not None:
            o.affiliate_provider = affiliate_provider
        if settings:
            merged = dict(o.settings or {})
            for k in _EDITABLE_SETTINGS:
                if k in settings:
                    # post_templates is a dict of individual templates: merge the
                    # incoming sub-keys over the existing ones so a partial update
                    # (e.g. editing one template) never wipes the others.
                    if k == "post_templates" and isinstance(settings[k], dict):
                        existing = merged.get(k)
                        base = dict(existing) if isinstance(existing, dict) else {}
                        base.update(settings[k])
                        merged[k] = base
                    else:
                        merged[k] = settings[k]
            if affiliate_provider is not None:
                merged["affiliate_provider"] = affiliate_provider
            o.settings = merged
        return {"ok": True, "org": {"id": o.id, "name": o.name,
                                    "affiliate_provider": o.affiliate_provider,
                                    "settings": o.settings}}
