"""Deterministic task.py used by MockInference. Standard library only; matplotlib is optional.

The script runs with the sandbox working directory containing dataset.csv and writes to out/.
"""

from app.agent.tools import TOOL_REGISTRY

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

# ---------------------------------------------------------------------------------------------------------
# Registry tools (SDD 7.4). Used only when a plan names one of the new tools. The default flood flow above
# is unchanged. Each section is standard library only. The arithmetic in the hazard and resource sections
# mirrors app/rules/engine.py; tests check that both produce identical output for the same CSV.
# ---------------------------------------------------------------------------------------------------------

TOOL_ORDER = ("geojson_analyzer", "hazard_analyzer", "tsunami_analyzer", "resource_estimator", "blocked_roads",
              "report_generator")

TOOL_PREAMBLE = r'''"""DCE registry tools (mock planner output). Standard library only."""
import csv
import json
import math
import os

OUT_DIR = "out"
REPORT = []
ILLUSTRATIVE_STATUS = "ILLUSTRATIVE: not validated against an authoritative standard (SDD 11.3)"
DISTRICT_CANDIDATES = ["district", "district_name", "location"]
ROAD_CANDIDATES = ["road_status", "road_blocked", "blocked_road"]
BLOCKED_VALUES = ("blocked", "closed", "yes", "true", "1")


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
    if not math.isfinite(value):
        return None
    return value


def blocked_flag(text):
    if text is None or text.strip() == "":
        return None
    return text.strip().lower() in BLOCKED_VALUES


def neutralize(value):
    # SDD 17.2: a text cell that could be read as a spreadsheet formula gets a single quote prefix.
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def write_json(name, document):
    with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
    log("wrote " + name)


def csv_records():
    # Same normalisation as app/rules/engine.py records_from_csv_bytes.
    with open("dataset.csv", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        district_col = find_column(fields, DISTRICT_CANDIDATES)
        depth_col = find_column(fields, ["water_depth_cm"])
        records = []
        for number, row in enumerate(reader, start=1):
            name = (row.get(district_col) or "").strip() if district_col else ""
            records.append({
                "row": number,
                "district": name or "unknown",
                "water_depth_cm": to_number(row.get(depth_col)) if depth_col else None,
            })
    return records


def load_rule_pack():
    # The server verified the pack hash before staging it. The sandbox reads the pack and never edits it.
    with open("rule_pack.json", encoding="utf-8") as handle:
        return json.load(handle)
'''

GEOJSON_SECTION = r'''

def positions(geometry):
    if geometry is None:
        return []
    if geometry["type"] == "GeometryCollection":
        found = []
        for member in geometry["geometries"]:
            found.extend(positions(member))
        return found
    found = []
    stack = [geometry["coordinates"]]
    while stack:
        item = stack.pop()
        if item and isinstance(item[0], (int, float)):
            found.append((float(item[0]), float(item[1])))
        else:
            stack.extend(item)
    return found


def run_geojson_analyzer():
    with open("dataset.geojson", encoding="utf-8-sig") as handle:
        document = json.load(handle)
    features = document["features"]
    geometry_types = {}
    property_counts = {}
    xs = []
    ys = []
    for feature in features:
        geometry = feature.get("geometry")
        gtype = "null" if geometry is None else geometry["type"]
        geometry_types[gtype] = geometry_types.get(gtype, 0) + 1
        for x, y in positions(geometry):
            xs.append(x)
            ys.append(y)
        for key, value in (feature.get("properties") or {}).items():
            if value is not None:
                property_counts[key] = property_counts.get(key, 0) + 1
    bounding_box = [min(xs), min(ys), max(xs), max(ys)] if xs else None
    summary = {
        "data_class": "SIMULATED_FACT",
        "tool": "geojson_analyzer",
        "feature_count": len(features),
        "geometry_types": dict(sorted(geometry_types.items())),
        "bounding_box": bounding_box,
        "property_counts": dict(sorted(property_counts.items())),
    }
    write_json("summary.json", summary)
    REPORT.append("## GeoJSON summary (SIMULATED_FACT)")
    REPORT.append("- Features: %d" % len(features))
    for gtype, count in sorted(geometry_types.items()):
        REPORT.append("- Geometry %s: %d" % (gtype, count))
    REPORT.append("- Bounding box: %s" % (bounding_box,))
    REPORT.append("")
'''

