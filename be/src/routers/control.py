"""Agent job control — status + run/stop the background pipeline/generation."""

from fastapi import APIRouter, Depends

from src.controllers.jobs import MANAGER
from src.shared.deps import current_user, require_role
from src.shared.response import ok

router = APIRouter(tags=["control"], dependencies=[Depends(current_user)])


@router.get("/api/job")
def job_status():
    return ok(MANAGER.status())


@router.post("/run/pipeline")
def run_pipeline(user: dict = Depends(require_role("editor"))):
    started = MANAGER.start("pipeline")
    return ok({"started": started, "busy": not started})


@router.post("/run/generate-live")
def run_generate_live(user: dict = Depends(require_role("editor"))):
    started = MANAGER.start("generate_live")
    return ok({"started": started, "busy": not started})


@router.post("/run/stop")
def stop_agent(user: dict = Depends(require_role("editor"))):
    stopped = MANAGER.request_stop()
    return ok({"stopping": stopped,
               "note": ("Stop requested; the agent halts after the current step."
                        if stopped else "No agent is currently running.")})
