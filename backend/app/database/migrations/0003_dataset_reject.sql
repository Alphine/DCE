-- Dataset rejection (docs/api.md section 3). The status CHECK in 0001 already allows 'REJECTED',
-- so only the review columns are added here. Migration 0001_init.sql is not edited.
ALTER TABLE datasets ADD COLUMN rejected_by TEXT REFERENCES users (id);
ALTER TABLE datasets ADD COLUMN rejected_at TEXT;
ALTER TABLE datasets ADD COLUMN rejection_note TEXT;
