from fastapi import APIRouter, Body, Depends

from src.controllers import accounts
from src.shared.deps import current_user, require_role
from src.shared.response import fail, ok

router = APIRouter(prefix="/api/org", tags=["org"])


@router.get("", dependencies=[Depends(current_user)])
def get_org(user: dict = Depends(current_user)):
    return ok(accounts.get_org(user["org_id"]))


@router.patch("", dependencies=[Depends(require_role("owner"))])
def update_org(payload: dict = Body(...), user: dict = Depends(current_user)):
    res = accounts.update_org(user["org_id"], name=payload.get("name"),
                              affiliate_provider=payload.get("affiliate_provider"),
                              settings=payload.get("settings"))
    return ok(res) if res.get("ok") else fail(res.get("error", "error"), 400)
