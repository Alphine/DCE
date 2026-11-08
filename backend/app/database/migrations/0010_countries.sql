-- Country scope and offline sync (docs/offline-global.md sections 3 and 4).
-- country_code is ISO 3166-1 alpha-2, uppercase. NULL means "not recorded"; responses show it as 'ID'.
ALTER TABLE reports ADD COLUMN country_code TEXT
    CHECK (country_code IS NULL OR (length(country_code) = 2 AND country_code = upper(country_code)));
ALTER TABLE datasets ADD COLUMN country_code TEXT
    CHECK (country_code IS NULL OR (length(country_code) = 2 AND country_code = upper(country_code)));
ALTER TABLE missions ADD COLUMN country_code TEXT
    CHECK (country_code IS NULL OR (length(country_code) = 2 AND country_code = upper(country_code)));
ALTER TABLE simulation_runs ADD COLUMN country_code TEXT
    CHECK (country_code IS NULL OR (length(country_code) = 2 AND country_code = upper(country_code)));
CREATE INDEX reports_country_idx ON reports (country_code, status, created_at);
CREATE INDEX missions_country_idx ON missions (country_code, status, created_at);

-- Idempotency record for POST /api/sync/batch. One row per op_id, written in the same transaction as the
-- effect (APPLIED) or on its own (REJECTED). A replayed op_id returns the stored result and changes nothing.
CREATE TABLE sync_ops (
    op_id       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users (id),
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('APPLIED', 'REJECTED')),
    created_at  TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE INDEX sync_ops_user_idx ON sync_ops (user_id, created_at);