HAZARD_SECTION = r'''

def evaluate_rules(records, pack):
    order = pack["severity_order"]
    rank = {}
    for index, level in enumerate(order):
        rank[level] = index
    counts = {}
    for level in order:
        counts[level] = 0
    counts["UNKNOWN"] = 0
    per_district = {}
    results = []
    for record in sorted(records, key=lambda item: item["row"]):
        depth = record["water_depth_cm"]
        flags = set()
        if depth is None:
            severity = "UNKNOWN"
        else:
            severity = order[0]
            for rule in pack["rules"]:
                if depth >= rule["when"]["water_depth_cm_gte"]:
                    action = rule["then"]
                    if "flag" in action:
                        flags.add(action["flag"])
                    if "severity" in action and rank[action["severity"]] > rank[severity]:
                        severity = action["severity"]
        counts[severity] += 1
        district = per_district.setdefault(record["district"], {
            "rows": 0, "road_blocked_candidates": 0, "unknown_depth_rows": 0})
        district["rows"] += 1
        district["road_blocked_candidates"] += 1 if "road_blocked_candidate" in flags else 0
        district["unknown_depth_rows"] += 1 if depth is None else 0
        results.append({
            "row": record["row"],
            "district": record["district"],
            "water_depth_cm": depth,
            "severity": severity,
            "flags": sorted(flags),
        })
    return {
        "data_class": "INFERRED_FACT",
        "tool": "hazard_analyzer",
        "rule_pack": {"pack_id": pack["pack_id"], "version": pack["version"], "sha256": pack["pack_sha256"]},
        "thresholds": {"label": pack["thresholds_label"], "status": ILLUSTRATIVE_STATUS, "rules": pack["rules"]},
        "rows_evaluated": len(results),
        "rows_unknown_depth": counts["UNKNOWN"],
        "counts_by_severity": dict(sorted(counts.items())),
        "road_blocked_candidates": sum(1 for item in results if "road_blocked_candidate" in item["flags"]),
        "per_district": dict(sorted(per_district.items())),
        "results": results,
    }


def run_hazard_analyzer():
    pack = load_rule_pack()
    result = evaluate_rules(csv_records(), pack)
    write_json("hazard_results.json", result)
    REPORT.append("## Hazard evaluation (INFERRED_FACT, illustrative thresholds)")
    REPORT.append("- Rule pack: %s v%s, sha256 %s" % (pack["pack_id"], pack["version"], pack["pack_sha256"]))
    REPORT.append("- Rows evaluated: %d (unknown depth: %d)" % (result["rows_evaluated"], result["rows_unknown_depth"]))
    REPORT.append("- Road blocked candidates (illustrative, depth 50 cm or more): %d"
                  % result["road_blocked_candidates"])
    for level, count in sorted(result["counts_by_severity"].items()):
        REPORT.append("- Severity %s: %d" % (level, count))
    REPORT.append("")
'''

