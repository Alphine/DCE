"""Offline sync: POST /api/sync/batch and GET /api/sync/snapshot (docs/offline-global.md sections 2 and 4)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.auth import CurrentUser
from app.countries import DEFAULT_COUNTRY
from app.routes import sync as sync_module
from app.rules import engine
from app.security import API_KEY_HEADER, api_key_hash
from app.util import canonical_json, new_id
from tests.conftest import Env


def _iso(delta: timedelta = timedelta(0)) -> str:
    return (datetime.now(UTC) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _item(kind: str, payload: dict[str, Any], *, made_at: str | None = None, op_id: str | None = None) -> dict:
    return {"op_id": op_id or str(uuid.uuid4()), "kind": kind, "payload": payload,
            "made_at": made_at or _iso()}


def _batch(env: Env, username: str, items: list[dict], client_id: str = "device-test-1") -> Any:
    return env.api("POST", "/api/sync/batch", env.token(username), json={"client_id": client_id, "items": items})


def _results(env: Env, username: str, items: list[dict]) -> list[dict]:
    response = _batch(env, username, items)
    assert response.status_code == 200, response.text
    return response.json()["results"]


def _one(env: Env, username: str, kind: str, payload: dict, **kwargs: Any) -> dict:
    return _results(env, username, [_item(kind, payload, **kwargs)])[0]


def _report(env: Env, username: str = "analyst", **fields: Any) -> dict:
    body: dict[str, Any] = {"hazard_type": "FLOOD", "location_name": "Kemang", "notes": "Water at the gate"}
    body.update(fields)
    response = env.api("POST", "/api/reports", env.token(username), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _verified_report(env: Env) -> dict:
    report = _report(env)
    response = env.api("POST", f"/api/reports/{report['id']}/review", env.token("reviewer"),
                       json={"decision": "approve"})
    assert response.status_code == 200, response.text
    return response.json()


def _mission(env: Env, username: str = "analyst") -> dict:
    dataset_id = env.approved_dataset()
    response = env.api("POST", "/api/missions", env.token(username), json={
        "source_type": "DATASET", "source_id": dataset_id, "title": "Pump routes",
        "objective": "Prioritise pumps.", "area_column": "district"})
    assert response.status_code == 201, response.text
    return response.json()


def _report_decision(report: dict, decision: str = "approve", **overrides: Any) -> dict:
    payload = {"report_id": report["id"], "decision": decision, "content_sha256": report["content_sha256"],
               "note": None}
    payload.update(overrides)
    return payload


def _mission_decision(mission: dict, decision: str = "approve", **overrides: Any) -> dict:
    payload = {"mission_id": mission["id"], "decision": decision, "content_sha256": mission["content_sha256"],
               "note": None}
    payload.update(overrides)
    return payload


def _status(env: Env, path: str, username: str = "analyst") -> str:
    return env.api("GET", path, env.token(username)).json()["status"]


def _audit_for(env: Env, action: str, subject: str) -> dict:
    rows = [r for r in env.audit_rows() if r["action"] == action and r["subject"] == subject]
    assert rows, f"no audit row {action} for {subject}"
    return rows[-1]["detail"]


def _report_count(env: Env) -> int:
    with env.db.read() as conn:
        return conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]


# --- Idempotency and isolation -------------------------------------------------------------------------------------


def test_replayed_batch_returns_duplicate_and_changes_nothing(env: Env) -> None:
    item = _item("REPORT_CREATE", {"hazard_type": "FLOOD", "location_name": "Kemang"})
    first = _results(env, "analyst", [item])[0]
    assert first["status"] == "APPLIED"
    assert first["data"]["status"] == "OBSERVATION"

    replay = _results(env, "analyst", [item])[0]
    assert replay["status"] == "DUPLICATE"
    assert replay["code"] == "DUPLICATE"
    assert replay["result"]["status"] == "APPLIED"
    assert replay["result"]["data"]["id"] == first["data"]["id"]
    assert _report_count(env) == 1


def test_a_rejected_op_stays_rejected_on_replay(env: Env) -> None:
    item = _item("REPORT_CREATE", {"hazard_type": "NOT_A_HAZARD"})
    first = _results(env, "analyst", [item])[0]
    assert first["status"] == "REJECTED"
    assert first["code"] == "VALIDATION_FAILED"

    replay = _results(env, "analyst", [item])[0]
    assert replay["status"] == "DUPLICATE"
    assert replay["result"]["status"] == "REJECTED"


def test_op_id_used_by_another_account_is_refused(env: Env) -> None:
    item = _item("REPORT_CREATE", {"hazard_type": "FLOOD"})
    assert _results(env, "analyst", [item])[0]["status"] == "APPLIED"
    other = _results(env, "reviewer", [item])[0]
    assert other["status"] == "REJECTED"
    assert other["code"] == "OP_ID_IN_USE"
    assert _report_count(env) == 1


def test_one_bad_item_does_not_block_the_others(env: Env) -> None:
    # The approver may create reports too (Approver is above Analyst), so one batch can mix kinds.
    missing = {"id": str(uuid.uuid4()), "content_sha256": "0" * 64}
    items = [
        _item("REPORT_CREATE", {"hazard_type": "NOT_A_HAZARD"}),
        _item("REPORT_CREATE", {"hazard_type": "FLOOD", "location_name": "Menteng"}),
        _item("MISSION_DECISION", _mission_decision(missing)),
        _item("NO_SUCH_KIND", {}),
        _item("REPORT_CREATE", {"hazard_type": "TSUNAMI"}),
    ]
    results = _results(env, "approver", items)
    assert [r["status"] for r in results] == ["REJECTED", "APPLIED", "REJECTED", "REJECTED", "APPLIED"]
    assert [r["code"] for r in results] == ["VALIDATION_FAILED", "APPLIED", "NOT_FOUND", "UNKNOWN_KIND", "APPLIED"]
    assert [r["op_id"] for r in results] == [i["op_id"] for i in items]
    assert _report_count(env) == 2


def test_results_keep_the_order_of_the_items(env: Env) -> None:
    items = [_item("REPORT_CREATE", {"hazard_type": "FLOOD", "location_name": f"Place {n}"}) for n in range(4)]
    results = _results(env, "analyst", items)
    assert [r["op_id"] for r in results] == [i["op_id"] for i in items]


def test_op_id_must_be_a_uuid(env: Env) -> None:
    result = _results(env, "analyst", [_item("REPORT_CREATE", {"hazard_type": "FLOOD"}, op_id="not-a-uuid")])[0]
    assert result["status"] == "REJECTED"
    assert result["code"] == "VALIDATION_FAILED"


def test_viewer_items_are_role_checked_one_by_one(env: Env) -> None:
    viewer_report = _one(env, "viewer", "REPORT_CREATE", {"hazard_type": "FLOOD"})
    assert viewer_report["status"] == "REJECTED"
    assert viewer_report["code"] == "FORBIDDEN"

    analyst_report = _one(env, "analyst", "REPORT_CREATE", {"hazard_type": "FLOOD"})
    assert analyst_report["status"] == "APPLIED"


def test_viewer_cannot_decide_offline(env: Env) -> None:
    report = _report(env)
    result = _one(env, "viewer", "REPORT_DECISION", _report_decision(report))
    assert result["status"] == "REJECTED"
    assert result["code"] == "FORBIDDEN"


# --- Envelope limits and authentication ----------------------------------------------------------------------------


def test_more_than_200_items_is_refused_with_422(env: Env) -> None:
    items = [_item("UNKNOWN", {}) for _ in range(201)]
    response = _batch(env, "analyst", items)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_200_items_is_accepted(env: Env) -> None:
    items = [_item("UNKNOWN", {}) for _ in range(200)]
    results = _results(env, "analyst", items)
    assert len(results) == 200


def test_a_body_over_1_mb_is_refused_with_422(env: Env) -> None:
    body = {"client_id": "device-test-1", "items": [], "padding": "x" * 1_000_001}
    response = env.api("POST", "/api/sync/batch", env.token("analyst"), json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_api_key_is_refused_on_batch(env: Env) -> None:
    raw_key = "dce_test_key_for_sync_" + uuid.uuid4().hex
    with env.db.transaction() as conn:
        user_id = conn.execute("SELECT id FROM users WHERE username = 'analyst'").fetchone()[0]
        conn.execute("INSERT INTO api_keys (id, user_id, key_hash, scope, expires_at, created_at, revoked_at) "
                     "VALUES (?, ?, ?, 'full', NULL, ?, NULL)", (new_id(), user_id, api_key_hash(raw_key), _iso()))

    key_only = env.api("POST", "/api/sync/batch", headers={API_KEY_HEADER: raw_key},
                       json={"client_id": "device-test-1", "items": [_item("REPORT_CREATE", {"hazard_type": "FLOOD"})]})
    assert key_only.status_code == 401
    assert key_only.json()["error"]["code"] == "UNAUTHENTICATED"
    assert _report_count(env) == 0

    # The same key still works on an ordinary read, so the refusal is about the batch route only.
    assert env.api("GET", "/api/reports", headers={API_KEY_HEADER: raw_key}).status_code == 200


def test_batch_needs_a_session(env: Env) -> None:
    response = env.api("POST", "/api/sync/batch",
                       json={"client_id": "device-test-1", "items": []})
    assert response.status_code == 401


def test_disabled_user_cannot_send_the_queue(env: Env) -> None:
    token = env.token("analyst")
    with env.db.transaction() as conn:
        conn.execute("UPDATE users SET status = 'disabled' WHERE username = 'analyst'")
    response = env.api("POST", "/api/sync/batch", token,
                       json={"client_id": "device-test-1", "items": [_item("REPORT_CREATE", {"hazard_type": "FLOOD"})]})
    assert response.status_code == 401
    assert _report_count(env) == 0


# --- Report creation and decisions ---------------------------------------------------------------------------------


def test_offline_report_is_stored_with_country_and_audited(env: Env) -> None:
    item = _item("REPORT_CREATE", {"hazard_type": "FLOOD", "location_name": "Makati", "country_code": "ph"},
                 made_at=_iso(timedelta(hours=-1)))
    result = _results(env, "analyst", [item])[0]
    assert result["status"] == "APPLIED"
    report = env.api("GET", f"/api/reports/{result['data']['id']}", env.token("analyst")).json()
    assert report["country_code"] == "PH"
    detail = _audit_for(env, "report.submitted", report["id"])
    assert detail["offline"] is True
    assert detail["made_offline_at"] == item["made_at"]


def test_offline_report_approval_is_applied_and_audited_with_both_times(env: Env) -> None:
    report = _report(env)
    made_at = _iso(timedelta(hours=-2))
    result = _one(env, "reviewer", "REPORT_DECISION", _report_decision(report), made_at=made_at)
    assert result["status"] == "APPLIED"
    assert _status(env, f"/api/reports/{report['id']}", "reviewer") == "VERIFIED_OBSERVATION"

    detail = _audit_for(env, "report.reviewed", report["id"])
    assert detail["decided_offline_at"] == made_at
    assert detail["synced_at"]
    assert detail["offline"] is True


def test_check_2_report_state_changed_since_the_decision(env: Env) -> None:
    report = _report(env)
    env.api("POST", f"/api/reports/{report['id']}/review", env.token("reviewer"), json={"decision": "reject"})
    result = _one(env, "reviewer", "REPORT_DECISION", _report_decision(report))
    assert result["status"] == "REJECTED"
    assert result["code"] == "ITEM_STATE_CHANGED"
    assert _status(env, f"/api/reports/{report['id']}", "reviewer") == "REJECTED"


def test_check_3_content_hash_must_match(env: Env) -> None:
    report = _report(env)
    result = _one(env, "reviewer", "REPORT_DECISION", _report_decision(report, content_sha256="0" * 64))
    assert result["status"] == "REJECTED"
    assert result["code"] == "CONTENT_CHANGED"
    assert _status(env, f"/api/reports/{report['id']}", "reviewer") == "OBSERVATION"


def test_check_4_reviewer_cannot_decide_their_own_report(env: Env) -> None:
    own = env.api("POST", "/api/reports", env.token("reviewer"),
                  json={"hazard_type": "FLOOD", "location_name": "Kemang"}).json()
    result = _one(env, "reviewer", "REPORT_DECISION", _report_decision(own))
    assert result["status"] == "REJECTED"
    assert result["code"] == "SELF_APPROVAL_NOT_ALLOWED"
    assert _status(env, f"/api/reports/{own['id']}", "reviewer") == "OBSERVATION"


def test_check_1_role_is_checked_at_sync_time(env: Env) -> None:
    report = _report(env)
    result = _one(env, "analyst", "REPORT_DECISION", _report_decision(report))
    assert result["status"] == "REJECTED"
    assert result["code"] == "FORBIDDEN"


def test_check_1_user_must_still_be_active(env: Env) -> None:
    reviewer = _user(env, "reviewer")
    with env.db.transaction() as conn:
        conn.execute("UPDATE users SET status = 'disabled' WHERE username = 'reviewer'")
    with env.db.read() as conn, pytest.raises(sync_module._Rejected) as caught:
        sync_module._fresh_user(conn, reviewer, "Reviewer")
    assert caught.value.code == "USER_INACTIVE"


def test_check_5_decision_older_than_72_hours_is_rejected(env: Env) -> None:
    report = _report(env)
    result = _one(env, "reviewer", "REPORT_DECISION", _report_decision(report),
                  made_at=_iso(timedelta(hours=-73)))
    assert result["status"] == "REJECTED"
    assert result["code"] == "DECISION_EXPIRED"
    assert _status(env, f"/api/reports/{report['id']}", "reviewer") == "OBSERVATION"


def test_check_5_decision_at_71_hours_is_applied(env: Env) -> None:
    report = _report(env)
    result = _one(env, "reviewer", "REPORT_DECISION", _report_decision(report),
                  made_at=_iso(timedelta(hours=-71)))
    assert result["status"] == "APPLIED"


def test_check_5_decision_from_the_future_is_rejected(env: Env) -> None:
    report = _report(env)
    result = _one(env, "reviewer", "REPORT_DECISION", _report_decision(report),
                  made_at=_iso(timedelta(hours=1)))
    assert result["status"] == "REJECTED"
    assert result["code"] == "MADE_AT_IN_FUTURE"


def test_made_at_must_carry_a_time_zone(env: Env) -> None:
    result = _one(env, "analyst", "REPORT_CREATE", {"hazard_type": "FLOOD"}, made_at="2026-11-08T10:00:00")
    assert result["status"] == "REJECTED"
    assert result["code"] == "VALIDATION_FAILED"


# --- Missions ------------------------------------------------------------------------------------------------------


def test_offline_mission_proposal_is_applied(env: Env) -> None:
    dataset_id = env.approved_dataset()
    result = _one(env, "analyst", "MISSION_PROPOSE", {
        "source_type": "DATASET", "source_id": dataset_id, "title": "Pump routes",
        "objective": "Prioritise pumps.", "area_column": "district"})
    assert result["status"] == "APPLIED"
    assert result["data"]["status"] == "PROPOSED"


def test_offline_mission_approval_is_applied_with_both_times(env: Env) -> None:
    mission = _mission(env)
    made_at = _iso(timedelta(hours=-3))
    result = _one(env, "approver", "MISSION_DECISION", _mission_decision(mission), made_at=made_at)
    assert result["status"] == "APPLIED"
    assert _status(env, f"/api/missions/{mission['id']}", "approver") == "APPROVED"
    detail = _audit_for(env, "mission.approved", mission["id"])
    assert detail["decided_offline_at"] == made_at
    assert detail["synced_at"]
    assert detail["content_sha256"] == mission["content_sha256"]


def test_check_1_mission_decision_needs_the_approver_role(env: Env) -> None:
    mission = _mission(env)
    result = _one(env, "analyst", "MISSION_DECISION", _mission_decision(mission))
    assert result["status"] == "REJECTED"
    assert result["code"] == "FORBIDDEN"


def test_check_2_mission_state_changed_since_the_decision(env: Env) -> None:
    mission = _mission(env)
    env.api("POST", f"/api/missions/{mission['id']}/approve", env.token("approver"), json={})
    result = _one(env, "approver", "MISSION_DECISION", _mission_decision(mission, "reject"))
    assert result["status"] == "REJECTED"
    assert result["code"] == "ITEM_STATE_CHANGED"
    assert _status(env, f"/api/missions/{mission['id']}", "approver") == "APPROVED"


def test_check_3_mission_content_hash_must_match(env: Env) -> None:
    mission = _mission(env)
    result = _one(env, "approver", "MISSION_DECISION", _mission_decision(mission, content_sha256="f" * 64))
    assert result["status"] == "REJECTED"
    assert result["code"] == "CONTENT_CHANGED"
    assert _status(env, f"/api/missions/{mission['id']}", "approver") == "PROPOSED"


def test_check_4_proposer_cannot_approve_their_own_mission(env: Env) -> None:
    mission = _mission(env, username="approver")
    result = _one(env, "approver", "MISSION_DECISION", _mission_decision(mission))
    assert result["status"] == "REJECTED"
    assert result["code"] == "SELF_APPROVAL_NOT_ALLOWED"
    assert _status(env, f"/api/missions/{mission['id']}", "approver") == "PROPOSED"


def test_check_5_mission_decision_older_than_72_hours_is_rejected(env: Env) -> None:
    mission = _mission(env)
    result = _one(env, "approver", "MISSION_DECISION", _mission_decision(mission),
                  made_at=_iso(timedelta(hours=-80)))
    assert result["status"] == "REJECTED"
    assert result["code"] == "DECISION_EXPIRED"
    assert _status(env, f"/api/missions/{mission['id']}", "approver") == "PROPOSED"


def test_rejected_offline_decision_is_recorded_for_the_device(env: Env) -> None:
    mission = _mission(env)
    item = _item("MISSION_DECISION", _mission_decision(mission, content_sha256="a" * 64))
    first = _results(env, "approver", [item])[0]
    assert first["status"] == "REJECTED"
    # Replaying the same op_id returns the stored rejection, so the device can show the reason.
    replay = _results(env, "approver", [item])[0]
    assert replay["status"] == "DUPLICATE"
    assert replay["result"]["code"] == "CONTENT_CHANGED"


# --- Simulations ---------------------------------------------------------------------------------------------------


def _pack_sha() -> str:
    return engine.load_default_pack()[1][engine.PACK_HASH_FIELD]


def _simulation_payload(dataset_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"dataset_id": dataset_id, "name": "Offline scenario", "pack": "flood",
                               "pack_sha256": _pack_sha(), "depth_multiplier": 1.0, "rise_cm_per_hour": 0.0,
                               "hours": 24}
    payload.update(overrides)
    return payload


def test_offline_simulation_runs_against_the_matching_pack(env: Env) -> None:
    dataset_id = env.approved_dataset()
    result = _one(env, "analyst", "SIMULATION_CREATE", _simulation_payload(dataset_id))
    assert result["status"] == "APPLIED"
    run = env.api("GET", f"/api/simulations/{result['data']['id']}", env.token("analyst")).json()
    assert run["output_sha256"] == result["data"]["output_sha256"]


def test_simulation_is_refused_when_the_pack_hash_differs(env: Env) -> None:
    dataset_id = env.approved_dataset()
    result = _one(env, "analyst", "SIMULATION_CREATE", _simulation_payload(dataset_id, pack_sha256="0" * 64))
    assert result["status"] == "REJECTED"
    assert result["code"] == "PACK_MISMATCH"


def test_simulation_needs_an_approved_dataset(env: Env) -> None:
    dataset_id = env.upload("analyst").json()["id"]
    result = _one(env, "analyst", "SIMULATION_CREATE", _simulation_payload(dataset_id))
    assert result["status"] == "REJECTED"
    assert result["code"] == "NOT_FOUND"


# --- Snapshot ------------------------------------------------------------------------------------------------------


def _snapshot(env: Env, username: str = "viewer", query: str = "") -> Any:
    return env.api("GET", f"/api/sync/snapshot{query}", env.token(username))


def test_snapshot_sections_have_stable_etags_that_track_their_content(env: Env) -> None:
    _verified_report(env)
    first = _snapshot(env).json()
    second = _snapshot(env).json()
    assert set(first["sections"]) == {"reports", "datasets", "missions", "simulations"}
    for name, section in first["sections"].items():
        assert len(section["etag"]) == 64, name
        assert section["etag"] == second["sections"][name]["etag"], name

    _verified_report(env)
    third = _snapshot(env).json()
    assert third["sections"]["reports"]["etag"] != first["sections"]["reports"]["etag"]
    assert third["sections"]["datasets"]["etag"] == first["sections"]["datasets"]["etag"]


def test_snapshot_etag_is_sha256_of_the_section_items(env: Env) -> None:
    _verified_report(env)
    section = _snapshot(env).json()["sections"]["reports"]
    expected = hashlib.sha256(canonical_json(section["items"]).encode("utf-8")).hexdigest()
    assert section["etag"] == expected


def test_viewer_snapshot_has_verified_reports_only(env: Env) -> None:
    verified = _verified_report(env)
    pending = _report(env, location_name="Menteng")
    viewer_ids = {r["id"] for r in _snapshot(env, "viewer").json()["sections"]["reports"]["items"]}
    analyst_ids = {r["id"] for r in _snapshot(env, "analyst").json()["sections"]["reports"]["items"]}
    assert viewer_ids == {verified["id"]}
    assert analyst_ids == {verified["id"], pending["id"]}


def test_snapshot_country_filter(env: Env) -> None:
    ph = _report(env, country_code="PH")
    env.api("POST", f"/api/reports/{ph['id']}/review", env.token("reviewer"), json={"decision": "approve"})
    default = _report(env, location_name="Menteng")
    env.api("POST", f"/api/reports/{default['id']}/review", env.token("reviewer"), json={"decision": "approve"})

    ph_only = _snapshot(env, "viewer", "?country=PH").json()
    assert ph_only["country"] == "PH"
    assert [r["id"] for r in ph_only["sections"]["reports"]["items"]] == [ph["id"]]

    id_only = _snapshot(env, "viewer", f"?country={DEFAULT_COUNTRY}").json()
    assert [r["id"] for r in id_only["sections"]["reports"]["items"]] == [default["id"]]

    bad = _snapshot(env, "viewer", "?country=ZZ")
    assert bad.status_code == 422


def test_snapshot_needs_a_signed_in_user(env: Env) -> None:
    assert env.api("GET", "/api/sync/snapshot").status_code == 401


def _user(env: Env, username: str) -> CurrentUser:
    with env.db.read() as conn:
        row = conn.execute("SELECT u.id, u.username, r.role FROM users u JOIN user_roles r ON r.user_id = u.id "
                           "WHERE u.username = ?", (username,)).fetchone()
    return CurrentUser(id=row["id"], username=row["username"], role=row["role"])
