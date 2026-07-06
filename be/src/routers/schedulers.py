"""Scheduler control API — status of all 20 jobs, start/stop the registry, run one
job on demand, and recent run logs. Start/stop + run are owner-only."""

from fastapi import APIRouter, Depends

from src.controllers.schedulers import REGISTRY
from src.shared.deps import current_user, require_role
from src.shared.response import fail, ok

router = APIRouter(prefix="/api/schedulers", tags=["schedulers"])


@router.get("", dependencies=[Depends(current_user)])
def status():
    return ok(REGISTRY.status())


@router.get("/logs", dependencies=[Depends(current_user)])
def logs(limit: int = 40):
    return ok(REGISTRY.recent_logs(limit=limit))


@router.post("/start", dependencies=[Depends(require_role("owner"))])
def start():
    # leader-guarded so it won't double-run the cron under multiple workers
    if not REGISTRY.start_if_leader():
        return ok({**REGISTRY.status(), "note": "cron is already running on another worker"})
    return ok(REGISTRY.status())


@router.post("/stop", dependencies=[Depends(require_role("owner"))])
def stop():
    return ok(REGISTRY.stop())


@router.post("/run/{key}", dependencies=[Depends(require_role("owner"))])
def run_one(key: str):
    if key not in {j["key"] for j in REGISTRY.status()["jobs"]}:
        return fail(f"Unknown scheduler '{key}'.", status_code=404)
    REGISTRY.run_async(key)
    return ok({"started": True, "key": key})
