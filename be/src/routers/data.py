"""Data + draft-management endpoints (all require auth)."""

from datetime import date

from fastapi import APIRouter, Body, Depends, Query

from src.controllers import service
from src.shared.deps import current_user, require_role
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
def day(date_str: str | None = Query(default=None, alias="date"),
        end_str: str | None = Query(default=None, alias="end")):
    if not date_str:
        return ok(service.day_summary(None))
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return fail("date must be YYYY-MM-DD", 400)
    e = None
    if end_str:
        try:
            e = date.fromisoformat(end_str)
        except ValueError:
            return fail("end must be YYYY-MM-DD", 400)
    return ok(service.day_summary(d, e))


@router.get("/drafts")
def drafts(page: int = 1, page_size: int = 12):
    return ok(service.drafts(page=page, page_size=page_size))


@router.post("/drafts")
def create_draft(user: dict = Depends(require_role("editor")),
                 text: str = Body(..., embed=True),
                 post_type: str = Body("manual", embed=True),
                 selection_bucket: str | None = Body(None, embed=True),
                 channel_ref: str | None = Body(None, embed=True)):
    result = service.create_draft(text=text, post_type=post_type,
                                  selection_bucket=selection_bucket,
                                  channel_ref=channel_ref)
    return ok(result)


@router.put("/drafts/{draft_id}")
def update_draft(draft_id: int, user: dict = Depends(require_role("editor")),
                 text: str | None = Body(None, embed=True),
                 post_type: str | None = Body(None, embed=True),
                 status: str | None = Body(None, embed=True),
                 selection_bucket: str | None = Body(None, embed=True),
                 channel_ref: str | None = Body(None, embed=True)):
    result = service.update_draft(draft_id, text=text, post_type=post_type,
                                  status=status, selection_bucket=selection_bucket,
                                  channel_ref=channel_ref)
    if not result.get("ok"):
        return fail(result.get("error", "Draft not found"), 404)
    return ok(result)


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: int, user: dict = Depends(require_role("editor"))):
    result = service.delete_draft(draft_id)
    if not result.get("ok"):
        return fail(result.get("error", "Draft not found"), 404)
    return ok(result)


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


@router.get("/plan/daily")
def plan_daily(date: str | None = None):
    return ok(service.daily_brief(date=date))


@router.get("/plan/weekly")
def plan_weekly(end: str | None = None):
    return ok(service.weekly_brief(end=end))


@router.get("/weekly")
def weekly():
    return ok(service.weekly_report())


@router.get("/growth")
def growth(start: str | None = Query(default=None), end: str | None = Query(default=None)):
    try:
        return ok(service.growth(start=start, end=end))
    except ValueError:
        return fail("start/end must be YYYY-MM-DD", 400)


@router.get("/digest")
def digest():
    return ok(service.digest())
