"""Logistics registry (SDD 15.1, 14.2): roles, validation, filters, audit rows, and planning coverage arithmetic."""

from __future__ import annotations

from typing import Any

import pytest

from app import audit
from app.routes import logistics
from app.util import new_id, utc_now
from tests.conftest import Env

ZERO_ID = "00000000-0000-4000-8000-000000000000"


@pytest.fixture
def lenv(env: Env) -> Env:
    """Makes sure the logistics routes are served. main.py mounts them; this only mounts them if it has not.

    Routes are inserted before the catch-all /api/{rest:path} handler, which would otherwise answer first.
    """
    app = env.app
    if not any(getattr(route, "path", "") == "/api/logistics/shelters" for route in app.routes):
        before = len(app.router.routes)
        app.include_router(logistics.router, prefix="/api")
        added = app.router.routes[before:]
        del app.router.routes[before:]
        app.router.routes[0:0] = added
    return env


def _post(env: Env, path: str, user: str, body: dict[str, Any]) -> Any:
    return env.api("POST", f"/api/logistics/{path}", env.token(user), json=body)


def _patch(env: Env, path: str, user: str, row_id: str, body: dict[str, Any]) -> Any:
    return env.api("PATCH", f"/api/logistics/{path}/{row_id}", env.token(user), json=body)


def _get(env: Env, path: str, query: str = "", user: str = "viewer") -> Any:
    return env.api("GET", f"/api/logistics/{path}{query}", env.token(user))


def _shelter(env: Env, **overrides: Any) -> dict[str, Any]:
    body = {"name": "Kemang Hall", "district": "Kemang", "capacity_people": 5, "status": "OPEN"}
    body.update(overrides)
    response = _post(env, "shelters", "analyst", body)
    assert response.status_code == 201, response.text
    return response.json()


def _audit(env: Env, action: str) -> list[dict[str, Any]]:
    return [row for row in env.audit_rows() if row["action"] == action]


# ---- roles -------------------------------------------------------------------------------------------------

def test_viewer_reads_every_list(lenv: Env) -> None:
    for path in ("shelters", "supplies", "teams", "vehicles"):
        response = _get(lenv, path)
        assert response.status_code == 200, response.text
        assert response.json() == []


def test_viewer_cannot_write_to_any_collection(lenv: Env) -> None:
    shelter = _shelter(lenv)
    checks = [
        _post(lenv, "shelters", "viewer", {"name": "A", "district": "B", "capacity_people": 1}),
        _patch(lenv, "shelters", "viewer", shelter["id"], {"status": "FULL"}),
        _post(lenv, "supplies", "viewer", {"shelter_id": shelter["id"], "item": "water_packs", "quantity": 1}),
        _post(lenv, "teams", "viewer", {"team_type": "RESCUE", "size": 4, "district": "Kemang"}),
        _post(lenv, "vehicles", "viewer", {"vehicle_type": "Truck", "capacity_people": 10, "district": "Kemang"}),
    ]
    for response in checks:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FORBIDDEN"


def test_analyst_creates_and_patches_records(lenv: Env) -> None:
    shelter = _shelter(lenv)
    assert shelter["status"] == "OPEN"
    assert shelter["country_code"] == "ID"  # NULL is shown as the default country
    assert shelter["created_by"] == {"id": shelter["created_by"]["id"]}  # id only, no username

    patched = _patch(lenv, "shelters", "analyst", shelter["id"], {"status": "FULL", "capacity_people": 3})
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "FULL"
    assert patched.json()["capacity_people"] == 3

    team = _post(lenv, "teams", "analyst", {"team_type": "MEDICAL", "size": 6, "district": "Tebet"})
    assert team.status_code == 201, team.text
    assert team.json()["status"] == "AVAILABLE"
    moved = _patch(lenv, "teams", "analyst", team.json()["id"], {"status": "DEPLOYED"})
    assert moved.json()["status"] == "DEPLOYED"

    vehicle = _post(lenv, "vehicles", "analyst", {"vehicle_type": "Truck", "capacity_people": 12, "district": "Tebet"})
    assert vehicle.status_code == 201, vehicle.text
    assert _patch(lenv, "vehicles", "analyst", vehicle.json()["id"], {"district": "Menteng"}).json()["district"] == "Menteng"


