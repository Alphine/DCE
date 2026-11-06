"""FastAPI application factory. All API routes live under /api; the frontend is mounted last at /."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agent.events import EventBus
from app.agent.inference_client import make_inference
from app.agent.planner import Planner
from app.agent.task_manager import TaskManager
from app.config import Settings, get_settings
from app.container import Services
from app.db import Db
from app.errors import AppError, install_error_handlers
from app.middleware import RequestContextMiddleware
from app.ratelimit import SlidingWindowLimiter
from app.routes import agent, artifacts, auth, datasets, governance

logger = logging.getLogger("dce.app")
LOGIN_LIMIT_PER_MINUTE = 10
AGENT_CREATE_MIN_INTERVAL_S = 30.0


def create_app(settings: Settings | None = None, *, runner: Any | None = None,
               inference: Any | None = None, min_agent_interval_s: float = AGENT_CREATE_MIN_INTERVAL_S) -> FastAPI:
    """Build the app. `runner` and `inference` may be injected (tests); otherwise they come from settings."""
    cfg = settings or get_settings()
    production = cfg.env == "production"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        db = Db(cfg.database_path)
        applied = db.migrate()
        logger.info("database ready; migrations applied now: %s", applied or "none")

        sandbox = runner
        if sandbox is None:
            from app.sandbox.factory import make_runner  # imported lazily: the sandbox package owns it

            sandbox = make_runner(cfg)
        client = inference or make_inference(cfg)
        bus = EventBus()
        planner = Planner(cfg, client)
        manager = TaskManager(settings=cfg, db=db, runner=sandbox, planner=planner, bus=bus,
                              min_interval_s=min_agent_interval_s)
        manager.bind_loop(asyncio.get_running_loop())
        recovered = manager.recover()
        if recovered:
            logger.warning("reconciled %d task(s) to ORPHANED on startup", recovered)
        await manager.sweep_sandbox()

        app.state.db = db
        app.state.services = Services(
            settings=cfg, db=db, bus=bus, planner=planner, manager=manager, runner=sandbox,
            login_limiter=SlidingWindowLimiter(LOGIN_LIMIT_PER_MINUTE, 60.0),
        )
        yield

    app = FastAPI(
        title="Disaster Commander Edge",
        version="1.6.0",
        lifespan=lifespan,
        docs_url=None if production else "/api/docs",
        openapi_url=None if production else "/api/openapi.json",
        redoc_url=None,
    )
    install_error_handlers(app)

    api = APIRouter(prefix="/api")
    api.include_router(governance.router)
    api.include_router(auth.router)
    api.include_router(datasets.router)
    api.include_router(agent.router)
    api.include_router(artifacts.router)

    @api.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def _unknown(rest: str) -> None:
        raise AppError("NOT_FOUND", "Unknown API route.")

    app.include_router(api)

    frontend_dir = Path(cfg.frontend_dir)
    if cfg.frontend_enabled and frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    elif cfg.frontend_enabled:
        logger.warning("frontend directory not found; static files are not served")

    origins = cfg.cors_origin_list
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                           allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.add_middleware(RequestContextMiddleware)
    return app


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


_configure_logging()
app = create_app()
