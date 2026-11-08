"""Earthquake and wildfire rule packs (SDD 11, illustrative). Pure-engine tests plus endpoint tests for viewers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.rules import earthquake, wildfire
from app.rules.engine import RulePackError, pack_body_sha256
from tests.conftest import Env

REPO_ROOT = Path(__file__).resolve().parents[2]
EARTHQUAKE_SAMPLE = REPO_ROOT / "datasets" / "samples" / "earthquake_sample.csv"
WILDFIRE_SAMPLE = REPO_ROOT / "datasets" / "samples" / "wildfire_sample.csv"
FLOOD_PACK = REPO_ROOT / "backend" / "app" / "rules" / "flood_v1.json"


def _eq(magnitude: Any, coastal: Any = None) -> dict:
    return {"row": 1, "district": "x", "magnitude": magnitude, "coastal": coastal}


def _wf(distance: Any, wind: Any = None) -> dict:
    return {"row": 1, "district": "x", "distance_km": distance, "wind_kmh": wind}


def _eq_eval(magnitude: Any, coastal: Any = None) -> dict:
    _, pack = earthquake.load_default_earthquake_pack()
    return earthquake.evaluate_earthquake([_eq(magnitude, coastal)], pack)["results"][0]


def _wf_eval(distance: Any, wind: Any = None) -> dict:
    _, pack = wildfire.load_default_wildfire_pack()
    return wildfire.evaluate_wildfire([_wf(distance, wind)], pack)["results"][0]


def _rehash(pack: dict) -> bytes:
    pack["pack_sha256"] = pack_body_sha256(pack)
    return json.dumps(pack).encode("utf-8")


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


# Pack integrity and declarations

def test_default_packs_load_and_hashes_match() -> None:
    for loader, parser in ((earthquake.load_default_earthquake_pack, earthquake.parse_earthquake_pack),
                           (wildfire.load_default_wildfire_pack, wildfire.parse_wildfire_pack)):
        data, pack = loader()
        assert pack["pack_sha256"] == pack_body_sha256(pack)
        assert parser(data) == pack
        assert pack["thresholds_label"] == "illustrative"
        assert "ILLUSTRATIVE" in pack["status_note"]
        assert "SDD 11.3" in pack["status_note"]


def test_packs_declare_countries_as_any_country() -> None:
    assert earthquake.load_default_earthquake_pack()[1]["countries"] == []
    assert wildfire.load_default_wildfire_pack()[1]["countries"] == []


def test_missing_countries_field_is_treated_as_any_country() -> None:
    _, pack = wildfire.load_default_wildfire_pack()
    del pack["countries"]
    loaded = wildfire.parse_wildfire_pack(_rehash(pack))
    assert "countries" not in loaded
    result = wildfire.evaluate_wildfire([_wf(1.0)], loaded)
    assert result["rule_pack"]["countries"] == []


def test_declared_countries_are_exposed_in_the_result() -> None:
    _, pack = earthquake.load_default_earthquake_pack()
    pack["countries"] = ["ID", "JP"]
    loaded = earthquake.parse_earthquake_pack(_rehash(pack))
    assert earthquake.evaluate_earthquake([_eq(5.5)], loaded)["rule_pack"]["countries"] == ["ID", "JP"]


def test_invalid_country_code_is_refused() -> None:
    _, pack = earthquake.load_default_earthquake_pack()
    pack["countries"] = ["Indonesia"]
    with pytest.raises(RulePackError, match="alpha-2"):
        earthquake.parse_earthquake_pack(_rehash(pack))


def test_tampered_earthquake_pack_is_refused() -> None:
    data, _ = earthquake.load_default_earthquake_pack()
    tampered = json.loads(data)
    tampered["rules"][2]["when"]["magnitude_gte"] = 9.0
    with pytest.raises(RulePackError, match="hash mismatch"):
        earthquake.parse_earthquake_pack(json.dumps(tampered).encode("utf-8"))


def test_tampered_wildfire_pack_is_refused() -> None:
    data, _ = wildfire.load_default_wildfire_pack()
    tampered = json.loads(data)
    tampered["rules"][1]["when"]["distance_km_lte"] = 50
    with pytest.raises(RulePackError, match="hash mismatch"):
        wildfire.parse_wildfire_pack(json.dumps(tampered).encode("utf-8"))


def test_pack_of_another_hazard_is_refused() -> None:
    eq_data, _ = earthquake.load_default_earthquake_pack()
    wf_data, _ = wildfire.load_default_wildfire_pack()
    with pytest.raises(RulePackError):
        wildfire.parse_wildfire_pack(eq_data)
    with pytest.raises(RulePackError):
        earthquake.parse_earthquake_pack(wf_data)
    with pytest.raises(RulePackError):
        earthquake.parse_earthquake_pack(FLOOD_PACK.read_bytes())


def test_unrecognised_condition_is_refused() -> None:
    _, pack = wildfire.load_default_wildfire_pack()
    pack["rules"][0]["when"] = {"humidity_gte": 10}
    with pytest.raises(RulePackError, match="not recognised"):
        wildfire.parse_wildfire_pack(_rehash(pack))


# Earthquake thresholds

@pytest.mark.parametrize("magnitude, severity", [
    (4.9, "LOW"),
    (5.0, "LOW"),
    (5.99, "LOW"),
    (6.0, "MEDIUM"),
    (6.99, "MEDIUM"),
    (7.0, "HIGH"),
    (8.2, "HIGH"),
])
def test_earthquake_severity_bands(magnitude: float, severity: str) -> None:
    assert _eq_eval(magnitude)["severity"] == severity


def test_strong_coastal_quake_is_tsunami_check_candidate() -> None:
    row = _eq_eval(7.0, coastal=True)
    assert row["severity"] == "HIGH"
    assert row["flags"] == ["tsunami_check_candidate"]


def test_strong_inland_quake_is_not_flagged() -> None:
    assert _eq_eval(7.4, coastal=False)["flags"] == []


def test_strong_quake_with_unknown_coast_is_not_flagged_but_keeps_severity() -> None:
    row = _eq_eval(7.4, coastal=None)
    assert row["severity"] == "HIGH"
    assert row["flags"] == []


def test_coastal_below_seven_is_not_flagged() -> None:
    assert _eq_eval(6.9, coastal=True)["flags"] == []


def test_unknown_magnitude_is_unknown_never_low() -> None:
    assert _eq_eval(None, coastal=True)["severity"] == "UNKNOWN"


def test_earthquake_csv_coastal_column_is_parsed_and_counted() -> None:
    _, pack = earthquake.load_default_earthquake_pack()
    csv_bytes = (b"district,magnitude,coastal\n"
                 b"Coast A,7.5,true\nCoast B,7.5,false\nCoast C,7.5,\nCoast D,6.0,yes\n")
    result = earthquake.evaluate_earthquake(earthquake.records_from_csv_bytes(csv_bytes), pack)
    assert [row["flags"] for row in result["results"]] == [["tsunami_check_candidate"], [], [], []]
    assert result["flag_counts"] == {"tsunami_check_candidate": 1}
    assert result["counts_by_severity"]["HIGH"] == 3
    assert result["counts_by_severity"]["MEDIUM"] == 1


def test_earthquake_sample_is_deterministic() -> None:
    _, pack = earthquake.load_default_earthquake_pack()
    records = earthquake.records_from_csv_bytes(EARTHQUAKE_SAMPLE.read_bytes())
    first = earthquake.evaluate_earthquake(records, pack)
    assert first == earthquake.evaluate_earthquake(records, pack)
    assert first["rows_evaluated"] == 15
    assert first["counts_by_severity"] == {"HIGH": 2, "LOW": 5, "MEDIUM": 7, "UNKNOWN": 1}
    assert first["data_class"] == "INFERRED_FACT"
    assert first["not_for_operational_use"] is True


# Wildfire thresholds

@pytest.mark.parametrize("distance, severity", [
    (0.8, "HIGH"),
    (2.0, "HIGH"),
    (2.5, "MEDIUM"),
    (5.0, "MEDIUM"),
    (5.1, "LOW"),
    (30.0, "LOW"),
])
def test_wildfire_distance_bands(distance: float, severity: str) -> None:
    assert _wf_eval(distance)["severity"] == severity


def test_smoke_exposure_candidate_at_thresholds() -> None:
    assert _wf_eval(10.0, wind=20.0)["flags"] == ["smoke_exposure_candidate"]


def test_no_smoke_flag_below_wind_threshold() -> None:
    assert _wf_eval(5.0, wind=19.9)["flags"] == []


def test_no_smoke_flag_beyond_distance_threshold() -> None:
    assert _wf_eval(10.1, wind=40.0)["flags"] == []


def test_unknown_wind_keeps_distance_severity_without_flag() -> None:
    row = _wf_eval(1.0, wind=None)
    assert row["severity"] == "HIGH"
    assert row["flags"] == []


def test_unknown_distance_is_unknown_never_low() -> None:
    assert _wf_eval(None, wind=35.0)["severity"] == "UNKNOWN"


def test_wildfire_sample_is_deterministic_and_counted() -> None:
    _, pack = wildfire.load_default_wildfire_pack()
    records = wildfire.records_from_csv_bytes(WILDFIRE_SAMPLE.read_bytes())
    first = wildfire.evaluate_wildfire(records, pack)
    assert first == wildfire.evaluate_wildfire(records, pack)
    assert first["rows_evaluated"] == 12
    assert first["counts_by_severity"] == {"HIGH": 3, "LOW": 5, "MEDIUM": 3, "UNKNOWN": 1}
    assert first["flag_counts"] == {"smoke_exposure_candidate": 4}
    assert first["tool"] == "wildfire_analyzer"


# Missing required columns

def test_earthquake_without_magnitude_column_raises_value_error() -> None:
    with pytest.raises(ValueError):
        earthquake.records_from_csv_bytes(b"district,depth_km\nA,10\n")


def test_wildfire_without_distance_column_raises_value_error() -> None:
    with pytest.raises(ValueError):
        wildfire.records_from_csv_bytes(b"district,wind_kmh\nA,10\n")


# Endpoint (viewer reads, approval, 422 on missing columns)

def _approved_upload(env: Env, data: bytes, filename: str) -> str:
    dataset_id = env.upload("analyst", data=data, filename=filename).json()["id"]
    response = env.api("POST", f"/api/datasets/{dataset_id}/approve", env.token("reviewer"))
    assert response.status_code == 200, response.text
    return dataset_id


def _hazards(env: Env, dataset_id: str, pack: str) -> Any:
    return env.api("GET", "/api/hazards", env.token("viewer"), params={"dataset_id": dataset_id, "pack": pack})


def test_viewer_reads_earthquake_pack_on_approved_dataset(env: Env) -> None:
    dataset_id = _approved_upload(env, EARTHQUAKE_SAMPLE.read_bytes(), "earthquake_sample.csv")
    response = _hazards(env, dataset_id, "earthquake")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tool"] == "earthquake_analyzer"
    assert body["rows_evaluated"] == 15
    assert body["rule_pack"]["countries"] == []
    assert body["dataset"]["id"] == dataset_id


def test_viewer_reads_wildfire_pack_on_approved_dataset(env: Env) -> None:
    dataset_id = _approved_upload(env, WILDFIRE_SAMPLE.read_bytes(), "wildfire_sample.csv")
    response = _hazards(env, dataset_id, "wildfire")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tool"] == "wildfire_analyzer"
    assert body["rows_evaluated"] == 12
    assert body["flag_counts"] == {"smoke_exposure_candidate": 4}
    assert body["rule_pack"]["sha256"] == wildfire.load_default_wildfire_pack()[1]["pack_sha256"]
    assert "ILLUSTRATIVE" in body["thresholds"]["status"]


def test_wildfire_csv_without_distance_is_refused_not_server_error(env: Env) -> None:
    dataset_id = _approved_upload(env, b"district,wind_kmh\nAttica,30\n", "wind_only.csv")
    response = _hazards(env, dataset_id, "wildfire")
    assert response.status_code == 422
    assert _error_code(response) == "VALIDATION_FAILED"


def test_earthquake_csv_without_magnitude_is_refused_not_server_error(env: Env) -> None:
    dataset_id = _approved_upload(env, WILDFIRE_SAMPLE.read_bytes(), "wildfire_sample.csv")
    response = _hazards(env, dataset_id, "earthquake")
    assert response.status_code == 422
    assert _error_code(response) == "VALIDATION_FAILED"


def test_new_packs_are_refused_for_pending_dataset(env: Env) -> None:
    pending = env.upload("analyst", data=WILDFIRE_SAMPLE.read_bytes(), filename="wildfire_sample.csv").json()["id"]
    response = _hazards(env, pending, "wildfire")
    assert response.status_code == 404
    assert _error_code(response) == "NOT_FOUND"