def test_response_never_contains_usernames(lenv: Env) -> None:
    _shelter(lenv)
    body = _get(lenv, "shelters").json()
    assert body and "username" not in body[0]["created_by"]
    assert set(body[0]["created_by"]) == {"id"}


def test_patch_on_unknown_record_is_not_found(lenv: Env) -> None:
    response = _patch(lenv, "shelters", "analyst", ZERO_ID, {"status": "FULL"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_supply_for_unknown_shelter_is_not_found(lenv: Env) -> None:
    response = _post(lenv, "supplies", "analyst", {"shelter_id": ZERO_ID, "item": "water_packs", "quantity": 1})
    assert response.status_code == 404


# ---- validation --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"name": "Kemang Hall", "district": "Kemang", "capacity_people": -1},
    {"name": "Kemang Hall", "district": "Kemang", "capacity_people": 5, "status": "CLOSING"},
    {"name": "x" * 121, "district": "Kemang", "capacity_people": 5},
    {"name": "   ", "district": "Kemang", "capacity_people": 5},
    {"name": "Kemang Hall", "district": "Kemang", "capacity_people": 5, "country_code": "XX"},
    {"name": "Kemang Hall", "district": "Kemang", "capacity_people": 5, "latitude": 91},
    {"name": "Kemang Hall", "district": "Kemang", "capacity_people": 5, "username": "x"},
])
def test_bad_shelter_bodies_are_rejected(lenv: Env, body: dict[str, Any]) -> None:
    response = _post(lenv, "shelters", "analyst", body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_negative_supply_quantity_is_rejected(lenv: Env) -> None:
    shelter = _shelter(lenv)
    response = _post(lenv, "supplies", "analyst", {"shelter_id": shelter["id"], "item": "water_packs", "quantity": -1})
    assert response.status_code == 422


def test_unknown_supply_item_is_rejected(lenv: Env) -> None:
    shelter = _shelter(lenv)
    response = _post(lenv, "supplies", "analyst", {"shelter_id": shelter["id"], "item": "fuel", "quantity": 1})
    assert response.status_code == 422


def test_team_and_vehicle_bounds_are_rejected(lenv: Env) -> None:
    assert _post(lenv, "teams", "analyst", {"team_type": "RESCUE", "size": 0, "district": "Kemang"}).status_code == 422
    assert _post(lenv, "teams", "analyst", {"team_type": "BOAT", "size": 2, "district": "Kemang"}).status_code == 422
    assert _post(lenv, "vehicles", "analyst", {"vehicle_type": "Truck", "capacity_people": -4,
                                               "district": "Kemang"}).status_code == 422
    assert _post(lenv, "vehicles", "analyst", {"vehicle_type": "y" * 121, "capacity_people": 4,
                                               "district": "Kemang"}).status_code == 422


def test_patch_rejects_unknown_status_and_empty_body(lenv: Env) -> None:
    shelter = _shelter(lenv)
    assert _patch(lenv, "shelters", "analyst", shelter["id"], {"status": "PAUSED"}).status_code == 422
    assert _patch(lenv, "shelters", "analyst", shelter["id"], {}).status_code == 422
    assert _patch(lenv, "shelters", "analyst", shelter["id"], {"district": None}).status_code == 422


def test_country_codes_are_normalised_and_checked(lenv: Env) -> None:
    shelter = _shelter(lenv, country_code=" my ")
    assert shelter["country_code"] == "MY"
    assert _get(lenv, "shelters", "?country=zz").status_code == 422


# ---- filters, ordering and the row cap ---------------------------------------------------------------------

def test_country_and_district_filters(lenv: Env) -> None:
    default_id = _shelter(lenv, name="Default", district="Kemang")["id"]
    malaysia = _shelter(lenv, name="Subang", district="Subang", country_code="MY")["id"]

    only_my = _get(lenv, "shelters", "?country=MY").json()
    assert [row["id"] for row in only_my] == [malaysia]

    # A NULL country is stored as NULL and matches the default country, ID.
    only_id = _get(lenv, "shelters", "?country=ID").json()
    assert [row["id"] for row in only_id] == [default_id]

    by_district = _get(lenv, "shelters", "?district=KEMANG").json()
    assert [row["id"] for row in by_district] == [default_id]


def test_supply_filters_go_through_the_shelter(lenv: Env) -> None:
    shelter = _shelter(lenv, country_code="MY", district="Subang")
    _post(lenv, "supplies", "analyst", {"shelter_id": shelter["id"], "item": "food_packs", "quantity": 4})
    rows = _get(lenv, "supplies", "?country=MY").json()
    assert len(rows) == 1
    assert rows[0]["item"] == "food_packs" and rows[0]["quantity"] == 4
    assert rows[0]["district"] == "Subang"
    assert _get(lenv, "supplies", "?country=ID").json() == []


def test_lists_are_newest_first(lenv: Env) -> None:
    with lenv.db.transaction() as conn:
        analyst = conn.execute("SELECT id FROM users WHERE username = 'analyst'").fetchone()[0]
        for name, stamp in (("Older", "2026-11-01T08:00:00Z"), ("Newer", "2026-11-02T08:00:00Z")):
            conn.execute("INSERT INTO shelters (id, name, district, capacity_people, status, created_by, "
                         "created_at, updated_at) VALUES (?, ?, 'Kemang', 1, 'OPEN', ?, ?, ?)",
                         (new_id(), name, analyst, stamp, stamp))
    names = [row["name"] for row in _get(lenv, "shelters").json()]
    assert names == ["Newer", "Older"]


def test_list_is_capped_at_500_rows(lenv: Env) -> None:
    with lenv.db.transaction() as conn:
        analyst = conn.execute("SELECT id FROM users WHERE username = 'analyst'").fetchone()[0]
        stamp = utc_now()
        for i in range(501):
            conn.execute("INSERT INTO shelters (id, name, district, capacity_people, status, created_by, "
                         "created_at, updated_at) VALUES (?, ?, 'Kemang', 1, 'OPEN', ?, ?, ?)",
                         (new_id(), f"Shelter {i}", analyst, stamp, stamp))
    assert len(_get(lenv, "shelters").json()) == 500


# ---- audit -------------------------------------------------------------------------------------------------

def test_every_write_is_audited_with_the_actor_and_subject(lenv: Env) -> None:
    shelter = _shelter(lenv)
    created = _audit(lenv, "shelter.created")
    assert len(created) == 1
    assert created[0]["actor"] == "analyst" and created[0]["subject"] == shelter["id"]
    assert created[0]["detail"]["district"] == "Kemang"

    _patch(lenv, "shelters", "analyst", shelter["id"], {"status": "CLOSED"})
    updated = _audit(lenv, "shelter.updated")
    assert updated[0]["detail"]["changed"] == ["status"]

    _post(lenv, "supplies", "analyst", {"shelter_id": shelter["id"], "item": "water_packs", "quantity": 9})
    assert len(_audit(lenv, "supply.upserted")) == 1


def test_audit_detail_stores_no_secrets_and_the_chain_still_verifies(lenv: Env) -> None:
    shelter = _shelter(lenv)
    _post(lenv, "vehicles", "analyst", {"vehicle_type": "Truck", "capacity_people": 4, "district": "Kemang"})
    for row in lenv.audit_rows():
        text = repr(row["detail"]).lower()
        assert "password" not in text and "token" not in text and "session" not in text
    with lenv.db.read() as conn:
        assert audit.verify(conn).valid
    assert shelter["id"]


def test_refused_writes_write_no_audit_row(lenv: Env) -> None:
    lenv.token("viewer")  # logging in writes its own audit row, so take the baseline after it
    before = len(lenv.audit_rows())
    _post(lenv, "teams", "viewer", {"team_type": "RESCUE", "size": 4, "district": "Kemang"})
    assert len(lenv.audit_rows()) == before


# ---- planning coverage (SDD 15.1) --------------------------------------------------------------------------

def _run(env: Env) -> str:
    # Peak snapshot at multiplier 2, hour 0: Kemang 2 affected households, Tebet 1, others 0.
    body = {"dataset_id": env.approved_dataset(), "name": "Coverage base",
            "depth_multiplier": 2.0, "rise_cm_per_hour": 0.0, "hours": 2}
    response = env.api("POST", "/api/simulations", env.token("analyst"), json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _plan(env: Env, run_id: str) -> dict[str, Any]:
    response = env.api("GET", f"/api/planning/allocation?simulation_id={run_id}", env.token("viewer"))
    assert response.status_code == 200, response.text
    return response.json()


def _by_district(coverage: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["district"]: row for row in coverage}


def test_no_logistics_data_gives_an_empty_coverage_and_the_same_plan(lenv: Env) -> None:
    plan = _plan(lenv, _run(lenv))
    assert plan["coverage"] == []
    assert plan["allocations"][0]["district"] == "Kemang"
    # Every field the planner returned before still exists.
    for key in ("data_class", "label", "tool", "basis", "allocations", "totals", "districts_without_need",
                "not_estimated", "assumptions", "not_for_operational_use"):
        assert key in plan


def test_coverage_matches_the_hand_calculation(lenv: Env) -> None:
    # Need from the plan: Kemang 2 households = 8 people, 2 water, 2 food, 1 shelter kit (ceil of 0.5 x 2).
    #                     Tebet 1 household = 4 people, 1 water, 1 food, 1 shelter kit (ceil of 0.5).
    open_kemang = _shelter(lenv, name="Kemang Hall", district="kemang", capacity_people=5)  # counts
    closed_kemang = _shelter(lenv, name="Old school", district="Kemang", capacity_people=100, status="CLOSED")
    _post(lenv, "supplies", "analyst", {"shelter_id": open_kemang["id"], "item": "water_packs", "quantity": 1})
    _post(lenv, "supplies", "analyst", {"shelter_id": open_kemang["id"], "item": "food_packs", "quantity": 3})
    _post(lenv, "supplies", "analyst", {"shelter_id": open_kemang["id"], "item": "medical_kits", "quantity": 7})
    _post(lenv, "supplies", "analyst", {"shelter_id": closed_kemang["id"], "item": "water_packs", "quantity": 9})
    _post(lenv, "vehicles", "analyst", {"vehicle_type": "Truck", "capacity_people": 4, "district": "KEMANG"})
    _post(lenv, "vehicles", "analyst", {"vehicle_type": "Bus", "capacity_people": 50, "district": "Kemang",
                                        "status": "DEPLOYED"})
    _post(lenv, "teams", "analyst", {"team_type": "RESCUE", "size": 4, "district": "Kemang"})
    _post(lenv, "teams", "analyst", {"team_type": "RESCUE", "size": 4, "district": "Kemang", "status": "DEPLOYED"})

    plan = _plan(lenv, _run(lenv))
    coverage = _by_district(plan["coverage"])
    assert [row["district"] for row in plan["coverage"]] == ["Kemang", "Tebet"]

    kemang = coverage["Kemang"]
    assert kemang["need"] == {"people_estimated": 8, "water_packs": 2, "food_packs": 2, "shelter_kits": 1}
    # OPEN shelter 5 + AVAILABLE truck 4 = 9. CLOSED shelter and DEPLOYED bus are left out.
    assert kemang["capacity"] == {"shelter_people": 5, "vehicle_people": 4, "total_people": 9}
    assert kemang["people_gap"] == 0
    # Stock at the open shelter only: water 1, food 3, shelter kits 0, medical 7. Closed-shelter water (9) is left out.
    assert kemang["stock"] == {"water_packs": 1, "food_packs": 3, "shelter_kits": 0, "medical_kits": 7}
    assert kemang["gaps"] == [
        {"item": "water_packs", "need": 2, "stock": 1, "shortfall": 1},
        {"item": "shelter_kits", "need": 1, "stock": 0, "shortfall": 1},
    ]
    assert kemang["teams_available"] == {"RESCUE": 1, "MEDICAL": 0, "TRANSPORT": 0}

    tebet = coverage["Tebet"]
    assert tebet["need"] == {"people_estimated": 4, "water_packs": 1, "food_packs": 1, "shelter_kits": 1}
    assert tebet["capacity"] == {"shelter_people": 0, "vehicle_people": 0, "total_people": 0}
    assert tebet["people_gap"] == 4
    assert [gap["item"] for gap in tebet["gaps"]] == ["water_packs", "food_packs", "shelter_kits"]
    assert all(gap["shortfall"] == gap["need"] for gap in tebet["gaps"])


def test_the_rest_of_the_plan_is_unchanged_by_logistics(lenv: Env) -> None:
    run_id = _run(lenv)
    before = _plan(lenv, run_id)
    _shelter(lenv, district="Tebet", capacity_people=2)
    after = _plan(lenv, run_id)
    assert after["coverage"] != []
    assert {k: v for k, v in before.items() if k != "coverage"} == {k: v for k, v in after.items() if k != "coverage"}
