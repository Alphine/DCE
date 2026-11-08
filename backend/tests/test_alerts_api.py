"""Alerts, alert summary, and the report time series (docs/notes/w4-alerts.md).

Covers: generation on verify (and none on reject), acknowledge role and idempotency, filters, summary arithmetic
including DECISION_WAITING, zero-filled hourly buckets, and that no alert carries a username.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import alerts as alerts_core
from app.errors import install_error_handlers
from app.routes import alerts as alerts_routes
from tests.conftest import SEED_USERS, Api, Env

HAZARDS = ("EARTHQUAKE", "TSUNAMI", "EXTREME_RAINFALL", "FLOOD", "LANDSLIDE", "WILDFIRE", "SMOKE")


def _mount_alert_routes(env: Env) -> Env:
    """Serve the alert routes from an outer app that wraps the real app. The outer app answers /api/alerts and
    /api/timeseries and hands every other path to the real app. Needed until main.py includes alerts.router:
    the real app's own catch-all /api route would otherwise answer 404 first. Services are shared with the real
    app, so the same database and the same session rules apply."""
    outer = FastAPI()
    install_error_handlers(outer)
    outer.state.db = env.app.state.db
    outer.state.services = env.app.state.services
    outer.include_router(alerts_routes.router, prefix="/api")
    outer.mount("/", env.app)
    env.client = TestClient(outer, base_url="http://testserver")
    env.api = Api(env.client)
    return env


@pytest.fixture
def aenv(make_env: Callable[..., Env]) -> Env:
    return _mount_alert_routes(make_env())


def _report(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "hazard_type": "FLOOD",
        "location_name": "Kemang",
        "latitude": -6.26,
        "longitude": 106.81,
        "severity_reported": "HIGH",
        "notes": "Water above the curb.",
    }
    body.update(overrides)
    return body


def _submit(env: Env, **overrides: Any) -> str:
    response = env.api("POST", "/api/reports", env.token("analyst"), json=_report(**overrides))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _review(env: Env, report_id: str, decision: str = "approve") -> None:
    response = env.api("POST", f"/api/reports/{report_id}/review", env.token("reviewer"),
                       json={"decision": decision})
    assert response.status_code == 200, response.text


def _verified(env: Env, **overrides: Any) -> str:
    report_id = _submit(env, **overrides)
    _review(env, report_id)
    return report_id


def _alerts(env: Env, username: str = "viewer", query: str = "") -> list[dict[str, Any]]:
    response = env.api("GET", f"/api/alerts{query}", env.token(username))
    assert response.status_code == 200, response.text
    return response.json()


def _propose_mission(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = env.api("POST", "/api/missions", env.token("analyst"), json={
        "source_type": "DATASET", "source_id": dataset_id, "title": "Flood response: south",
        "objective": "Prioritise pump routes.", "area_column": "district",
    })
    assert response.status_code == 201, response.text


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


def _set_created_at(env: Env, table: str, row_id: str, stamp: str) -> None:
    with env.db.transaction() as conn:
        conn.execute(f"UPDATE {table} SET created_at = ? WHERE id = ?", (stamp, row_id))


# ----- generation --------------------------------------------------------------------------------

def test_verify_creates_one_report_alert_with_the_reported_severity(aenv: Env) -> None:
    report_id = _verified(aenv, severity_reported="CRITICAL", location_name="Kemang")
    rows = _alerts(aenv)
    assert len(rows) == 1
    alert = rows[0]
    assert alert["kind"] == "REPORT_VERIFIED"
    assert alert["severity"] == "CRITICAL"
    assert alert["country_code"] == "ID"
    assert alert["source"] == {"type": "report", "id": report_id}
    assert alert["detail"]["hazard_type"] == "FLOOD"
    assert alert["acknowledged"] is False
    assert alert["acknowledged_by"] is None


def test_report_without_severity_gets_medium(aenv: Env) -> None:
    _verified(aenv, severity_reported=None)
    assert _alerts(aenv)[0]["severity"] == "MEDIUM"


def test_reject_creates_no_alert(aenv: Env) -> None:
    report_id = _submit(aenv)
    _review(aenv, report_id, decision="reject")
    assert _alerts(aenv) == []


def test_alert_country_follows_the_report(aenv: Env) -> None:
    _verified(aenv, country_code="JP")
    assert _alerts(aenv)[0]["country_code"] == "JP"


def test_alert_is_written_in_the_same_transaction_as_the_review(aenv: Env) -> None:
    report_id = _submit(aenv)
    with aenv.db.read() as conn:
        before = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    _review(aenv, report_id)
    with aenv.db.read() as conn:
        after = conn.execute("SELECT COUNT(*) FROM alerts WHERE source_id = ?", (report_id,)).fetchone()[0]
    assert before == 0 and after == 1


def test_write_helper_refuses_to_run_outside_a_transaction(aenv: Env) -> None:
    with aenv.db.read() as conn, pytest.raises(RuntimeError):
        alerts_core.write_alert(conn, alerts_core.report_verified_alert(
            {"id": "x", "hazard_type": "FLOOD", "location_name": None, "severity_reported": None,
             "country_code": None}))


# ----- acknowledge -------------------------------------------------------------------------------

def test_acknowledge_requires_reviewer_and_is_idempotent(aenv: Env) -> None:
    _verified(aenv)
    alert_id = _alerts(aenv)[0]["id"]
    path = f"/api/alerts/{alert_id}/acknowledge"

    assert aenv.api("POST", path, aenv.token("viewer")).status_code == 403
    assert aenv.api("POST", path, aenv.token("analyst")).status_code == 403
    assert aenv.api("POST", path).status_code == 401

    first = aenv.api("POST", path, aenv.token("reviewer"))
    assert first.status_code == 200, first.text
    assert first.json()["acknowledged"] is True
    assert set(first.json()["acknowledged_by"]) == {"id"}  # the user id only, never a username

    second = aenv.api("POST", path, aenv.token("approver"))
    assert second.status_code == 200
    assert second.json()["acknowledged_at"] == first.json()["acknowledged_at"]
    assert second.json()["acknowledged_by"] == first.json()["acknowledged_by"]

    acks = [r for r in aenv.audit_rows() if r["action"] == "alert.acknowledged"]
    assert len(acks) == 1
    assert acks[0]["subject"] == alert_id


def test_acknowledge_unknown_alert_is_404(aenv: Env) -> None:
    response = aenv.api("POST", "/api/alerts/does-not-exist/acknowledge", aenv.token("reviewer"))
    assert response.status_code == 404
    assert _error_code(response) == "NOT_FOUND"


# ----- list filters -----------------------------------------------------------------------------

def test_list_filters_by_country_kind_severity_and_acknowledgement(aenv: Env) -> None:
    _verified(aenv, severity_reported="HIGH", country_code="ID")
    _verified(aenv, severity_reported="CRITICAL", country_code="JP")
    all_rows = _alerts(aenv)
    assert len(all_rows) == 2

    jp = _alerts(aenv, query="?country=JP")
    assert [a["country_code"] for a in jp] == ["JP"]
    assert _alerts(aenv, query="?kind=SYNC_REJECTED") == []
    assert [a["severity"] for a in _alerts(aenv, query="?severity=HIGH")] == ["HIGH"]

    aenv.api("POST", f"/api/alerts/{jp[0]['id']}/acknowledge", aenv.token("reviewer"))
    unacked = _alerts(aenv, query="?unacknowledged=true")
    assert len(unacked) == 1
    assert unacked[0]["country_code"] == "ID"


def test_list_is_newest_first_and_limit_is_applied(aenv: Env) -> None:
    _verified(aenv, country_code="ID")
    _verified(aenv, country_code="ID")
    _verified(aenv, country_code="ID")
    rows = _alerts(aenv)
    stamps = ["2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z"]
    for row, stamp in zip(sorted(rows, key=lambda a: a["id"]), stamps):
        _set_created_at(aenv, "alerts", row["id"], stamp)
    ordered = _alerts(aenv, query="?limit=200")
    assert [a["created_at"] for a in ordered] == sorted(stamps, reverse=True)
    assert len(_alerts(aenv, query="?limit=1")) == 1


def test_list_rejects_bad_filters_and_limits(aenv: Env) -> None:
    assert aenv.api("GET", "/api/alerts?kind=VOLCANO", aenv.token("viewer")).status_code == 422
    assert aenv.api("GET", "/api/alerts?country=ZZ", aenv.token("viewer")).status_code == 422
    assert aenv.api("GET", "/api/alerts?limit=201", aenv.token("viewer")).status_code == 422
    assert aenv.api("GET", "/api/alerts", None).status_code == 401


# ----- summary -----------------------------------------------------------------------------------

def test_summary_counts_stored_alerts_and_decision_waiting(aenv: Env) -> None:
    _verified(aenv, severity_reported="HIGH", country_code="ID")
    _verified(aenv, severity_reported="CRITICAL", country_code="JP")
    _verified(aenv, severity_reported=None, country_code="ID")
    _submit(aenv, country_code="ID")                     # OBSERVATION: waiting for review
    _propose_mission(aenv)                               # PROPOSED mission: waiting for a decision
    high = next(a for a in _alerts(aenv) if a["severity"] == "HIGH")
    aenv.api("POST", f"/api/alerts/{high['id']}/acknowledge", aenv.token("reviewer"))

    summary = aenv.api("GET", "/api/alerts/summary", aenv.token("analyst")).json()
    assert summary["by_severity"] == {"LOW": 0, "MEDIUM": 1, "HIGH": 0, "CRITICAL": 1}
    assert summary["by_kind"] == {"REPORT_VERIFIED": 2, "THRESHOLD_CROSSED": 0, "DECISION_WAITING": 2,
                                  "SYNC_REJECTED": 0}
    assert summary["decision_waiting"] == {"missions_proposed": 1, "reports_observation": 1}
    assert summary["total"] == 4
    assert sum(summary["by_kind"].values()) == summary["total"]

    jp = aenv.api("GET", "/api/alerts/summary?country=JP", aenv.token("analyst")).json()
    assert jp["by_severity"]["CRITICAL"] == 1
    assert jp["by_kind"]["REPORT_VERIFIED"] == 1
    assert jp["decision_waiting"] == {"missions_proposed": 0, "reports_observation": 0}
    assert jp["total"] == 1


def test_summary_hides_decision_waiting_from_viewers(aenv: Env) -> None:
    _verified(aenv, country_code="ID")
    _submit(aenv, country_code="ID")
    _propose_mission(aenv)
    summary = aenv.api("GET", "/api/alerts/summary", aenv.token("viewer")).json()
    assert summary["by_kind"]["DECISION_WAITING"] == 0
    assert summary["by_kind"]["REPORT_VERIFIED"] == 1


def test_summary_ignores_acknowledged_alerts_in_totals(aenv: Env) -> None:
    _verified(aenv)
    alert_id = _alerts(aenv)[0]["id"]
    aenv.api("POST", f"/api/alerts/{alert_id}/acknowledge", aenv.token("reviewer"))
    summary = aenv.api("GET", "/api/alerts/summary", aenv.token("viewer")).json()
    assert summary["total"] == 0


# ----- time series -------------------------------------------------------------------------------

def test_timeseries_zero_fills_gaps_and_counts_buckets(aenv: Env) -> None:
    now_hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

    def stamp(delta: timedelta) -> str:
        return (now_hour + delta).strftime("%Y-%m-%dT%H:%M:%SZ")

    flood_now = _verified(aenv, hazard_type="FLOOD", country_code="ID")
    quake_now = _submit(aenv, hazard_type="EARTHQUAKE", country_code="ID")
    flood_old = _verified(aenv, hazard_type="FLOOD", country_code="ID")
    _set_created_at(aenv, "reports", flood_now, stamp(timedelta(minutes=10)))
    _set_created_at(aenv, "reports", quake_now, stamp(timedelta(minutes=20)))
    _set_created_at(aenv, "reports", flood_old, stamp(timedelta(hours=-5, minutes=15)))

    response = aenv.api("GET", "/api/timeseries?hours=24", aenv.token("analyst"))
    assert response.status_code == 200, response.text
    buckets = response.json()["buckets"]
    assert len(buckets) == 24
    assert buckets[-1]["hour"] == stamp(timedelta(0))
    assert buckets[0]["hour"] == stamp(timedelta(hours=-23))

    by_hour = {b["hour"]: b for b in buckets}
    now_bucket = by_hour[stamp(timedelta(0))]
    assert now_bucket["reports"] == 2
    assert now_bucket["verified"] == 1
    assert now_bucket["by_hazard"]["FLOOD"] == 1
    assert now_bucket["by_hazard"]["EARTHQUAKE"] == 1
    old_bucket = by_hour[stamp(timedelta(hours=-5))]
    assert old_bucket["reports"] == 1 and old_bucket["verified"] == 1
    assert set(old_bucket["by_hazard"]) == set(HAZARDS)

    empty = [b for b in buckets if b["hour"] not in (stamp(timedelta(0)), stamp(timedelta(hours=-5)))]
    assert len(empty) == 22
    assert all(b["reports"] == 0 and b["verified"] == 0 for b in empty)
    assert all(v == 0 for b in empty for v in b["by_hazard"].values())
    assert sum(b["reports"] for b in buckets) == 3


def test_timeseries_viewer_sees_verified_reports_only(aenv: Env) -> None:
    _verified(aenv, country_code="ID")
    _submit(aenv, country_code="ID")
    viewer = aenv.api("GET", "/api/timeseries?hours=24", aenv.token("viewer")).json()
    analyst = aenv.api("GET", "/api/timeseries?hours=24", aenv.token("analyst")).json()
    assert sum(b["reports"] for b in viewer["buckets"]) == 1
    assert sum(b["reports"] for b in analyst["buckets"]) == 2


def test_timeseries_country_filter_and_hours_validation(aenv: Env) -> None:
    _verified(aenv, country_code="JP")
    _verified(aenv, country_code="ID")
    jp = aenv.api("GET", "/api/timeseries?hours=168&country=JP", aenv.token("viewer")).json()
    assert len(jp["buckets"]) == 168
    assert sum(b["reports"] for b in jp["buckets"]) == 1
    assert aenv.api("GET", "/api/timeseries?hours=5", aenv.token("viewer")).status_code == 422
    assert aenv.api("GET", "/api/timeseries", None).status_code == 401


# ----- privacy and pure functions ----------------------------------------------------------------

def test_no_alert_ever_contains_a_username(aenv: Env) -> None:
    _verified(aenv, country_code="ID")
    _verified(aenv, country_code="JP", severity_reported="LOW")
    _submit(aenv)
    _propose_mission(aenv)
    alert_id = _alerts(aenv)[0]["id"]
    aenv.api("POST", f"/api/alerts/{alert_id}/acknowledge", aenv.token("reviewer"))

    api_text = json.dumps([_alerts(aenv, "reviewer"), aenv.api("GET", "/api/alerts/summary",
                                                                aenv.token("reviewer")).json()]).lower()
    with aenv.db.read() as conn:
        rows = conn.execute("SELECT * FROM alerts").fetchall()
        raw_text = " ".join(" ".join(str(v) for v in dict(r).values() if v is not None) for r in rows).lower()
    for username in SEED_USERS:
        assert username not in api_text, username
        assert username not in raw_text, username


def test_threshold_crossing_is_pure_and_fires_only_on_a_rise_above() -> None:
    crossed = alerts_core.threshold_crossings({"ID": {"FLOOD": 3}}, {"ID": {"FLOOD": 5}}, {"FLOOD": 4},
                                              dataset_id="ds-1")
    assert len(crossed) == 1
    assert crossed[0]["kind"] == "THRESHOLD_CROSSED"
    assert crossed[0]["source_id"] == "ds-1"
    assert crossed[0]["detail"] == {"hazard_type": "FLOOD", "threshold": 4, "before": 3, "after": 5}

    assert alerts_core.threshold_crossings({"ID": {"FLOOD": 5}}, {"ID": {"FLOOD": 6}}, {"FLOOD": 4},
                                           dataset_id="ds-1") == []
    assert alerts_core.threshold_crossings({"ID": {"FLOOD": 2}}, {"ID": {"FLOOD": 3}}, {"FLOOD": 4},
                                           dataset_id="ds-1") == []


def test_report_alert_title_is_capped_and_defaults_apply() -> None:
    alert = alerts_core.report_verified_alert({"id": "r1", "hazard_type": "FLOOD", "location_name": "x" * 300,
                                               "severity_reported": None, "country_code": None})
    assert len(alert["title"]) <= 120
    assert alert["severity"] == "MEDIUM"
    assert alert["country_code"] == "ID"
