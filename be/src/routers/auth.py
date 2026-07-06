from fastapi import APIRouter, Body, Depends

from src.controllers import accounts
from src.shared.deps import current_user
from src.shared.response import fail, ok

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: dict = Body(...)):
    res = accounts.login(payload.get("email", ""), payload.get("password", ""))
    if res is None:
        return fail("Invalid email or password.", status_code=401)
    return ok(res)


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return ok(user)


@router.post("/change-password")
def change_password(payload: dict = Body(...), user: dict = Depends(current_user)):
    res = accounts.change_password(user["id"], payload.get("old_password", ""),
                                   payload.get("new_password", ""))
    return ok(res) if res.get("ok") else fail(res.get("error", "error"), 400)
