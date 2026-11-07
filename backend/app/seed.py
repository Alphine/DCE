"""Create the demo accounts: `python -m app.seed`. Idempotent. Password comes only from DCE_SEED_PASSWORD."""

from __future__ import annotations

import sys
import uuid

from app import audit
from app.config import get_settings
from app.db import Db
from app.security import PASSWORD_MIN_LENGTH as MIN_PASSWORD_LENGTH
from app.security import hash_password
from app.util import utc_now

SEED_USERS: tuple[tuple[str, str], ...] = (
    ("admin", "Admin"),
    ("analyst", "Analyst"),
    ("reviewer", "Reviewer"),
    ("approver", "Approver"),
)


def main() -> int:
    settings = get_settings()
    password = settings.seed_password.get_secret_value() if settings.seed_password else ""
    if not password:
        print("DCE_SEED_PASSWORD is not set. Refusing to create seed accounts.", file=sys.stderr)
        return 2
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"DCE_SEED_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        return 2

    db = Db(settings.database_path)
    db.migrate()
    password_hash = hash_password(password)  # hashed once, reused for every account
    with db.transaction() as conn:
        for username, role in SEED_USERS:
            existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if existing is not None:
                print(f"exists  {username} ({role})")
                continue
            user_id = str(uuid.uuid4())
            conn.execute("INSERT INTO users (id, username, password_hash, status, created_at) "
                         "VALUES (?, ?, ?, 'active', ?)", (user_id, username, password_hash, utc_now()))
            conn.execute("INSERT INTO user_roles (user_id, role) VALUES (?, ?)", (user_id, role))
            audit.append(conn, actor="system", action="seed.user_created", subject=user_id, detail={"role": role})
            print(f"created {username} ({role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
