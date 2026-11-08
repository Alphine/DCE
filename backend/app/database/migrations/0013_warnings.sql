-- Public warnings (docs/notes/w5-i18n.md). A warning is drafted by an Analyst, then published by an Approver
-- who did not draft it. Only PUBLISHED rows are ever returned by /api/public/warnings.
-- Text is plain text: the API refuses '<' and '>' so nothing that looks like HTML is stored.
CREATE TABLE warnings (
    id              TEXT PRIMARY KEY,
    country_code    TEXT CHECK (country_code IS NULL OR (length(country_code) = 2 AND country_code = upper(country_code))),
    lang            TEXT NOT NULL CHECK (lang IN ('en', 'id')),
    hazard_type     TEXT NOT NULL CHECK (hazard_type IN ('EARTHQUAKE', 'TSUNAMI', 'EXTREME_RAINFALL', 'FLOOD',
                                                         'LANDSLIDE', 'WILDFIRE', 'SMOKE')),
    title           TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
    body            TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
    status          TEXT NOT NULL CHECK (status IN ('DRAFT', 'PUBLISHED', 'WITHDRAWN')),
    content_sha256  TEXT NOT NULL CHECK (length(content_sha256) = 64),
    created_by      TEXT NOT NULL REFERENCES users (id),
    decided_by      TEXT REFERENCES users (id),
    decided_at      TEXT,
    published_at    TEXT,
    withdrawn_at    TEXT,
    created_at      TEXT NOT NULL,
    -- The publisher is never the drafter (separation of duties, enforced in the database too).
    CHECK (decided_by IS NULL OR decided_by <> created_by),
    -- A draft has no decision. A published or withdrawn warning always has a decider and a publish time.
    CHECK (status <> 'DRAFT' OR (decided_by IS NULL AND published_at IS NULL AND withdrawn_at IS NULL)),
    CHECK (status <> 'PUBLISHED' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL
                                     AND published_at IS NOT NULL AND withdrawn_at IS NULL)),
    CHECK (status <> 'WITHDRAWN' OR (decided_by IS NOT NULL AND published_at IS NOT NULL
                                     AND withdrawn_at IS NOT NULL))
);
CREATE INDEX warnings_status_idx ON warnings (status, created_at);
CREATE INDEX warnings_public_idx ON warnings (status, lang, country_code, published_at);
-- At most one live (PUBLISHED) copy of identical content, so the same warning cannot be published twice.
CREATE UNIQUE INDEX warnings_one_published_idx ON warnings (content_sha256) WHERE status = 'PUBLISHED';
