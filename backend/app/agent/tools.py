"""Tool registry: the only tools a plan may name (SDD 7.4, docs/api.md section 3).

Every tool declares the dataset kinds it accepts, the sandbox input files it needs besides the dataset,
the output files it may produce (all must also be on the OUTPUT_RULES allowlist), the outputs it always
writes, and a schema for each output. Tools not in this registry cannot run.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

RULE_PACK_INPUT = "rule_pack.json"
DATASET_INPUT_NAMES = MappingProxyType({"CSV": "dataset.csv", "GEOJSON": "dataset.geojson"})


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_kinds: tuple[str, ...]              # dataset kinds accepted: "CSV" | "GEOJSON"
    outputs: tuple[str, ...]                  # file names this tool may produce, all allowed by OUTPUT_RULES
    required_outputs: tuple[str, ...]         # subset that the tool always writes
    output_schema: Mapping[str, str]          # per output file: what it contains
    input_files: tuple[str, ...] = ()         # sandbox inputs besides the dataset (server-supplied)
    data_class: str = "SIMULATED_FACT"        # docs/api.md data classes (SDD 16.3)
    input_schema: str = "Approved dataset of the accepted kind."


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "csv_analyzer": ToolSpec(
        name="csv_analyzer",
        description="Count flooded districts (water depth above threshold), blocked roads and affected population.",
        input_kinds=("CSV",),
        outputs=("summary.json",),
        required_outputs=("summary.json",),
        output_schema={"summary.json": "dataset_rows, flooded_districts[], blocked_roads, affected_population"},
    ),
    "chart_generator": ToolSpec(
        name="chart_generator",
        description="Plot water depth by district. Produced only when the sandbox image provides matplotlib.",
        input_kinds=("CSV",),
        outputs=("chart.png",),
        required_outputs=(),
        output_schema={"chart.png": "PNG bar chart of flooded rows by district"},
    ),
    "report_generator": ToolSpec(
        name="report_generator",
        description="Write the situation report in Markdown, and in PDF when planned (stdlib PDF writer).",
        input_kinds=("CSV", "GEOJSON"),
        outputs=("situation_report.md", "situation_report.pdf"),
        required_outputs=("situation_report.md",),
        output_schema={
            "situation_report.md": "Markdown report with data class labels",
            "situation_report.pdf": "Same content as PDF (%PDF magic, 10 MB limit)",
        },
    ),
    "geojson_analyzer": ToolSpec(
        name="geojson_analyzer",
        description="Summarise an approved GeoJSON FeatureCollection: feature count, geometry types, bounding box, "
                    "and per-property non-null counts.",
        input_kinds=("GEOJSON",),
        outputs=("summary.json",),
        required_outputs=("summary.json",),
        output_schema={"summary.json": "feature_count, geometry_types{}, bounding_box[minx,miny,maxx,maxy] or null, "
                                       "property_counts{}"},
        input_schema="Approved GeoJSON FeatureCollection dataset.",
    ),
    "hazard_analyzer": ToolSpec(
        name="hazard_analyzer",
        description="Evaluate approved flood rows with the hash-checked rule pack (illustrative thresholds). "
                    "Deterministic: same rows and pack give the same output.",
        input_kinds=("CSV",),
        input_files=(RULE_PACK_INPUT,),
        outputs=("hazard_results.json",),
        required_outputs=("hazard_results.json",),
        output_schema={"hazard_results.json": "data_class INFERRED_FACT, rule_pack{pack_id,version,sha256}, "
                                              "thresholds{label: illustrative, rules[]}, counts_by_severity, "
                                              "road_blocked_candidates, per_district{}, results[]"},
        data_class="INFERRED_FACT",
    ),
    "resource_estimator": ToolSpec(
        name="resource_estimator",
        description="Illustrative resource estimate (water packs, food packs, shelter kits, drinking water) from "
                    "affected row counts and the rule pack ratios.",
        input_kinds=("CSV",),
        input_files=(RULE_PACK_INPUT,),
        outputs=("resource_estimate.json",),
        required_outputs=("resource_estimate.json",),
        output_schema={"resource_estimate.json": "data_class SIMULATED_FACT, label ILLUSTRATIVE ratios, inputs{}, "
                                                 "ratios{}, estimates{}, assumptions[]"},
        data_class="SIMULATED_FACT",
    ),
    "blocked_roads": ToolSpec(
        name="blocked_roads",
        description="List rows whose road is blocked as blocked_roads.csv. Needs a road_status or road_blocked column "
                    "(see datasets/samples/README.md).",
        input_kinds=("CSV",),
        outputs=("blocked_roads.csv",),
        required_outputs=("blocked_roads.csv",),
        output_schema={"blocked_roads.csv": "columns row, district, road_status, water_depth_cm; text cells "
                                            "neutralised against spreadsheet formulas"},
    ),
}

ALLOWED_TOOL_NAMES = frozenset(TOOL_REGISTRY)


def inputs_for_tools(tools: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Server-supplied sandbox input files needed by a set of tools, in a stable order."""
    needed: list[str] = []
    for name in tools:
        for item in TOOL_REGISTRY[name].input_files:
            if item not in needed:
                needed.append(item)
    return tuple(needed)
