-- DCE core schema (SDD 16.2). Timestamps are ISO 8601 UTC strings. IDs are UUIDv4 text.

CREATE TABLE users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at    TEXT NOT NULL
);

CREATE TABLE user_roles (
    user_id TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    role    TEXT NOT NULL CHECK (role IN ('Viewer', 'Analyst', 'Reviewer', 'Approver', 'Admin'))
);

-- Session id is the SHA-256 of the cookie token; the raw token is never stored.
CREATE TABLE sessions (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX sessions_user_idx ON sessions (user_id);

-- Table only (automation keys are not issued in the MVP). Hashes only.
CREATE TABLE api_keys (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    key_hash    TEXT NOT NULL UNIQUE,
    scope       TEXT NOT NULL,
    expires_at  TEXT,
    created_at  TEXT NOT NULL,
    revoked_at  TEXT
);

CREATE TABLE datasets (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    filename       TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256         TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('PENDING_VALIDATION', 'APPROVED', 'REJECTED')),
    owner_id       TEXT NOT NULL REFERENCES users (id),
    storage_name   TEXT NOT NULL UNIQUE,
    profile_json  TEXT NOT NULL,
    approved_by    TEXT REFERENCES users (id),
    approved_at    TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE agent_tasks (
    id                    TEXT PRIMARY KEY,
    owner_id              TEXT NOT NULL REFERENCES users (id),
    instruction           TEXT NOT NULL,
    dataset_id            TEXT NOT NULL REFERENCES datasets (id),
    requested_outputs_json TEXT NOT NULL,
    state                 TEXT NOT NULL CHECK (state IN (
        'PLANNING', 'FAILED_PLANNING', 'AWAITING_APPROVAL', 'REJECTED', 'QUEUED', 'CANCELLED',
        'RUNNING', 'TIMED_OUT', 'FAILED_SANDBOX', 'OUTPUT_VALIDATING', 'REJECTED_OUTPUT',
        'AWAITING_REVIEW', 'COMPLETED', 'ORPHANED')),
    plan_json             TEXT,
    code_sha256           TEXT,
    sandbox_json          TEXT,
    error_reason          TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
CREATE INDEX agent_tasks_owner_idx ON agent_tasks (owner_id, created_at);
CREATE INDEX agent_tasks_state_idx ON agent_tasks (state);

CREATE TABLE approvals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES agent_tasks (id) ON DELETE CASCADE,
    gate        TEXT NOT NULL CHECK (gate IN ('A', 'B')),
    decision    TEXT NOT NULL CHECK (decision IN ('approve', 'reject')),
    approver_id TEXT NOT NULL REFERENCES users (id),
    role        TEXT NOT NULL,
    note        TEXT,
    at          TEXT NOT NULL
);
CREATE INDEX approvals_task_idx ON approvals (task_id);

CREATE TABLE artifacts (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL REFERENCES agent_tasks (id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('csv', 'json', 'png', 'pdf', 'md', 'py', 'log')),
    size_bytes   INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256       TEXT NOT NULL,
    storage_path TEXT NOT NULL UNIQUE,  -- relative to DCE_DATA_DIR, server-generated
    created_at   TEXT NOT NULL
);
CREATE INDEX artifacts_task_idx ON artifacts (task_id);

CREATE TABLE quota_usage (
    user_id       TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    day           TEXT NOT NULL,  -- UTC date YYYY-MM-DD
    tasks_created INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

-- Append-only, hash-chained audit log (SDD 16.4). Stores IDs and hashes, never secrets.
CREATE TABLE audit_logs (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    subject     TEXT,
    detail_json TEXT NOT NULL,
    prev_hash   TEXT NOT NULL,
    row_hash    TEXT NOT NULL
);

CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs is append-only');
END;

CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs is append-only');
END;