RESOURCE_SECTION = r'''

def run_resource_estimator():
    pack = load_rule_pack()
    records = csv_records()
    ratios = pack["resource_ratios"]
    threshold = ratios["affected_depth_cm_gte"]
    affected = 0
    unknown = 0
    for record in records:
        depth = record["water_depth_cm"]
        if depth is None:
            unknown += 1
        elif depth >= threshold:
            affected += 1
    people = affected * ratios["people_per_household"]
    litres = people * ratios["drinking_water_litres_per_person_per_day"] * ratios["planning_days"]
    estimate = {
        "data_class": "SIMULATED_FACT",
        "tool": "resource_estimator",
        "label": "ILLUSTRATIVE ratios",
        "rule_pack": {"pack_id": pack["pack_id"], "version": pack["version"], "sha256": pack["pack_sha256"]},
        "inputs": {
            "rows_total": len(records),
            "affected_rows": affected,
            "unknown_depth_rows": unknown,
            "affected_depth_cm_gte": threshold,
        },
        "ratios": {key: value for key, value in ratios.items() if key != "label"},
        "estimates": {
            "households_affected": affected,
            "people_estimated": people,
            "water_packs": math.ceil(affected * ratios["water_packs_per_household"]),
            "food_packs": math.ceil(affected * ratios["food_packs_per_household"]),
            "shelter_kits": math.ceil(affected * ratios["shelter_kits_per_household"]),
            "drinking_water_litres_total": math.ceil(litres),
        },
        "assumptions": [
            "Each affected row is treated as one household (illustrative).",
            "Ratios are illustrative and not validated against an authoritative standard.",
            "Rows with unknown water depth are not counted as affected.",
        ],
        "not_for_operational_use": True,
    }
    write_json("resource_estimate.json", estimate)
    REPORT.append("## Resource estimate (SIMULATED_FACT, ILLUSTRATIVE ratios)")
    REPORT.append("- Affected rows (depth %s cm or more): %d" % (threshold, affected))
    REPORT.append("- Water packs: %d, food packs: %d, shelter kits: %d"
                  % (estimate["estimates"]["water_packs"], estimate["estimates"]["food_packs"],
                     estimate["estimates"]["shelter_kits"]))
    REPORT.append("")
'''

BLOCKED_SECTION = r'''

def run_blocked_roads():
    rows_out = []
    unknown = 0
    with open("dataset.csv", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        road_col = find_column(fields, ROAD_CANDIDATES)
        if road_col is None:
            raise SystemExit("blocked_roads needs a road_status or road_blocked column")
        district_col = find_column(fields, DISTRICT_CANDIDATES)
        depth_col = find_column(fields, ["water_depth_cm"])
        for number, row in enumerate(reader, start=1):
            blocked = blocked_flag(row.get(road_col))
            if blocked is None:
                unknown += 1
                continue
            if not blocked:
                continue
            district = (row.get(district_col) or "").strip() if district_col else ""
            depth = to_number(row.get(depth_col)) if depth_col else None
            rows_out.append([
                number,
                neutralize(district or "unknown"),
                neutralize((row.get(road_col) or "").strip()),
                "" if depth is None else depth,
            ])
    with open(os.path.join(OUT_DIR, "blocked_roads.csv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row", "district", "road_status", "water_depth_cm"])
        writer.writerows(rows_out)
    log("wrote blocked_roads.csv")
    REPORT.append("## Blocked roads (SIMULATED_FACT)")
    REPORT.append("- Blocked road rows: %d (unknown road status rows: %d)" % (len(rows_out), unknown))
    REPORT.append("")
'''

REPORT_SECTION = r'''

def run_report_generator(want_pdf):
    lines = [
        "# Situation report (sandbox analysis)",
        "",
        "Data classes are labelled in each section. This is an analysis output, not a verified field observation.",
        "",
    ] + REPORT
    with open(os.path.join(OUT_DIR, "situation_report.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    log("wrote situation_report.md")
    if want_pdf:
        write_pdf(os.path.join(OUT_DIR, "situation_report.pdf"), lines)
'''

# Minimal PDF 1.4 writer: standard library only, ASCII text in Helvetica, no compression, no images.
PDF_WRITER = r'''

def pdf_text(value):
    out = []
    for ch in value:
        if ch in "\\()":
            out.append("\\" + ch)
        elif 32 <= ord(ch) <= 126:
            out.append(ch)
        else:
            out.append("?")
    return "".join(out)


def wrap_text(text, width=95):
    if not text:
        return [" "]
    return [text[start:start + width] for start in range(0, len(text), width)]


def write_pdf(path, lines):
    wrapped = []
    for line in lines:
        wrapped.extend(wrap_text(line))
    per_page = 56
    pages = [wrapped[start:start + per_page] for start in range(0, len(wrapped), per_page)] or [[" "]]
    objects = {}
    page_ids = []
    for index, page in enumerate(pages):
        page_id = 4 + 2 * index
        content_id = page_id + 1
        page_ids.append(page_id)
        body = ["BT", "/F1 10 Tf", "12 TL", "50 790 Td"]
        for line in page:
            body.append("(" + pdf_text(line) + ") Tj T*")
        body.append("ET")
        stream = "\n".join(body).encode("latin-1")
        objects[page_id] = ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                            "/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id).encode("latin-1")
        objects[content_id] = ("<< /Length %d >>\nstream\n" % len(stream)).encode("latin-1") + stream + b"\nendstream"
    kids = " ".join("%d 0 R" % page_id for page_id in page_ids)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))).encode("latin-1")
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += ("%d 0 obj\n" % number).encode("latin-1") + objects[number] + b"\nendobj\n"
    xref_at = len(out)
    count = len(objects) + 1
    out += ("xref\n0 %d\n" % count).encode("latin-1")
    out += b"0000000000 65535 f \n"
    for number in range(1, count):
        out += ("%010d 00000 n \n" % offsets[number]).encode("latin-1")
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (count, xref_at)).encode("latin-1")
    with open(path, "wb") as handle:
        handle.write(bytes(out))
    log("wrote " + os.path.basename(path))
'''

