"""Read-only data endpoints (all require auth)."""

from datetime import date

from fastapi import APIRouter, Depends, Query

from src.controllers import service
from src.shared.channel import selected_channel_id
from src.shared.deps import current_user
from src.shared.response import fail, ok

router = APIRouter(prefix="/api", tags=["data"], dependencies=[Depends(current_user)])


@router.get("/overview")
def overview(channel_id: int | None = Depends(selected_channel_id)):
    return ok(service.overview(channel_id=channel_id))


@router.get("/insights")
def insights(channel_id: int | None = Depends(selected_channel_id)):
    return ok(service.insights(channel_id=channel_id))


@router.get("/analytics")
def analytics(start: str | None = Query(default=None), end: str | None = Query(default=None),
              channel_id: int | None = Depends(selected_channel_id)):
    try:
        return ok(service.analytics(start=start, end=end, channel_id=channel_id))
    except ValueError:
        return fail("start/end must be YYYY-MM-DD", 400)


@router.get("/data-range")
def data_range(channel_id: int | None = Depends(selected_channel_id)):
    return ok(service.data_range(channel_id=channel_id))


@router.get("/day")
def day(date_str: str | None = Query(default=None, alias="date"),
        channel_id: int | None = Depends(selected_channel_id)):
    if not date_str:
        return ok(service.day_summary(None, channel_id=channel_id))
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return fail("date must be YYYY-MM-DD", 400)
    return ok(service.day_summary(d, channel_id=channel_id))


@router.get("/drafts")
def drafts(page: int = 1, page_size: int = 12,
           channel_id: int | None = Depends(selected_channel_id)):
    return ok(service.drafts(page=page, page_size=page_size, channel_id=channel_id))


@router.get("/posts")
def posts(page: int = 1, page_size: int = 20,
          channel_id: int | None = Depends(selected_channel_id)):
    return ok(service.posts(page=page, page_size=page_size, channel_id=channel_id))


@router.get("/queue")
def queue(page: int = 1, page_size: int = 20,
          channel_id: int | None = Depends(selected_channel_id)):
    return ok(service.queue(page=page, page_size=page_size, channel_id=channel_id))


@router.get("/competitors")
def competitors():
    return ok(service.competitors())


@router.get("/merchants")
def merchants():
    return ok(service.merchants())


@router.get("/plans")
def plans(channel_id: int | None = Depends(selected_channel_id)):
    return ok(service.plans(channel_id=channel_id))


@router.get("/weekly")
def weekly(channel_id: int | None = Depends(selected_channel_id)):
    return ok(service.weekly_report(channel_id=channel_id))


@router.get("/comparison")
def comparison():
    return ok(service.comparison())
