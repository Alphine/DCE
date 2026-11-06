"""Planner: asks the inference client for a plan and code, then validates everything (SDD 8.5, 20.3)."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.inference_client import InferenceClient, InferenceError, PlanRequest, check_script
from app.agent.schemas import Plan, PlanError, validate_plan
from app.config import Settings

logger = logging.getLogger("dce.planner")


class PlanningFailed(Exception):
    """Planning or code generation failed. `code` is the machine-readable error_reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Planner:
    def __init__(self, settings: Settings, client: InferenceClient) -> None:
        self._client = client
        self._ceiling = {
            "timeout_s": settings.sandbox_timeout_s,
            "memory_mb": settings.sandbox_memory_mb,
            "pids": settings.sandbox_pids,
        }

    @property
    def model_id(self) -> str:
        return self._client.model_id

    async def create_plan(self, *, instruction: str, requested_outputs: list[str],
                          dataset_name: str, profile: dict[str, Any]) -> Plan:
        request = PlanRequest(instruction=instruction, requested_outputs=requested_outputs,
                              dataset_name=dataset_name, profile=profile, limits=dict(self._ceiling))
        try:
            raw = await self._client.plan(request)
            return validate_plan(raw, self._ceiling)
        except InferenceError as exc:
            logger.warning("planning failed code=%s", exc.code)
            raise PlanningFailed(exc.code) from exc
        except PlanError as exc:
            logger.warning("plan rejected code=%s", exc.code)
            raise PlanningFailed(exc.code) from exc

    async def create_script(self, plan: Plan, profile: dict[str, Any]) -> str:
        """Generate task.py after gate A. The script is checked before it can reach the sandbox."""
        try:
            script = await self._client.generate_code(plan.model_dump(mode="json"), profile)
            check_script(script)
        except InferenceError as exc:
            logger.warning("code generation failed code=%s", exc.code)
            raise PlanningFailed(exc.code) from exc
        return script
