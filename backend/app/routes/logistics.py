"""Logistics registry: shelters, supply stock, teams and vehicles (SDD 15.1, 14.2).

Viewers read. Analysts write. Each write appends one audit row in the same transaction and stores only counts,
names, districts and statuses. Lists are capped at 500 rows, newest first. The coverage helper below is used by
GET /api/planning/allocation to compare the need with stock and capacity by district.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app import audit
from app.auth import CurrentUser, current_user, require_role
from app.container import services_of
from app.countries import (
    country_filter,
    country_or_default,
    country_query,
    normalize_country,
)
from app.errors import AppError
from app.util import new_id, utc_now

router = APIRouter(prefix="/logistics", tags=["logistics"])

MAX_ROWS = 500
SUPPLY_ITEMS = ("water_packs", "food_packs", "shelter_kits", "medical_kits")
# Items the flood pack estimates a need for. Medical kits have no need figure yet, so they are not gap-checked.
NEED_ITEMS = ("water_packs", "food_packs", "shelter_kits")

ShelterStatus = Literal["OPEN", "FULL", "CLOSED"]
TeamType = Literal["RESCUE", "MEDICAL", "TRANSPORT"]
AvailStatus = Literal["AVAILABLE", "DEPLOYED", "UNAVAILABLE"]
SupplyItem = Literal["water_packs", "food_packs", "shelter_kits", "medical_kits"]
Text120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Quantity = Annotated[int, Field(ge=0, le=10_000_000)]


def _country(value: str | None) -> str | None:
    return normalize_country(value)


# ---- request models (extra="forbid": unknown fields are a 422) ----------------------------------------------

class ShelterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Text120
    district: Text120
    country_code: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    capacity_people: Quantity
    status: ShelterStatus = "OPEN"

    @field_validator("country_code")
    @classmethod
    def _cc(cls, value: str | None) -> str | None:
        return _country(value)


class ShelterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Text120 | None = None
    district: Text120 | None = None
    country_code: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    capacity_people: Quantity | None = None
    status: ShelterStatus | None = None

    @field_validator("country_code")
    @classmethod
    def _cc(cls, value: str | None) -> str | None:
        return _country(value)


class SupplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shelter_id: str = Field(min_length=36, max_length=36)
    item: SupplyItem
    quantity: Quantity


class TeamIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_type: TeamType
    size: int = Field(ge=1, le=100_000)
    status: AvailStatus = "AVAILABLE"
    district: Text120
    country_code: str | None = None

    @field_validator("country_code")
    @classmethod
    def _cc(cls, value: str | None) -> str | None:
        return _country(value)


class TeamPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_type: TeamType | None = None
    size: int | None = Field(default=None, ge=1, le=100_000)
    status: AvailStatus | None = None
    district: Text120 | None = None
    country_code: str | None = None

    @field_validator("country_code")
    @classmethod
    def _cc(cls, value: str | None) -> str | None:
        return _country(value)


class VehicleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_type: Text120
    capacity_people: Quantity
    status: AvailStatus = "AVAILABLE"
    district: Text120
    country_code: str | None = None

    @field_validator("country_code")
    @classmethod
    def _cc(cls, value: str | None) -> str | None:
        return _country(value)


class VehiclePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_type: Text120 | None = None
    capacity_people: Quantity | None = None
    status: AvailStatus | None = None
    district: Text120 | None = None
    country_code: str | None = None

    @field_validator("country_code")
    @classmethod
    def _cc(cls, value: str | None) -> str | None:
        return _country(value)


# ---- shared helpers ----------------------------------------------------------------------------------------

NOT_NULL_FIELDS = {"name", "district", "capacity_people", "status", "team_type", "size", "vehicle_type"}


def _changes(body: BaseModel) -> dict[str, Any]:
    """Only the fields the client sent. Explicit nulls are refused for fields that cannot be empty."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise AppError("VALIDATION_FAILED", "Send at least one field to change.")
    for key, value in changes.items():
        if value is None and key in NOT_NULL_FIELDS:
            raise AppError("VALIDATION_FAILED", f"{key} cannot be empty.")
    return changes