TSUNAMI_SECTION = r'''

TSUNAMI_CONDITIONS = {
    "magnitude_gte": "magnitude",
    "depth_km_lt": "depth_km",
    "coast_distance_km_lte": "coast_distance_km",
}


def tsunami_records():
    # Same normalisation as app/rules/tsunami.py records_from_csv_bytes.
    with open("dataset.csv", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        name_col = find_column(fields, ["area", "area_name", "district", "location"])
        columns = {
            "magnitude": find_column(fields, ["magnitude"]),
            "depth_km": find_column(fields, ["depth_km"]),
            "coast_distance_km": find_column(fields, ["coast_distance_km"]),
        }
        records = []
        for number, row in enumerate(reader, start=1):
            name = (row.get(name_col) or "").strip() if name_col else ""
            item = {"row": number, "area": name or "unknown"}
            for key, column in columns.items():
                item[key] = to_number(row.get(column)) if column else None
            records.append(item)
    return records


def load_tsunami_pack():
    # The server verified the pack hash before staging it. The sandbox reads the pack and never edits it.
    with open("tsunami_pack.json", encoding="utf-8") as handle:
        return json.load(handle)


def tsunami_condition(key, threshold, record):
    value = record[TSUNAMI_CONDITIONS[key]]
    if value is None:
        return None
    if key == "magnitude_gte":
        return value >= threshold
    if key == "depth_km_lt":
        return value < threshold
    return value <= threshold


def evaluate_tsunami(records, pack):
    order = pack["severity_order"]
    rank = {level: index for index, level in enumerate(order)}
    counts = {level: 0 for level in order}
    counts["UNKNOWN"] = 0
    results = []
    for record in sorted(records, key=lambda item: item["row"]):
        fired = None
        flags = set()
        undecided = False
        for rule in pack["rules"]:
            outcomes = [tsunami_condition(key, threshold, record) for key, threshold in rule["when"].items()]
            if all(outcome is True for outcome in outcomes):
                action = rule["then"]
                if "flag" in action:
                    flags.add(action["flag"])
                if "severity" in action and (fired is None or rank[action["severity"]] > rank[fired]):
                    fired = action["severity"]
            elif any(outcome is None for outcome in outcomes):
                undecided = True
        if fired is not None:
            severity = fired
        elif undecided:
            severity = "UNKNOWN"
        else:
            severity = order[0]
        counts[severity] += 1
        results.append({
            "row": record["row"],
            "area": record["area"],
            "magnitude": record["magnitude"],
            "depth_km": record["depth_km"],
            "coast_distance_km": record["coast_distance_km"],
            "severity": severity,
            "flags": sorted(flags),
        })
    return {
        "data_class": "INFERRED_FACT",
        "tool": "tsunami_analyzer",
        "rule_pack": {"pack_id": pack["pack_id"], "version": pack["version"], "sha256": pack["pack_sha256"]},
        "thresholds": {"label": pack["thresholds_label"], "status": ILLUSTRATIVE_STATUS, "rules": pack["rules"]},
        "rows_evaluated": len(results),
        "counts_by_severity": dict(sorted(counts.items())),
        "watch_candidates": sum(1 for item in results if "tsunami_watch_candidate" in item["flags"]),
        "results": results,
        "not_for_operational_use": True,
    }


def run_tsunami_analyzer():
    pack = load_tsunami_pack()
    result = evaluate_tsunami(tsunami_records(), pack)
    write_json("tsunami_results.json", result)
    REPORT.append("## Earthquake-tsunami screening (INFERRED_FACT, illustrative thresholds)")
    REPORT.append("- Rule pack: %s v%s, sha256 %s" % (pack["pack_id"], pack["version"], pack["pack_sha256"]))
    REPORT.append("- Rows evaluated: %d" % result["rows_evaluated"])
    REPORT.append("- Tsunami watch candidates (illustrative, not a warning): %d" % result["watch_candidates"])
    for level, count in sorted(result["counts_by_severity"].items()):
        REPORT.append("- Severity %s: %d" % (level, count))
    REPORT.append("")
'''

