"""Application services wired at startup and stored on app.state.services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.agent.events import EventBus
from app.agent.planner import Planner
from app.agent.task_manager import TaskManager
from app.config import Settings
from app.db import Db
from app.ratelimit import SlidingWindowLimiter


@dataclass
class Services:
    settings: Settings
    db: Db
    bus: EventBus
    planner: Planner
    manager: TaskManager
    runner: Any
    login_limiter: SlidingWindowLimiter


def services_of(request: Request) -> Services:
    return request.app.state.services
