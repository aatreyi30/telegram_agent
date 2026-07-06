from fastapi import APIRouter, Body, Depends, Query

from src.controllers import service
from src.shared.deps import current_user, require_role
from src.shared.response import fail, ok

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.get("")
def list_channels(user: dict = Depends(current_user)):
    return ok(service.list_channels(org_id=user.get("org_id")))


@router.post("")
def add_channel(user: dict = Depends(require_role("editor")),
                username: str = Body(..., embed=True),
                kind: str = Body("owned", embed=True)):
    result = service.add_channel(user.get("org_id"), username, kind=kind)
    if result.get("ok"):
        return ok(result["channel"])
    return fail(result.get("error", "Could not add channel."), status_code=400)


@router.delete("/{channel_id}")
def delete_channel(channel_id: int, confirm: bool = Query(default=False),
                   user: dict = Depends(require_role("owner"))):
    result = service.delete_channel(channel_id, confirm=confirm, org_id=user.get("org_id"))
    if result.get("ok"):
        return ok(result)
    if result.get("requires_confirm"):
        return fail(result.get("note", "Confirmation required."), status_code=409,
                    details=result.get("would_delete"))
    return fail(result.get("error", "Not found."), status_code=404)