def _where(alias: str, country: str | None, district: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    frag, args = country_filter(alias, country_query(country))
    if frag:
        clauses.append(frag)
        params.extend(args)
    if district is not None and district.strip():
        clauses.append(f"lower({alias}.district) = lower(?)")
        params.append(district.strip())
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def _out(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["country_code"] = country_or_default(data.get("country_code"))
    data["created_by"] = {"id": data["created_by"]}
    return data


def _insert(conn: sqlite3.Connection, table: str, values: dict[str, Any], user: CurrentUser) -> str:
    row_id = new_id()
    now = utc_now()
    cols = {**values, "id": row_id, "created_by": user.id, "created_at": now, "updated_at": now}
    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                 tuple(cols.values()))
    return row_id


def _patch(conn: sqlite3.Connection, table: str, row_id: str, changes: dict[str, Any]) -> sqlite3.Row:
    if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)).fetchone() is None:
        raise AppError("NOT_FOUND", "Record not found.")
    assignments = ", ".join(f"{column} = ?" for column in changes)
    conn.execute(f"UPDATE {table} SET {assignments}, updated_at = ? WHERE id = ?",
                 (*changes.values(), utc_now(), row_id))
    return conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()


def _list(request: Request, table: str, alias: str, country: str | None, district: str | None) -> list[dict[str, Any]]:
    where, params = _where(alias, country, district)
    with services_of(request).db.read() as conn:
        rows = conn.execute(f"SELECT * FROM {table} {alias}{where} ORDER BY {alias}.created_at DESC, "
                            f"{alias}.id DESC LIMIT {MAX_ROWS}", tuple(params)).fetchall()
    return [_out(row) for row in rows]


CountryQ = Query(default=None, max_length=2)
DistrictQ = Query(default=None, max_length=120)


# ---- shelters ----------------------------------------------------------------------------------------------