_TOOL_SECTIONS = {
    "geojson_analyzer": GEOJSON_SECTION,
    "hazard_analyzer": HAZARD_SECTION,
    "tsunami_analyzer": TSUNAMI_SECTION,
    "resource_estimator": RESOURCE_SECTION,
    "blocked_roads": BLOCKED_SECTION,
    "report_generator": REPORT_SECTION,
}

_TOOL_DESCRIPTIONS = {
    "geojson_analyzer": "Summarise GeoJSON features, geometry types, bounding box and properties",
    "hazard_analyzer": "Evaluate flood rows with the illustrative rule pack",
    "tsunami_analyzer": "Screen earthquake rows with the illustrative earthquake-tsunami rule pack",
    "resource_estimator": "Estimate illustrative resource needs from affected rows",
    "blocked_roads": "List rows with blocked roads",
    "report_generator": "Write the situation report",
}


def registry_tools_in_order(tools: list[str] | tuple[str, ...]) -> list[str]:
    """The requested registry tools in the fixed execution order. Unknown names raise ValueError."""
    unknown = [name for name in tools if name not in _TOOL_SECTIONS]
    if unknown or not tools:
        raise ValueError(f"unsupported tool set: {sorted(set(tools))}")
    return [name for name in TOOL_ORDER if name in tools]


def mock_tool_plan(tools: list[str] | tuple[str, ...], ceiling: dict[str, int], *, want_pdf: bool = False) -> dict:
    """A plan a planner could return for these registry tools. Validated later by validate_plan."""
    chosen = registry_tools_in_order(tools)
    steps = []
    for index, name in enumerate(chosen, start=1):
        description = _TOOL_DESCRIPTIONS[name]
        if name == "report_generator" and want_pdf:
            description = "Write the situation report in Markdown and PDF"
        steps.append({"id": f"s{index}", "description": description, "tool": name})
    expected: list[str] = []
    for name in chosen:
        for output in TOOL_REGISTRY[name].required_outputs:
            if output not in expected:
                expected.append(output)
    if "report_generator" in chosen and want_pdf:
        expected.append("situation_report.pdf")
    return {
        "tools": chosen,
        "steps": steps,
        "limits": {"timeout_s": ceiling["timeout_s"], "memory_mb": ceiling["memory_mb"], "pids": ceiling["pids"]},
        "expected_outputs": expected,
        "assumptions": ["Hazard thresholds and resource ratios come from the illustrative rule pack flood_v1 "
                        "and are not validated against an authoritative standard."],
        "data_class": "SIMULATED_FACT",
    }


def build_tool_script(tools: list[str] | tuple[str, ...], *, want_pdf: bool = False) -> str:
    """One task.py for the selected registry tools. The PDF writer is included only when a PDF is planned."""
    chosen = registry_tools_in_order(tools)
    parts = [TOOL_PREAMBLE]
    parts.extend(_TOOL_SECTIONS[name] for name in chosen)
    if "report_generator" in chosen and want_pdf:
        parts.append(PDF_WRITER)
    calls = [f"    run_{name}()" for name in chosen if name != "report_generator"]
    if "report_generator" in chosen:
        calls.append(f"    run_report_generator({bool(want_pdf)})")
    parts.append("\n\ndef main():\n    os.makedirs(OUT_DIR, exist_ok=True)\n" + "\n".join(calls)
                 + "\n    log(\"done\")\n\n\nif __name__ == \"__main__\":\n    main()\n")
    return "".join(parts)
