"""FastAPI app assembly + entry point.

Run: ``uvicorn src.main:app`` (from be/). Serves the JSON API (envelope
{success,data,error}), OpenAPI docs at /api/docs, and hosts the built fe/ SPA.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from src.config.settings import get_settings
from src.logger import get_logger
from src.middleware.errors import register_error_handlers
from src.routers import auth, channels, control, data, health, org, users

logger = get_logger(__name__)

# repo root: be/src/main.py -> parents[2]; the frontend build lives at repo/fe/dist
_DIST = Path(__file__).resolve().parents[2] / "fe" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # runs when the ASGI server (uvicorn) actually starts — NOT at import, so tests
    # that build the app without serving never trigger seeding or the schedulers.
    # 1) ensure the org + admin user exist (idempotent) so a fresh deploy can log in.
    try:
        from src.db.org_seed import seed_org
        from src.db.session import session_scope
        with session_scope() as s:
            seed_org(s)
    except Exception:
        logger.exception("[startup] org/admin seed skipped")
    # 2) auto-run the cron (leader-guarded) if enabled.
    if get_settings().schedulers_autostart:
        from src.controllers.schedulers import REGISTRY
        if REGISTRY.start_if_leader():   # cross-process lock: only one worker runs cron
            logger.info("[startup] schedulers auto-started (this worker is the cron leader)")
    yield
    try:
        from src.controllers.schedulers import REGISTRY
        REGISTRY.stop()
    except Exception:
        pass


def create_app() -> FastAPI:
    from src.db.session import init_db
    init_db()

    settings = get_settings()
    app = FastAPI(title="DealWing API", docs_url="/api/docs", redoc_url=None,
                  lifespan=_lifespan,
                  description="DealWing — Telegram deal-channel growth OS.")

    # CORS: exact origins from CORS_ORIGIN (comma-separated) PLUS any *.vercel.app
    # domain (so preview + prod deploys of the frontend work without reconfig).
    origins = [o.strip() for o in (settings.cors_origin or "").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )
    register_error_handlers(app)

    for r in (health, auth, control, data, channels, users, org):
        app.include_router(r.router)

    _mount_spa(app)
    return app


def _mount_spa(app: FastAPI) -> None:
    index = _DIST / "index.html"
    if not index.exists():
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def _no_build():
            return HTMLResponse(
                "<h1>DealWing</h1><p>Frontend not built. Run "
                "<code>cd fe &amp;&amp; npm install &amp;&amp; npm run build</code>, then reload. "
                "API docs at <a href='/api/docs'>/api/docs</a>.</p>")
        return

    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "run/")):
            return JSONResponse({"success": False, "data": None,
                                 "error": {"message": "Not found", "code": 404}}, status_code=404)
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            from fastapi.responses import FileResponse
            return FileResponse(candidate)
        return HTMLResponse(index.read_text(encoding="utf-8"))


app = create_app()


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    logger.info("DealWing on http://%s:%d  · API docs at /api/docs", host, port)
    uvicorn.run("src.main:app", host=host, port=port, log_level="warning")
