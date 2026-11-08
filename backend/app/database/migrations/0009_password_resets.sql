-- Password reset tokens (emailed link). Only a SHA-256 of the token is stored. A token works once and expires.
-- Requesting a new link marks older unused links for that account as used.
CREATE TABLE password_resets (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX password_resets_user_idx ON password_resets (user_id);
