"""Read-only data endpoints (all require auth)."""

from datetime import date

from fastapi import APIRouter, Depends, Query

from src.controllers import service
from src.shared.deps import current_user
from src.shared.response import fail, ok

router = APIRouter(prefix="/api", tags=["data"], dependencies=[Depends(current_user)])


@router.get("/overview")
def overview():
    return ok(service.overview())


@router.get("/insights")
def insights(start: str | None = Query(default=None), end: str | None = Query(default=None)):
    try:
        return ok(service.insights(start=start, end=end))
    except ValueError:
        return fail("start/end must be YYYY-MM-DD", 400)


@router.get("/analytics")
def analytics(start: str | None = Query(default=None), end: str | None = Query(default=None)):
    try:
        return ok(service.analytics(start=start, end=end))
    except ValueError:
        return fail("start/end must be YYYY-MM-DD", 400)


@router.get("/data-range")
def data_range():
    return ok(service.data_range())


@router.get("/day")
def day(date_str: str | None = Query(default=None, alias="date")):
    if not date_str:
        return ok(service.day_summary(None))
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return fail("date must be YYYY-MM-DD", 400)
    return ok(service.day_summary(d))


@router.get("/drafts")
def drafts(page: int = 1, page_size: int = 12):
    return ok(service.drafts(page=page, page_size=page_size))


@router.get("/posts")
def posts(page: int = 1, page_size: int = 20):
    return ok(service.posts(page=page, page_size=page_size))


@router.get("/queue")
def queue(page: int = 1, page_size: int = 20):
    return ok(service.queue(page=page, page_size=page_size))


@router.get("/competitors")
def competitors():
    return ok(service.competitors())


@router.get("/competitor-dashboard")
def competitor_dashboard(window: int | None = Query(default=None, description="Window in days (7/30/90). Omit for all data.")):
    return ok(service.competitor_dashboard(window_days=window))


@router.get("/merchants")
def merchants():
    return ok(service.merchants())


@router.get("/plans")
def plans():
    return ok(service.plans())


@router.get("/weekly")
def weekly():
    return ok(service.weekly_report())


@router.get("/growth")
def growth():
    return ok(service.growth())
