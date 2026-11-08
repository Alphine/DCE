-- Alerts: things that need attention (docs/notes/w4-alerts.md). Written in the same transaction as the event
-- that causes them. DECISION_WAITING is never stored; /api/alerts/summary computes it from PROPOSED missions and
-- OBSERVATION reports. An alert never carries a username: acknowledged_by is the internal user id.
CREATE TABLE alerts (
    id               TEXT PRIMARY KEY,
    kind             TEXT NOT NULL CHECK (kind IN (
        'REPORT_VERIFIED', 'THRESHOLD_CROSSED', 'DECISION_WAITING', 'SYNC_REJECTED')),
    severity         TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    country_code     TEXT CHECK (country_code IS NULL OR (length(country_code) = 2 AND country_code = upper(country_code))),
    district         TEXT CHECK (district IS NULL OR length(district) BETWEEN 1 AND 120),
    title            TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
    detail_json      TEXT NOT NULL DEFAULT '{}',
    source_type      TEXT NOT NULL CHECK (source_type IN ('report', 'mission', 'dataset', 'sync_op', 'hazard_rule')),
    source_id        TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    acknowledged_by  TEXT REFERENCES users (id),
    acknowledged_at  TEXT,
    CHECK ((acknowledged_by IS NULL) = (acknowledged_at IS NULL))
);
CREATE INDEX alerts_created_idx ON alerts (created_at);
CREATE INDEX alerts_country_idx ON alerts (country_code, created_at);
