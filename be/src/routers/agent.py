"""The living-agent control API: status, start/stop the scheduled loop, run a
cycle now, and trigger competitor discovery. Editor+ may run; start/stop is owner."""

from fastapi import APIRouter, Body, Depends

from src.controllers.agent import AGENT
from src.shared.deps import current_user, require_role
from src.shared.response import fail, ok

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("", dependencies=[Depends(current_user)])
def status():
    return ok(AGENT.status())


@router.post("/start", dependencies=[Depends(require_role("owner"))])
def start(payload: dict = Body(default={})):
    hours = payload.get("interval_hours")
    return ok(AGENT.start(interval_hours=hours, run_now=payload.get("run_now", True)))


@router.post("/stop", dependencies=[Depends(require_role("owner"))])
def stop():
    return ok(AGENT.stop())


@router.post("/run-once", dependencies=[Depends(require_role("owner"))])
def run_once():
    return ok(AGENT.run_once())


@router.post("/discover", dependencies=[Depends(require_role("owner"))])
def discover(payload: dict = Body(default={})):
    """Run competitor discovery immediately (Telegram search)."""
    from src.services.collection.discovery import discover_competitors
    try:
        return ok(discover_competitors(max_add=int(payload.get("max_add", 5))))
    except Exception as e:
        return fail(f"Discovery unavailable: {e}", status_code=503)


@router.post("/plan-day", dependencies=[Depends(require_role("owner"))])
def plan_day():
    """Build today's category × best-time plan now: scrape each category's fresh deals,
    draft a collection, and queue it at that category's peak-views hour (deduped)."""
    from src.services.generation.daily_planner import build_and_schedule_day
    from src.db.session import session_scope
    with session_scope() as s:
        r = build_and_schedule_day(s)
    return ok(r) if r.get("ok") else fail(r.get("reason", "could not build plan"), status_code=503)
