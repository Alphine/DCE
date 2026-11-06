"""Deterministic task.py used by MockInference. Standard library only; matplotlib is optional.

The script runs with the sandbox working directory containing dataset.csv and writes to out/.
"""

MOCK_TASK_SCRIPT = r'''"""DCE flood analysis (mock planner output). Standard library only."""
import csv
import json
import os

THRESHOLD_CM = 30
DATASET = "dataset.csv"
OUT_DIR = "out"


def log(message):
    print("[task] " + message, flush=True)


def find_column(fields, candidates):
    lowered = {}
    for field in fields:
        lowered.setdefault(field.strip().lower(), field)
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def to_number(text):
    # None means unknown. Empty, non-numeric, NaN and infinite values are unknown, never zero.
    if text is None or text.strip() == "":
        return None
    try:
        value = float(text.strip())
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def blocked_flag(text):
    if text is None or text.strip() == "":
        return None
    return text.strip().lower() in ("blocked", "closed", "yes", "true", "1")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(DATASET, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        district_col = find_column(fields, ["district", "district_name", "location"])
        depth_col = find_column(fields, ["water_depth_cm"])
        road_col = find_column(fields, ["road_status", "road_blocked", "blocked_road"])
        population_col = find_column(fields, ["affected_population", "population_affected"])
        log("columns: district=%s depth=%s road=%s population=%s"
            % (district_col, depth_col, road_col, population_col))

        rows = 0
        flooded_total = 0
        flooded_by_district = {}
        incidents_by_district = {}
        depth_unknown = 0
        blocked_total = 0
        blocked_unknown = 0
        population_sum = 0.0
        population_known = 0
        population_unknown = 0

        for row in reader:
            rows += 1
            district = (row.get(district_col) or "").strip() if district_col else ""
            district = district or "unknown"
            incidents_by_district[district] = incidents_by_district.get(district, 0) + 1
            if depth_col:
                depth = to_number(row.get(depth_col))
                if depth is None:
                    depth_unknown += 1
                elif depth > THRESHOLD_CM:
                    flooded_total += 1
                    flooded_by_district[district] = flooded_by_district.get(district, 0) + 1
            if road_col:
                blocked = blocked_flag(row.get(road_col))
                if blocked is None:
                    blocked_unknown += 1
                elif blocked:
                    blocked_total += 1
            if population_col:
                people = to_number(row.get(population_col))
                if people is None:
                    population_unknown += 1
                else:
                    population_sum += people
                    population_known += 1

    # Schema from docs/api.md section 12. Unknown values are reported as unknown, never as zero.
    summary = {
        "dataset_rows": rows,
        "flooded_districts": [
            {
                "district": name,
                "incidents": incidents_by_district[name],
                "flooded_incidents": flooded_by_district.get(name, 0) if depth_col else None,
            }
            for name in sorted(incidents_by_district)
        ],
        "blocked_roads": blocked_total if road_col else None,
        "affected_population": {
            "sum": round(population_sum, 2) if population_known else None,
            "unknown_rows": population_unknown if population_col else rows,
        },
        "data_class": "SIMULATED_FACT",
    }
    with open(os.path.join(OUT_DIR, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
    log("wrote summary.json")

    lines = [
        "# Situation report (sandbox analysis)",
        "",
        "Data class: SIMULATED_FACT. This is an analysis output, not a verified field observation.",
        "",
        "- Rows analysed: %d" % rows,
        "- Flood threshold: water depth above %d cm" % THRESHOLD_CM,
    ]
    if depth_col:
        lines.append("- Flooded rows: %d" % flooded_total)
        lines.append("- Rows with unknown water depth: %d (not counted as flooded)" % depth_unknown)
        for name, count in sorted(flooded_by_district.items()):
            lines.append("  - %s: %d" % (name, count))
    if road_col:
        lines.append("- Blocked roads: %d (unknown status rows: %d)" % (blocked_total, blocked_unknown))
    if population_col:
        if population_known:
            lines.append("- Affected population (known values only): %s" % summary["affected_population"]["sum"])
        lines.append("- Rows with unknown affected population: %d" % population_unknown)
    with open(os.path.join(OUT_DIR, "situation_report.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    log("wrote situation_report.md")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log("matplotlib not available; chart.png skipped")
    else:
        try:
            if flooded_by_district:
                names = sorted(flooded_by_district)
                values = [flooded_by_district[n] for n in names]
                figure, axis = plt.subplots(figsize=(6, 4))
                axis.bar(names, values, color="#2b6cb0")
                axis.set_title("Flooded rows by district (depth above %d cm)" % THRESHOLD_CM)
                axis.set_ylabel("Rows")
                figure.tight_layout()
                figure.savefig(os.path.join(OUT_DIR, "chart.png"), dpi=100)
                plt.close(figure)
                log("wrote chart.png")
            else:
                log("no flooded rows; chart.png skipped")
        except Exception as exc:  # chart is optional; never fail the task for it
            log("chart skipped: " + type(exc).__name__)


if __name__ == "__main__":
    main()
'''
