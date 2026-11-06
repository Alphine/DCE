"""Tool registry: the only tools a plan may name (SDD 7.4, docs/api.md section 3)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    outputs: tuple[str, ...]          # file names this tool may produce, all allowed by OUTPUT_RULES
    required_outputs: tuple[str, ...]  # subset that the tool always writes


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "csv_analyzer": ToolSpec(
        name="csv_analyzer",
        description="Count flooded districts (water depth above threshold), blocked roads and affected population.",
        outputs=("summary.json",),
        required_outputs=("summary.json",),
    ),
    "chart_generator": ToolSpec(
        name="chart_generator",
        description="Plot water depth by district. Produced only when the sandbox image provides matplotlib.",
        outputs=("chart.png",),
        required_outputs=(),
    ),
    "report_generator": ToolSpec(
        name="report_generator",
        description="Write the situation report in Markdown.",
        outputs=("situation_report.md",),
        required_outputs=("situation_report.md",),
    ),
}

ALLOWED_TOOL_NAMES = frozenset(TOOL_REGISTRY)
