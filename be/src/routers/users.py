from fastapi import APIRouter, Body, Depends

from src.controllers import accounts
from src.shared.deps import current_user, require_role
from src.shared.response import fail, ok

router = APIRouter(prefix="/api/users", tags=["users"],
                   dependencies=[Depends(require_role("owner"))])


@router.get("")
def list_users(user: dict = Depends(current_user)):
    return ok(accounts.list_users(user["org_id"]))


@router.post("")
def create_user(payload: dict = Body(...), user: dict = Depends(current_user)):
    res = accounts.create_user(user["org_id"], payload.get("name", ""), payload.get("email", ""),
                               payload.get("password", ""), payload.get("role", "viewer"))
    return ok(res) if res.get("ok") else fail(res.get("error", "error"), 400)


@router.patch("/{user_id}")
def update_user(user_id: int, payload: dict = Body(...)):
    res = accounts.update_user(user_id, role=payload.get("role"),
                               password=payload.get("password"), name=payload.get("name"))
    return ok(res) if res.get("ok") else fail(res.get("error", "error"), 400)


@router.delete("/{user_id}")
def delete_user(user_id: int, user: dict = Depends(current_user)):
    res = accounts.delete_user(user_id, acting_user_id=user["id"])
    return ok(res) if res.get("ok") else fail(res.get("error", "error"), 400)
