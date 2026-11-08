"""Alerts, alert summary, and the report time series (docs/notes/w4-alerts.md).

Visibility follows the reports rules: Viewers see verified reports only, so the time series counts verified reports
for them, and the DECISION_WAITING count (which includes OBSERVATION reports and PROPOSED missions) is zero for
Viewers. Every alert and bucket holds ids and counts, never usernames.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app import audit
from app.alerts import SEVERITIES, STORED_KINDS
from app.auth import CurrentUser, require_role
from app.container import services_of
from app.countries import country_filter, country_or_default, country_query
from app.errors import AppError
from app.routes.reports import visible_clause
from app.util import utc_now

router = APIRouter(tags=["alerts"])

KINDS = (*STORED_KINDS, "DECISION_WAITING")
HAZARDS = ("EARTHQUAKE", "TSUNAMI", "EXTREME_RAINFALL", "FLOOD", "LANDSLIDE", "WILDFIRE", "SMOKE")
TIMESERIES_HOURS = (24, 72, 168)

_SELECT = "SELECT a.* FROM alerts a "


def _view(row: sqlite3.Row) -> dict[str, Any]:
    acknowledged = row["acknowledged_at"] is not None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "severity": row["severity"],
        "country_code": country_or_default(row["country_code"]),
        "district": row["district"],
        "title": row["title"],
        "detail": json.loads(row["detail_json"]),
        "source": {"type": row["source_type"], "id": row["source_id"]},
        "created_at": row["created_at"],
        "acknowledged": acknowledged,
        "acknowledged_by": {"id": row["acknowledged_by"]} if acknowledged else None,
        "acknowledged_at": row["acknowledged_at"],
    }


def _load(conn: sqlite3.Connection, alert_id: str) -> sqlite3.Row:
    row = conn.execute(_SELECT + "WHERE a.id = ?", (alert_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Alert not found.")
    return row


def _one_of(value: str | None, allowed: tuple[str, ...], name: str) -> str | None:
    if value is None:
        return None
    if value not in allowed:
        raise AppError("VALIDATION_FAILED", f"{name} must be one of {', '.join(allowed)}.")
    return value


@router.get("/alerts")
def list_alerts(request: Request,
                country: str | None = Query(default=None, max_length=2),
                kind: str | None = Query(default=None, max_length=40),
                severity: str | None = Query(default=None, max_length=10),
                unacknowledged: bool = Query(default=False),
                limit: int = Query(default=50, ge=1, le=200),
                user: CurrentUser = Depends(require_role("Viewer"))) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    frag, cparams = country_filter("a", country_query(country))
    if frag:
        clauses.append(frag)
        params += cparams
    kind = _one_of(kind, KINDS, "kind")
    if kind is not None:
        clauses.append("a.kind = ?")
        params.append(kind)
    severity = _one_of(severity, SEVERITIES, "severity")
    if severity is not None:
        clauses.append("a.severity = ?")
        params.append(severity)
    if unacknowledged:
        clauses.append("a.acknowledged_at IS NULL")
    where = ("WHERE " + " AND ".join(clauses) + " ") if clauses else ""
    with services_of(request).db.read() as conn:
        rows = conn.execute(_SELECT + where + "ORDER BY a.created_at DESC, a.id LIMIT ?",
                            (*params, limit)).fetchall()
    return [_view(r) for r in rows]


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, request: Request,
                      user: CurrentUser = Depends(require_role("Reviewer"))) -> dict[str, Any]:
    """Idempotent. The first call records who acknowledged and writes one audit row. Later calls change nothing."""
    services = services_of(request)
    with services.db.transaction() as conn:
        row = _load(conn, alert_id)
        if row["acknowledged_at"] is None:
            conn.execute("UPDATE alerts SET acknowledged_by = ?, acknowledged_at = ? "
                         "WHERE id = ? AND acknowledged_at IS NULL", (user.id, utc_now(), alert_id))
            audit.append(conn, actor=user.username, action="alert.acknowledged", subject=alert_id, detail={
                "kind": row["kind"], "severity": row["severity"], "country_code": country_or_default(row["country_code"]),
            })
            row = _load(conn, alert_id)
        return _view(row)


@router.get("/alerts/summary")
def alert_summary(request: Request,
                  country: str | None = Query(default=None, max_length=2),
                  user: CurrentUser = Depends(require_role("Viewer"))) -> dict[str, Any]:
    """Counts of unacknowledged stored alerts by severity and kind, plus DECISION_WAITING, which is computed
    here: PROPOSED missions and OBSERVATION reports in the country. Those two are counted for Analyst and above
    only, because Viewers may not see them.

    by_severity covers stored alerts. by_kind covers every kind, DECISION_WAITING included. total is the sum of
    by_kind."""
    code = country_query(country)
    by_severity = {s: 0 for s in SEVERITIES}
    by_kind = {k: 0 for k in KINDS}
    with services_of(request).db.read() as conn:
        clauses = ["a.acknowledged_at IS NULL"]
        params: list[Any] = []
        frag, cparams = country_filter("a", code)
        if frag:
            clauses.append(frag)
            params += cparams
        where = " AND ".join(clauses)
        for row in conn.execute(f"SELECT a.severity AS k, COUNT(*) AS n FROM alerts a WHERE {where} "
                                "GROUP BY a.severity", params):
            by_severity[row["k"]] = row["n"]
        for row in conn.execute(f"SELECT a.kind AS k, COUNT(*) AS n FROM alerts a WHERE {where} GROUP BY a.kind",
                                params):
            by_kind[row["k"]] = row["n"]

        missions_waiting = reports_waiting = 0
        if user.has_at_least("Analyst"):
            frag_m, pm = country_filter("m", code)
            mwhere = "m.status = 'PROPOSED'" + (f" AND {frag_m}" if frag_m else "")
            missions_waiting = conn.execute(f"SELECT COUNT(*) FROM missions m WHERE {mwhere}", pm).fetchone()[0]
            frag_r, pr = country_filter("r", code)
            rwhere = "r.status = 'OBSERVATION'" + (f" AND {frag_r}" if frag_r else "")
            reports_waiting = conn.execute(f"SELECT COUNT(*) FROM reports r WHERE {rwhere}", pr).fetchone()[0]

    by_kind["DECISION_WAITING"] = missions_waiting + reports_waiting
    return {
        "country": code,
        "by_severity": by_severity,
        "by_kind": by_kind,
        "decision_waiting": {"missions_proposed": missions_waiting, "reports_observation": reports_waiting},
        "total": sum(by_kind.values()),
    }


@router.get("/timeseries")
def timeseries(request: Request,
               country: str | None = Query(default=None, max_length=2),
               hours: int = Query(default=72),
               user: CurrentUser = Depends(require_role("Viewer"))) -> dict[str, Any]:
    """Hourly UTC buckets of report intake, ending with the current hour. Buckets without data are zero.
    `reports` counts every report the caller may see, `verified` counts VERIFIED_OBSERVATION ones, and by_hazard
    counts `reports` per hazard_type. Reports are placed by created_at (intake time)."""
    if hours not in TIMESERIES_HOURS:
        raise AppError("VALIDATION_FAILED", "hours must be 24, 72 or 168.")
    code = country_query(country)
    now_hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start = now_hour - timedelta(hours=hours - 1)
    buckets: dict[str, dict[str, Any]] = {}
    for i in range(hours):
        key = (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00:00Z")
        buckets[key] = {"hour": key, "reports": 0, "verified": 0, "by_hazard": {h: 0 for h in HAZARDS}}

    clauses = ["r.created_at >= ?", *visible_clause(user)]
    params: list[Any] = [start.strftime("%Y-%m-%dT%H:%M:%SZ")]
    frag, cparams = country_filter("r", code)
    if frag:
        clauses.append(frag)
        params += cparams
    with services_of(request).db.read() as conn:
        rows = conn.execute(
            "SELECT substr(r.created_at, 1, 13) AS hk, r.hazard_type AS hz, r.status AS st, COUNT(*) AS n "
            "FROM reports r WHERE " + " AND ".join(clauses) + " GROUP BY hk, hz, st",
            params,
        ).fetchall()
    for row in rows:
        bucket = buckets.get(row["hk"] + ":00:00Z")
        if bucket is None:
            continue  # created_at outside the window (for example, a late clock)
        bucket["reports"] += row["n"]
        bucket["by_hazard"][row["hz"]] += row["n"]
        if row["st"] == "VERIFIED_OBSERVATION":
            bucket["verified"] += row["n"]
    return {"country": code, "hours": hours, "buckets": list(buckets.values())}
