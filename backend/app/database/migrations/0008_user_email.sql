-- Optional contact email per account (lowercase, unique when set). Used by admins to identify a person and for
-- future reset-link delivery. Nothing is sent by the system yet. Accounts without an email keep NULL.
ALTER TABLE users ADD COLUMN email TEXT CHECK (email IS NULL OR length(email) BETWEEN 3 AND 254);
CREATE UNIQUE INDEX users_email_uidx ON users (email) WHERE email IS NOT NULL;
