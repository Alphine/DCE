-- Logistics registry (SDD 15.1 resource availability, 14.2 road access). Counts and locations only.
-- country_code follows 0010: ISO 3166-1 alpha-2, uppercase. NULL means "not recorded"; responses show 'ID'.
-- Every write is audited in the same transaction by the route (app/routes/logistics.py).
CREATE TABLE shelters (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    country_code    TEXT CHECK (country_code IS NULL OR (length(country_code) = 2 AND country_code = upper(country_code))),
    district        TEXT NOT NULL CHECK (length(district) BETWEEN 1 AND 120),
    latitude        REAL CHECK (latitude IS NULL OR (latitude BETWEEN -90 AND 90)),
    longitude       REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180)),
    capacity_people INTEGER NOT NULL CHECK (capacity_people >= 0),
    status          TEXT NOT NULL CHECK (status IN ('OPEN', 'FULL', 'CLOSED')),
    created_by      TEXT NOT NULL REFERENCES users (id),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX shelters_list_idx ON shelters (created_at, id);

-- Stock at a shelter. One row per (shelter, item): POST upserts it. shelter_id stays nullable for stock
-- that is not yet tied to a shelter; such rows have no district, so they never count toward coverage.
CREATE TABLE supply_items (
    id          TEXT PRIMARY KEY,
    shelter_id  TEXT REFERENCES shelters (id),
    item        TEXT NOT NULL CHECK (item IN ('water_packs', 'food_packs', 'shelter_kits', 'medical_kits')),
    quantity    INTEGER NOT NULL CHECK (quantity >= 0),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX supply_items_shelter_item_idx ON supply_items (shelter_id, item);
CREATE INDEX supply_items_list_idx ON supply_items (created_at, id);

CREATE TABLE teams (
    id           TEXT PRIMARY KEY,
    team_type    TEXT NOT NULL CHECK (team_type IN ('RESCUE', 'MEDICAL', 'TRANSPORT')),
    size         INTEGER NOT NULL CHECK (size >= 1),
    status       TEXT NOT NULL CHECK (status IN ('AVAILABLE', 'DEPLOYED', 'UNAVAILABLE')),
    district     TEXT NOT NULL CHECK (length(district) BETWEEN 1 AND 120),
    country_code TEXT CHECK (country_code IS NULL OR (length(country_code) = 2 AND country_code = upper(country_code))),
    created_by   TEXT NOT NULL REFERENCES users (id),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX teams_list_idx ON teams (created_at, id);

CREATE TABLE vehicles (
    id              TEXT PRIMARY KEY,
    vehicle_type    TEXT NOT NULL CHECK (length(vehicle_type) BETWEEN 1 AND 120),
    capacity_people INTEGER NOT NULL CHECK (capacity_people >= 0),
    status          TEXT NOT NULL CHECK (status IN ('AVAILABLE', 'DEPLOYED', 'UNAVAILABLE')),
    district        TEXT NOT NULL CHECK (length(district) BETWEEN 1 AND 120),
    country_code    TEXT CHECK (country_code IS NULL OR (length(country_code) = 2 AND country_code = upper(country_code))),
    created_by      TEXT NOT NULL REFERENCES users (id),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX vehicles_list_idx ON vehicles (created_at, id);
