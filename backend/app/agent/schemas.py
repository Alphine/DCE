"""Strict plan schema and validation (docs/api.md section 3, SDD 8.5). Unknown fields are rejected."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.agent.tools import TOOL_REGISTRY


class PlanError(Exception):
    """Validation failure with a machine-readable reason code (stored as task error_reason)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^s[0-9]{1,2}$")
    description: str = Field(min_length=1, max_length=200)
    tool: str = Field(min_length=1, max_length=64)


class PlanLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_s: int = Field(ge=1, le=600)
    memory_mb: int = Field(ge=16, le=4096)
    pids: int = Field(ge=1, le=512)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tools: list[str] = Field(min_length=1, max_length=8)
    steps: list[PlanStep] = Field(min_length=1, max_length=16)
    limits: PlanLimits
    expected_outputs: list[str] = Field(min_length=1, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    data_class: Literal["SIMULATED_FACT"]

    @field_validator("assumptions")
    @classmethod
    def _assumption_length(cls, items: list[str]) -> list[str]:
        if any(len(text) > 300 for text in items):
            raise ValueError("assumption too long")
        return items


def validate_plan(raw: Any, ceiling: dict[str, int]) -> Plan:
    """Validate a planner output against the schema, the tool registry, and the limit ceiling.

    Limits may be lowered by the planner, never raised above the configured ceiling (SDD 8.5).
    """
    if not isinstance(raw, dict):
        raise PlanError("PLAN_INVALID_SCHEMA", "Plan must be a JSON object.")
    try:
        plan = Plan.model_validate(raw)
    except ValidationError as exc:
        raise PlanError("PLAN_INVALID_SCHEMA", f"Plan failed schema validation ({len(exc.errors())} errors).") from exc

    for tool in plan.tools:
        if tool not in TOOL_REGISTRY:
            raise PlanError("PLAN_UNKNOWN_TOOL", f"Tool is not in the registry: {tool[:64]}")
    step_ids: set[str] = set()
    for step in plan.steps:
        if step.tool not in plan.tools or step.tool not in TOOL_REGISTRY:
            raise PlanError("PLAN_UNKNOWN_TOOL", "A step names a tool that is not in the plan's tool list.")
        if step.id in step_ids:
            raise PlanError("PLAN_INVALID_SCHEMA", "Step ids must be unique.")
        step_ids.add(step.id)

    if plan.limits.timeout_s > ceiling["timeout_s"] or plan.limits.memory_mb > ceiling["memory_mb"] \
            or plan.limits.pids > ceiling["pids"]:
        raise PlanError("PLAN_LIMIT_RAISED", "Plan limits exceed the configured sandbox ceiling.")

    producible = {out for tool in plan.tools for out in TOOL_REGISTRY[tool].outputs}
    for out in plan.expected_outputs:
        if out not in producible:
            raise PlanError("PLAN_OUTPUT_UNPRODUCED", "An expected output is not produced by any planned tool.")
    if len(set(plan.expected_outputs)) != len(plan.expected_outputs):
        raise PlanError("PLAN_INVALID_SCHEMA", "Expected outputs must be unique.")
    for tool in plan.tools:
        for required in TOOL_REGISTRY[tool].required_outputs:
            if required not in plan.expected_outputs:
                raise PlanError("PLAN_OUTPUT_UNPRODUCED", f"Required output {required} must be expected.")
    return plan
