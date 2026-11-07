"""Mission proposal and approval (SDD 15.2 to 15.4): roles, validation, separation of duties, audit, and isolation."""

from __future__ import annotations

from typing import Any

from tests.conftest import Env

DISTRICTS = ["Cilandak", "Kemang", "Menteng", "Tebet"]  # distinct values of the district column in CSV_GOOD


def _proposal(source_id: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source_type": "DATASET",
        "source_id": source_id,
        "title": "Flood response: Jakarta south",
        "objective": "Prioritise pump and supply routes to the flooded districts.",
        "area_column": "district",
    }
    body.update(overrides)
    return body


def _propose(env: Env, username: str = "analyst", **overrides: Any) -> dict[str, Any]:
    response = env.api("POST", "/api/missions", env.token(username), json=_proposal(env.approved_dataset(), **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _decide(env: Env, mission_id: str, username: str, decision: str = "approve", note: str | None = None) -> Any:
    body: dict[str, Any] = {"decision": decision}
    if note is not None:
        body["note"] = note
    return env.api("POST", f"/api/missions/{mission_id}/decision", env.token(username), json=body)


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


def _agent_task_count(env: Env) -> int:
    with env.db.read() as conn:
        return conn.execute("SELECT COUNT(*) FROM agent_tasks").fetchone()[0]


# ----- proposal ----------------------------------------------------------------------------------

def test_analyst_proposes_mission_with_target_areas_read_from_data(env: Env) -> None:
    mission = _propose(env)
    assert mission["status"] == "PROPOSED"
    assert mission["target_areas"] == DISTRICTS
    assert mission["source"]["type"] == "DATASET"
    assert mission["proposer"]["username"] == "analyst"
    assert mission["decision"] is None
    assert mission["approved_content_sha256"] is None


def test_viewer_cannot_propose(env: Env) -> None:
    response = env.api("POST", "/api/missions", env.token("viewer"), json=_proposal(env.approved_dataset()))
    assert response.status_code == 403
    assert _error_code(response) == "FORBIDDEN"


def test_unauthenticated_proposal_is_refused(env: Env) -> None:
    response = env.api("POST", "/api/missions", None, json=_proposal(env.approved_dataset()))
    assert response.status_code == 401


def test_dataset_must_be_approved(env: Env) -> None:
    pending = env.upload("analyst").json()["id"]
    response = env.api("POST", "/api/missions", env.token("analyst"), json=_proposal(pending))
    assert response.status_code == 409
    assert _error_code(response) == "INVALID_STATE"


def test_unknown_dataset_is_not_found(env: Env) -> None:
    response = env.api("POST", "/api/missions", env.token("analyst"),
                       json=_proposal("00000000-0000-4000-8000-000000000000"))
    assert response.status_code == 404


def test_area_column_is_required_and_must_exist_in_the_data(env: Env) -> None:
    dataset_id = env.approved_dataset()
    missing = env.api("POST", "/api/missions", env.token("analyst"),
                      json=_proposal(dataset_id, area_column=None))
    assert missing.status_code == 422

    unknown = env.api("POST", "/api/missions", env.token("analyst"),
                      json=_proposal(dataset_id, area_column="invented_column"))
    assert unknown.status_code == 422
    assert _error_code(unknown) == "VALIDATION_FAILED"


def test_empty_cells_never_become_target_areas(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = env.api("POST", "/api/missions", env.token("analyst"),
                       json=_proposal(dataset_id, area_column="reported_at"))
    assert response.status_code == 201
    # Empty cells are never turned into a target area.
    assert "" not in response.json()["target_areas"]
    assert all(area.strip() for area in response.json()["target_areas"])


def test_text_fields_are_validated(env: Env) -> None:
    dataset_id = env.approved_dataset()
    for overrides in ({"title": "   "}, {"title": "x" * 121}, {"objective": ""}, {"objective": "x" * 1001},
                      {"title": "Bad\x00title"}):
        response = env.api("POST", "/api/missions", env.token("analyst"), json=_proposal(dataset_id, **overrides))
        assert response.status_code == 422, overrides


def test_unknown_fields_are_rejected(env: Env) -> None:
    response = env.api("POST", "/api/missions", env.token("analyst"),
                       json=_proposal(env.approved_dataset(), status="APPROVED"))
    assert response.status_code == 422


def test_mission_from_verified_report_uses_its_named_place(env: Env) -> None:
    report = env.api("POST", "/api/reports", env.token("analyst"), json={
        "hazard_type": "FLOOD", "location_name": "Kemang", "latitude": None, "longitude": None,
    }).json()
    not_yet = env.api("POST", "/api/missions", env.token("analyst"), json={
        "source_type": "REPORT", "source_id": report["id"], "title": "Road check", "objective": "Check the road."})
    assert not_yet.status_code == 409

    env.api("POST", f"/api/reports/{report['id']}/review", env.token("reviewer"), json={"decision": "approve"})
    response = env.api("POST", "/api/missions", env.token("analyst"), json={
        "source_type": "REPORT", "source_id": report["id"], "title": "Road check", "objective": "Check the road."})
    assert response.status_code == 201
    assert response.json()["target_areas"] == ["Kemang"]
    assert response.json()["source"] == {"type": "REPORT", "id": report["id"]}


def test_report_without_named_place_or_with_area_column_is_refused(env: Env) -> None:
    unnamed = env.api("POST", "/api/reports", env.token("analyst"), json={
        "hazard_type": "SMOKE", "latitude": -6.2, "longitude": 106.8}).json()
    env.api("POST", f"/api/reports/{unnamed['id']}/review", env.token("reviewer"), json={"decision": "approve"})
    response = env.api("POST", "/api/missions", env.token("analyst"), json={
        "source_type": "REPORT", "source_id": unnamed["id"], "title": "Smoke", "objective": "Assess smoke."})
    assert response.status_code == 422

    named = env.api("POST", "/api/reports", env.token("analyst"), json={
        "hazard_type": "SMOKE", "location_name": "Tebet"}).json()
    env.api("POST", f"/api/reports/{named['id']}/review", env.token("reviewer"), json={"decision": "approve"})
    with_column = env.api("POST", "/api/missions", env.token("analyst"), json={
        "source_type": "REPORT", "source_id": named["id"], "title": "Smoke", "objective": "Assess smoke.",
        "area_column": "district"})
    assert with_column.status_code == 422


# ----- decision and separation of duties ---------------------------------------------------------

def test_proposer_cannot_approve_their_own_mission(env: Env) -> None:
    mission = _propose(env, username="approver")
    response = _decide(env, mission["id"], "approver")
    assert response.status_code == 403
    assert _error_code(response) == "SELF_APPROVAL_NOT_ALLOWED"
    assert env.api("GET", f"/api/missions/{mission['id']}", env.token("approver")).json()["status"] == "PROPOSED"


def test_only_approver_or_admin_may_decide(env: Env) -> None:
    mission = _propose(env)
    for username in ("analyst", "reviewer", "viewer"):
        response = _decide(env, mission["id"], username)
        assert response.status_code == 403, username
        assert _error_code(response) == "FORBIDDEN"


def test_approver_approves_and_the_record_is_complete(env: Env) -> None:
    mission = _propose(env)
    response = _decide(env, mission["id"], "approver", note="Route plan agreed.")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["approved_content_sha256"] == body["content_sha256"]
    assert body["decision"]["decided_by"]["username"] == "approver"
    assert body["decision"]["role"] == "Approver"
    assert body["decision"]["at"]
    assert body["decision"]["note"] == "Route plan agreed."


def test_admin_may_decide_a_mission_proposed_by_someone_else(env: Env) -> None:
    mission = _propose(env)
    response = _decide(env, mission["id"], "admin")
    assert response.status_code == 200
    assert response.json()["decision"]["role"] == "Admin"


def test_approver_may_reject_and_rejected_mission_cannot_be_decided_again(env: Env) -> None:
    mission = _propose(env)
    rejected = _decide(env, mission["id"], "approver", decision="reject", note="Outside scope.")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["approved_content_sha256"] is None

    again = _decide(env, mission["id"], "approver")
    assert again.status_code == 409
    assert _error_code(again) == "INVALID_STATE"


def test_approved_mission_cannot_be_decided_again(env: Env) -> None:
    mission = _propose(env)
    assert _decide(env, mission["id"], "approver").status_code == 200
    again = _decide(env, mission["id"], "admin", decision="reject")
    assert again.status_code == 409
    assert env.api("GET", f"/api/missions/{mission['id']}", env.token("viewer")).json()["status"] == "APPROVED"


def test_decision_note_is_bounded(env: Env) -> None:
    mission = _propose(env)
    response = _decide(env, mission["id"], "approver", note="x" * 501)
    assert response.status_code == 422
    still = env.api("GET", f"/api/missions/{mission['id']}", env.token("analyst")).json()
    assert still["status"] == "PROPOSED"


def test_decision_on_unknown_mission_is_not_found(env: Env) -> None:
    response = _decide(env, "00000000-0000-4000-8000-000000000000", "approver")
    assert response.status_code == 404


def test_content_changed_after_proposal_blocks_approval(env: Env) -> None:
    mission = _propose(env)
    with env.db.transaction() as conn:
        conn.execute("UPDATE missions SET title = 'Changed after proposal' WHERE id = ?", (mission["id"],))
    response = _decide(env, mission["id"], "approver")
    assert response.status_code == 409
    assert _error_code(response) == "CONFLICT"


# ----- visibility --------------------------------------------------------------------------------

def test_viewer_sees_only_approved_missions(env: Env) -> None:
    pending = _propose(env)
    approved = _propose(env)
    _decide(env, approved["id"], "approver")

    viewer_ids = [m["id"] for m in env.api("GET", "/api/missions", env.token("viewer")).json()]
    assert viewer_ids == [approved["id"]]
    analyst_ids = {m["id"] for m in env.api("GET", "/api/missions", env.token("analyst")).json()}
    assert analyst_ids == {pending["id"], approved["id"]}

    assert env.api("GET", f"/api/missions/{pending['id']}", env.token("viewer")).status_code == 404
    assert env.api("GET", f"/api/missions/{approved['id']}", env.token("viewer")).status_code == 200


# ----- isolation and audit -----------------------------------------------------------------------

def test_approval_never_starts_sandbox_or_changes_agent_tasks(env: Env) -> None:
    tasks_before = _agent_task_count(env)
    mission = _propose(env)
    assert _decide(env, mission["id"], "approver").status_code == 200
    assert env.runner.calls == []
    assert _agent_task_count(env) == tasks_before


def test_proposal_and_decisions_write_audit_records(env: Env) -> None:
    mission = _propose(env)
    _decide(env, mission["id"], "approver", note="Looks right.")
    other = _propose(env)
    _decide(env, other["id"], "approver", decision="reject")

    rows = env.audit_rows()
    proposed = [r for r in rows if r["action"] == "mission.proposed" and r["subject"] == mission["id"]]
    approved = [r for r in rows if r["action"] == "mission.approved" and r["subject"] == mission["id"]]
    rejected = [r for r in rows if r["action"] == "mission.rejected" and r["subject"] == other["id"]]
    assert len(proposed) == 1 and proposed[0]["actor"] == "analyst"
    assert proposed[0]["detail"]["content_sha256"] == mission["content_sha256"]
    assert len(approved) == 1 and approved[0]["actor"] == "approver"
    assert approved[0]["detail"]["role"] == "Approver"
    assert approved[0]["detail"]["content_sha256"] == mission["content_sha256"]
    assert len(rejected) == 1

    raw = repr(rows)
    assert "Looks right." not in raw  # decision note is stored as a hash only
    assert "Flood response" not in raw  # title and objective never reach the audit log
