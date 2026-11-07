-- Mission proposals and human approval (SDD 15.2 to 15.4). Approval is recorded on the mission row:
-- approver ID, role, timestamp, and the SHA-256 of the approved content. Missions never start sandbox runs
-- or change agent tasks; "executed" is not part of this table yet.
CREATE TABLE missions (
    id                      TEXT PRIMARY KEY,
    title                   TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
    objective               TEXT NOT NULL CHECK (length(objective) BETWEEN 1 AND 1000),
    source_type             TEXT NOT NULL CHECK (source_type IN ('DATASET', 'REPORT')),
    dataset_id              TEXT REFERENCES datasets (id),
    report_id               TEXT REFERENCES reports (id),
    area_column             TEXT,
    target_areas_json       TEXT NOT NULL,
    content_sha256          TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK (status IN ('PROPOSED', 'APPROVED', 'REJECTED')),
    proposer_id             TEXT NOT NULL REFERENCES users (id),
    decided_by              TEXT REFERENCES users (id),
    decided_role            TEXT,
    decided_at              TEXT,
    decision_note           TEXT CHECK (decision_note IS NULL OR length(decision_note) <= 500),
    approved_content_sha256 TEXT,
    created_at              TEXT NOT NULL,
    CHECK ((source_type = 'DATASET' AND dataset_id IS NOT NULL AND report_id IS NULL)
        OR (source_type = 'REPORT' AND report_id IS NOT NULL AND dataset_id IS NULL)),
    CHECK (status <> 'APPROVED' OR approved_content_sha256 IS NOT NULL)
);
CREATE INDEX missions_status_idx ON missions (status, created_at);
