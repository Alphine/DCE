-- Simulation runs (SDD 14.4 reproducibility, 16.2 simulation_runs). A run stores its inputs, the verified
-- dataset and rule-pack hashes, and the output with its SHA-256, so the same run can be checked later.
-- Runs are analysis records. They never change a mission, a report or an observation.
CREATE TABLE simulation_runs (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    dataset_id         TEXT NOT NULL REFERENCES datasets (id),
    dataset_sha256     TEXT NOT NULL,
    pack_id            TEXT NOT NULL,
    pack_sha256        TEXT NOT NULL,
    simulator_version  TEXT NOT NULL,
    parameters_json    TEXT NOT NULL,
    output_json        TEXT NOT NULL,
    output_sha256      TEXT NOT NULL,
    peak_hour          INTEGER NOT NULL CHECK (peak_hour >= 0),
    peak_affected_rows INTEGER NOT NULL CHECK (peak_affected_rows >= 0),
    created_by         TEXT NOT NULL REFERENCES users (id),
    created_at         TEXT NOT NULL
);
CREATE INDEX simulation_runs_created_idx ON simulation_runs (created_at);
