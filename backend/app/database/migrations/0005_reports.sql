-- Structured report intake (SDD 10.7, 16.2, 16.3). Unknown values are NULL, never 0 or an empty string.
-- Status: OBSERVATION after passing validation; a Reviewer promotes it to VERIFIED_OBSERVATION or REJECTED.
CREATE TABLE reports (
    id                TEXT PRIMARY KEY,
    submitter_id      TEXT NOT NULL REFERENCES users (id),
    hazard_type       TEXT NOT NULL CHECK (hazard_type IN (
        'EARTHQUAKE', 'TSUNAMI', 'EXTREME_RAINFALL', 'FLOOD', 'LANDSLIDE', 'WILDFIRE', 'SMOKE')),
    location_name     TEXT CHECK (location_name IS NULL OR length(location_name) BETWEEN 1 AND 120),
    latitude          REAL CHECK (latitude IS NULL OR (latitude >= -90 AND latitude <= 90)),
    longitude         REAL CHECK (longitude IS NULL OR (longitude >= -180 AND longitude <= 180)),
    observed_at       TEXT CHECK (observed_at IS NULL OR length(observed_at) = 20),
    reporter_role     TEXT CHECK (reporter_role IS NULL OR reporter_role IN (
        'CIVILIAN', 'VOLUNTEER', 'OFFICIAL', 'RESPONDER', 'OTHER')),
    severity_reported TEXT CHECK (severity_reported IS NULL OR severity_reported IN (
        'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    source_reference  TEXT CHECK (source_reference IS NULL OR length(source_reference) BETWEEN 1 AND 120),
    notes             TEXT CHECK (notes IS NULL OR length(notes) BETWEEN 1 AND 2000),
    status            TEXT NOT NULL CHECK (status IN ('OBSERVATION', 'VERIFIED_OBSERVATION', 'REJECTED')),
    reviewed_by       TEXT REFERENCES users (id),
    reviewed_at       TEXT,
    review_note       TEXT CHECK (review_note IS NULL OR length(review_note) <= 500),
    created_at        TEXT NOT NULL,
    CHECK ((latitude IS NULL) = (longitude IS NULL))
);
CREATE INDEX reports_status_idx ON reports (status, created_at);
