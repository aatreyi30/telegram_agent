from fastapi import APIRouter

from src.shared.response import ok

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    return ok({"status": "ok", "message": "Hello from DealWing backend! 👋"})