@router.get("/shelters")
def list_shelters(request: Request, country: str | None = CountryQ, district: str | None = DistrictQ,
                  user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    return _list(request, "shelters", "sh", country, district)


@router.post("/shelters", status_code=201)
def create_shelter(body: ShelterIn, request: Request,
                   user: CurrentUser = Depends(require_role("Analyst"))) -> JSONResponse:
    with services_of(request).db.transaction() as conn:
        row_id = _insert(conn, "shelters", body.model_dump(), user)
        audit.append(conn, actor=user.username, action="shelter.created", subject=row_id, detail={
            "district": body.district, "status": body.status, "capacity_people": body.capacity_people,
            "country_code": country_or_default(body.country_code)})
        row = conn.execute("SELECT * FROM shelters WHERE id = ?", (row_id,)).fetchone()
    return JSONResponse(_out(row), status_code=201)


@router.patch("/shelters/{row_id}")
def update_shelter(row_id: str, body: ShelterPatch, request: Request,
                   user: CurrentUser = Depends(require_role("Analyst"))) -> dict[str, Any]:
    changes = _changes(body)
    with services_of(request).db.transaction() as conn:
        row = _patch(conn, "shelters", row_id, changes)
        audit.append(conn, actor=user.username, action="shelter.updated", subject=row_id,
                     detail={"changed": sorted(changes), "values": changes})
    return _out(row)


# ---- supplies ----------------------------------------------------------------------------------------------

@router.get("/supplies")
def list_supplies(request: Request, country: str | None = CountryQ, district: str | None = DistrictQ,
                  user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    # Stock is located by its shelter. With a country or district filter, stock without a shelter is left out.
    where, params = _where("sh", country, district)
    if where:
        where += " AND si.shelter_id IS NOT NULL"
    with services_of(request).db.read() as conn:
        rows = conn.execute(
            "SELECT si.*, sh.name AS shelter_name, sh.district AS district, sh.country_code AS country_code "
            "FROM supply_items si LEFT JOIN shelters sh ON sh.id = si.shelter_id"
            f"{where} ORDER BY si.created_at DESC, si.id DESC LIMIT {MAX_ROWS}", tuple(params)).fetchall()
    return [{**dict(row), "country_code": country_or_default(row["country_code"])} for row in rows]


@router.post("/supplies", status_code=201)
def upsert_supply(body: SupplyIn, request: Request,
                  user: CurrentUser = Depends(require_role("Analyst"))) -> JSONResponse:
    with services_of(request).db.transaction() as conn:
        if conn.execute("SELECT 1 FROM shelters WHERE id = ?", (body.shelter_id,)).fetchone() is None:
            raise AppError("NOT_FOUND", "Shelter not found.")
        now = utc_now()
        conn.execute(
            "INSERT INTO supply_items (id, shelter_id, item, quantity, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (shelter_id, item) "
            "DO UPDATE SET quantity = excluded.quantity, updated_at = excluded.updated_at",
            (new_id(), body.shelter_id, body.item, body.quantity, now, now))
        row = conn.execute("SELECT * FROM supply_items WHERE shelter_id = ? AND item = ?",
                           (body.shelter_id, body.item)).fetchone()
        audit.append(conn, actor=user.username, action="supply.upserted", subject=row["id"], detail={
            "shelter_id": body.shelter_id, "item": body.item, "quantity": body.quantity})
    return JSONResponse(dict(row), status_code=201)


# ---- teams -------------------------------------------------------------------------------------------------

@router.get("/teams")
def list_teams(request: Request, country: str | None = CountryQ, district: str | None = DistrictQ,
               user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    return _list(request, "teams", "t", country, district)


@router.post("/teams", status_code=201)
def create_team(body: TeamIn, request: Request,
                user: CurrentUser = Depends(require_role("Analyst"))) -> JSONResponse:
    with services_of(request).db.transaction() as conn:
        row_id = _insert(conn, "teams", body.model_dump(), user)
        audit.append(conn, actor=user.username, action="team.created", subject=row_id, detail={
            "team_type": body.team_type, "size": body.size, "status": body.status, "district": body.district,
            "country_code": country_or_default(body.country_code)})
        row = conn.execute("SELECT * FROM teams WHERE id = ?", (row_id,)).fetchone()
    return JSONResponse(_out(row), status_code=201)


@router.patch("/teams/{row_id}")
def update_team(row_id: str, body: TeamPatch, request: Request,
                user: CurrentUser = Depends(require_role("Analyst"))) -> dict[str, Any]:
    changes = _changes(body)
    with services_of(request).db.transaction() as conn:
        row = _patch(conn, "teams", row_id, changes)
        audit.append(conn, actor=user.username, action="team.updated", subject=row_id,
                     detail={"changed": sorted(changes), "values": changes})
    return _out(row)


# ---- vehicles ----------------------------------------------------------------------------------------------

@router.get("/vehicles")
def list_vehicles(request: Request, country: str | None = CountryQ, district: str | None = DistrictQ,
                  user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    return _list(request, "vehicles", "v", country, district)


@router.post("/vehicles", status_code=201)
def create_vehicle(body: VehicleIn, request: Request,
                   user: CurrentUser = Depends(require_role("Analyst"))) -> JSONResponse:
    with services_of(request).db.transaction() as conn:
        row_id = _insert(conn, "vehicles", body.model_dump(), user)
        audit.append(conn, actor=user.username, action="vehicle.created", subject=row_id, detail={
            "vehicle_type": body.vehicle_type, "capacity_people": body.capacity_people, "status": body.status,
            "district": body.district, "country_code": country_or_default(body.country_code)})
        row = conn.execute("SELECT * FROM vehicles WHERE id = ?", (row_id,)).fetchone()
    return JSONResponse(_out(row), status_code=201)


@router.patch("/vehicles/{row_id}")
def update_vehicle(row_id: str, body: VehiclePatch, request: Request,
                   user: CurrentUser = Depends(require_role("Analyst"))) -> dict[str, Any]:
    changes = _changes(body)
    with services_of(request).db.transaction() as conn:
        row = _patch(conn, "vehicles", row_id, changes)
        audit.append(conn, actor=user.username, action="vehicle.updated", subject=row_id,
                     detail={"changed": sorted(changes), "values": changes})
    return _out(row)


# ---- coverage (used by planning.py) ------------------------------------------------------------------------

def _key(district: str) -> str:
    """Districts match case-insensitively and ignore surrounding spaces."""
    return district.strip().casefold()


def coverage(conn: sqlite3.Connection, allocations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Need against stock and capacity for each allocated district (SDD 15.1).

    Capacity: people capacity of OPEN shelters plus AVAILABLE vehicles in the district.
    Stock: supply on hand at shelters that are not CLOSED. Stock without a shelter is not located and is not counted.
    Gap: an item where stock is below the allocated need. A district with no logistics rows shows zero.
    Returns [] when the registry is empty. Reads the current registry, not the state when the run was made.
    """
    counts = conn.execute("SELECT (SELECT COUNT(*) FROM shelters) + (SELECT COUNT(*) FROM vehicles) "
                          "+ (SELECT COUNT(*) FROM supply_items) + (SELECT COUNT(*) FROM teams)").fetchone()[0]
    if counts == 0 or not allocations:
        return []

    shelter_people: dict[str, int] = defaultdict(int)
    for row in conn.execute("SELECT district, capacity_people FROM shelters WHERE status = 'OPEN'"):
        shelter_people[_key(row["district"])] += row["capacity_people"]

    vehicle_people: dict[str, int] = defaultdict(int)
    for row in conn.execute("SELECT district, capacity_people FROM vehicles WHERE status = 'AVAILABLE'"):
        vehicle_people[_key(row["district"])] += row["capacity_people"]

    stock: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(SUPPLY_ITEMS, 0))
    for row in conn.execute(
            "SELECT sh.district AS district, si.item AS item, SUM(si.quantity) AS qty "
            "FROM supply_items si JOIN shelters sh ON sh.id = si.shelter_id "
            "WHERE sh.status <> 'CLOSED' GROUP BY sh.district, si.item"):
        stock[_key(row["district"])][row["item"]] += row["qty"]

    teams: dict[str, dict[str, int]] = defaultdict(lambda: {"RESCUE": 0, "MEDICAL": 0, "TRANSPORT": 0})
    for row in conn.execute("SELECT district, team_type, COUNT(*) AS n FROM teams "
                            "WHERE status = 'AVAILABLE' GROUP BY district, team_type"):
        teams[_key(row["district"])][row["team_type"]] += row["n"]

    result: list[dict[str, Any]] = []
    for item in allocations:
        key = _key(item["district"])
        need = {"people_estimated": item["people_estimated"], "water_packs": item["water_packs"],
                "food_packs": item["food_packs"], "shelter_kits": item["shelter_kits"]}
        have = dict(stock[key]) if key in stock else dict.fromkeys(SUPPLY_ITEMS, 0)
        capacity_total = shelter_people.get(key, 0) + vehicle_people.get(key, 0)
        result.append({
            "district": item["district"],
            "priority_rank": item["priority_rank"],
            "need": need,
            "capacity": {"shelter_people": shelter_people.get(key, 0),
                         "vehicle_people": vehicle_people.get(key, 0), "total_people": capacity_total},
            "people_gap": max(0, need["people_estimated"] - capacity_total),
            "stock": have,
            "teams_available": dict(teams[key]) if key in teams else {"RESCUE": 0, "MEDICAL": 0, "TRANSPORT": 0},
            "gaps": [{"item": name, "need": need[name], "stock": have[name], "shortfall": need[name] - have[name]}
                     for name in NEED_ITEMS if have[name] < need[name]],
        })
    return result
