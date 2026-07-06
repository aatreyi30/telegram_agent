from fastapi import APIRouter, Depends, Query

from src.controllers import service
from src.shared.deps import current_user, require_role
from src.shared.response import fail, ok

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.get("", dependencies=[Depends(current_user)])
def list_channels():
    return ok(service.list_channels())


@router.delete("/{channel_id}", dependencies=[Depends(require_role("owner"))])
def delete_channel(channel_id: int, confirm: bool = Query(default=False)):
    result = service.delete_channel(channel_id, confirm=confirm)
    if result.get("ok"):
        return ok(result)
    if result.get("requires_confirm"):
        return fail(result.get("note", "Confirmation required."), status_code=409,
                    details=result.get("would_delete"))
    return fail(result.get("error", "Not found."), status_code=404)
