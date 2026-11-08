"""Alert generation (docs/notes/w4-alerts.md).

Pure functions build alert records from events. Write helpers insert them and must be called inside the caller's
open transaction, so an alert exists if and only if the event that caused it was committed.

An alert never carries a username. Only ids, hazard types, counts and free text that the caller already stores.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from app.countries import country_or_default
from app.util import canonical_json, new_id, utc_now

KINDS = ("REPORT_VERIFIED", "THRESHOLD_CROSSED", "DECISION_WAITING", "SYNC_REJECTED")
# DECISION_WAITING is computed on read and never stored (see routes/alerts.py).
STORED_KINDS = ("REPORT_VERIFIED", "THRESHOLD_CROSSED", "SYNC_REJECTED")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
DEFAULT_SEVERITY = "MEDIUM"
TITLE_MAX = 120


def _title(text: str) -> str:
    """Fit a title into the 120-character column. Ellipsis when cut."""
    return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1] + "…"


def severity_or_default(value: str | None) -> str:
    """A report's severity_reported, or MEDIUM when the report did not say."""
    return value if value in SEVERITIES else DEFAULT_SEVERITY


def report_verified_alert(report: Mapping[str, Any]) -> dict[str, Any]:
    """Pure. The alert for a report that just became VERIFIED_OBSERVATION. `report` is a row or dict with the
    report fields. The country is resolved the same way the API shows it (NULL is 'ID')."""
    hazard = report["hazard_type"]
    place = report.get("location_name") or "unnamed location"
    return {
        "kind": "REPORT_VERIFIED",
        "severity": severity_or_default(report.get("severity_reported")),
        "country_code": country_or_default(report.get("country_code")),
        "district": None,
        "title": _title(f"Verified {hazard} report: {place}"),
        "detail": {"report_id": report["id"], "hazard_type": hazard, "location_name": report.get("location_name")},
        "source_type": "report",
        "source_id": report["id"],
    }


def threshold_crossings(before: Mapping[str, Mapping[str, int]], after: Mapping[str, Mapping[str, int]],
                        thresholds: Mapping[str, int], *, dataset_id: str) -> list[dict[str, Any]]:
    """Pure. `before` and `after` map country -> hazard -> count from two evaluations of the same dataset-based
    hazard rules. An alert is produced for each (country, hazard) whose count rose above its threshold:
    before <= threshold < after. Nothing is produced when the count was already above, or did not rise.

    Not called on every request. The hazard engine is not wired to this yet (see docs/notes/w4-alerts.md)."""
    alerts: list[dict[str, Any]] = []
    for country in sorted(after):
        for hazard in sorted(thresholds):
            limit = thresholds[hazard]
            now_count = int(after[country].get(hazard, 0))
            prev_count = int(before.get(country, {}).get(hazard, 0))
            if prev_count <= limit < now_count:
                alerts.append({
                    "kind": "THRESHOLD_CROSSED",
                    "severity": DEFAULT_SEVERITY,
                    "country_code": country_or_default(country),
                    "district": None,
                    "title": _title(f"{hazard} count rose above {limit} ({now_count} rows)"),
                    "detail": {"hazard_type": hazard, "threshold": limit, "before": prev_count, "after": now_count},
                    "source_type": "dataset",
                    "source_id": dataset_id,
                })
    return alerts


def sync_rejected_alert(*, op_id: str, item_kind: str, reason_code: str, country_code: str | None) -> dict[str, Any]:
    """Pure. The alert for an offline item the server refused. The caller passes the reason code, never the text."""
    return {
        "kind": "SYNC_REJECTED",
        "severity": DEFAULT_SEVERITY,
        "country_code": country_or_default(country_code),
        "district": None,
        "title": _title(f"Offline {item_kind} item rejected: {reason_code}"),
        "detail": {"item_kind": item_kind, "reason_code": reason_code},
        "source_type": "sync_op",
        "source_id": op_id,
    }


def write_alert(conn: sqlite3.Connection, alert: Mapping[str, Any]) -> str:
    """Insert one alert. The caller must hold an open transaction. Returns the new id."""
    if not conn.in_transaction:
        raise RuntimeError("alert write requires an open transaction")
    if alert["kind"] not in STORED_KINDS:
        raise ValueError(f"{alert['kind']} is not stored")
    alert_id = new_id()
    conn.execute(
        "INSERT INTO alerts (id, kind, severity, country_code, district, title, detail_json, source_type, "
        "source_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (alert_id, alert["kind"], alert["severity"], alert["country_code"], alert["district"], alert["title"],
         canonical_json(alert["detail"]), alert["source_type"], alert["source_id"], utc_now()),
    )
    return alert_id


def write_report_verified(conn: sqlite3.Connection, report: Mapping[str, Any], new_status: str) -> str | None:
    """Called from the review path after a report's status is written. Creates the alert only when the report
    became VERIFIED_OBSERVATION. A rejection writes nothing."""
    if new_status != "VERIFIED_OBSERVATION":
        return None
    # sqlite3.Row has no .get(), so copy it into a dict first.
    return write_alert(conn, report_verified_alert(dict(report)))


def write_sync_rejected(conn: sqlite3.Connection, *, op_id: str, item_kind: str, reason_code: str,
                        country_code: str | None) -> str:
    """For the sync path (not wired yet, see docs/notes/w4-alerts.md)."""
    return write_alert(conn, sync_rejected_alert(op_id=op_id, item_kind=item_kind, reason_code=reason_code,
                                                 country_code=country_code))
