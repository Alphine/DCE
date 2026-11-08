"""Country scope (docs/offline-global.md section 3): validation, defaults, and the ?country= filter."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from app.countries import ISO_3166_1_ALPHA_2, normalize_country
from tests.conftest import CSV_GOOD, Env


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


def _report(env: Env, username: str = "analyst", **fields: Any) -> Any:
    body: dict[str, Any] = {"hazard_type": "FLOOD", "location_name": "Kemang"}
    body.update(fields)
    return env.api("POST", "/api/reports", env.token(username), json=body)


def _upload_with_country(env: Env, country: str | None, username: str = "analyst") -> Any:
    form = {"country_code": country} if country is not None else {}
    return env.api("POST", "/api/datasets", env.token(username),
                   files={"file": ("flood_incidents.csv", CSV_GOOD, "text/csv")}, data=form)


def _approved_dataset_in(env: Env, country: str | None) -> str:
    response = _upload_with_country(env, country)
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]
    approved = env.api("POST", f"/api/datasets/{dataset_id}/approve", env.token("reviewer"))
    assert approved.status_code == 200, approved.text
    return dataset_id


def test_bundled_list_has_every_current_code() -> None:
    assert len(ISO_3166_1_ALPHA_2) == 249
    for code in ("ID", "PH", "US", "GB", "JP", "BR", "ZA"):
        assert code in ISO_3166_1_ALPHA_2
    # Not ISO 3166-1 alpha-2 codes: user-assigned or retired.
    for code in ("XK", "UK", "EU", "ZZ", "AN"):
        assert code not in ISO_3166_1_ALPHA_2


def test_normalize_accepts_lowercase_and_blank_as_missing() -> None:
    assert normalize_country("ph") == "PH"
    assert normalize_country("  jp ") == "JP"
    assert normalize_country(None) is None
    assert normalize_country("   ") is None


@pytest.mark.parametrize("value", ["ZZ", "XK", "PHL", "P", "1A", 12])
def test_normalize_refuses_unknown_or_malformed_codes(value: Any) -> None:
    with pytest.raises(ValueError):
        normalize_country(value)


def test_report_keeps_its_country_and_defaults_to_id(env: Env) -> None:
    ph = _report(env, country_code="ph")
    assert ph.status_code == 201, ph.text
    assert ph.json()["country_code"] == "PH"

    default = _report(env, location_name="Menteng")
    assert default.status_code == 201
    assert default.json()["country_code"] == "ID"


def test_unknown_country_on_report_is_a_validation_error(env: Env) -> None:
    response = _report(env, country_code="PHL")
    assert response.status_code == 422
    assert _error_code(response) == "VALIDATION_FAILED"


def test_dataset_upload_takes_a_country(env: Env) -> None:
    response = _upload_with_country(env, "ph")
    assert response.status_code == 201, response.text
    assert response.json()["country_code"] == "PH"

    no_country = _upload_with_country(env, None)
    assert no_country.json()["country_code"] == "ID"

    bad = _upload_with_country(env, "ZZ")
    assert bad.status_code == 422
    assert _error_code(bad) == "VALIDATION_FAILED"


def test_mission_takes_its_source_country_unless_given(env: Env) -> None:
    dataset_id = _approved_dataset_in(env, "PH")
    body = {"source_type": "DATASET", "source_id": dataset_id, "title": "Pump routes",
            "objective": "Prioritise pumps.", "area_column": "district"}
    inherited = env.api("POST", "/api/missions", env.token("analyst"), json=body)
    assert inherited.status_code == 201, inherited.text
    assert inherited.json()["country_code"] == "PH"

    explicit = env.api("POST", "/api/missions", env.token("analyst"), json={**body, "country_code": "jp"})
    assert explicit.status_code == 201, explicit.text
    assert explicit.json()["country_code"] == "JP"

    bad = env.api("POST", "/api/missions", env.token("analyst"), json={**body, "country_code": "PHL"})
    assert bad.status_code == 422


def test_simulation_takes_its_dataset_country(env: Env) -> None:
    dataset_id = _approved_dataset_in(env, "BR")
    response = env.api("POST", "/api/simulations", env.token("analyst"),
                       json={"dataset_id": dataset_id, "name": "Scenario"})
    assert response.status_code == 201, response.text
    assert response.json()["country_code"] == "BR"
    assert response.json()["peak"] is not None


def test_report_list_filters_by_country(env: Env) -> None:
    ph = _report(env, country_code="PH").json()["id"]
    default = _report(env, location_name="Menteng").json()["id"]
    us = _report(env, country_code="US").json()["id"]

    only_ph = env.api("GET", "/api/reports?country=PH", env.token("analyst")).json()
    assert [r["id"] for r in only_ph] == [ph]

    # Rows with no country are shown and filtered as ID.
    only_id = env.api("GET", "/api/reports?country=ID", env.token("analyst")).json()
    assert [r["id"] for r in only_id] == [default]
    assert env.api("GET", "/api/reports?country=us", env.token("analyst")).json()[0]["id"] == us

    everything = env.api("GET", "/api/reports", env.token("analyst")).json()
    assert {r["id"] for r in everything} == {ph, default, us}


def test_unknown_country_filter_is_refused_not_empty(env: Env) -> None:
    response = env.api("GET", "/api/reports?country=ZZ", env.token("analyst"))
    assert response.status_code == 422
    assert _error_code(response) == "VALIDATION_FAILED"


def test_dataset_mission_and_simulation_lists_filter_by_country(env: Env) -> None:
    ph_dataset = _approved_dataset_in(env, "PH")
    _approved_dataset_in(env, "US")
    body = {"source_type": "DATASET", "source_id": ph_dataset, "title": "Pump routes",
            "objective": "Prioritise pumps.", "area_column": "district"}
    mission = env.api("POST", "/api/missions", env.token("analyst"), json=body).json()
    run = env.api("POST", "/api/simulations", env.token("analyst"),
                  json={"dataset_id": ph_dataset, "name": "Scenario"}).json()

    datasets = env.api("GET", "/api/datasets?country=PH", env.token("analyst")).json()
    assert {d["country_code"] for d in datasets} == {"PH"}
    assert len(datasets) == 1

    missions = env.api("GET", "/api/missions?country=PH", env.token("analyst")).json()
    assert [m["id"] for m in missions] == [mission["id"]]
    assert env.api("GET", "/api/missions?country=US", env.token("analyst")).json() == []

    runs = env.api("GET", "/api/simulations?country=PH", env.token("analyst")).json()
    assert [r["id"] for r in runs] == [run["id"]]


def test_database_refuses_a_lowercase_or_unknown_stored_code(env: Env) -> None:
    report_id = _report(env, country_code="PH").json()["id"]
    with pytest.raises(sqlite3.IntegrityError), env.db.transaction() as conn:
        conn.execute("UPDATE reports SET country_code = 'ph' WHERE id = ?", (report_id,))
    with pytest.raises(sqlite3.IntegrityError), env.db.transaction() as conn:
        conn.execute("UPDATE reports SET country_code = 'PHL' WHERE id = ?", (report_id,))
