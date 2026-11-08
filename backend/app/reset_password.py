"""Operator account reset: `python -m app.reset_password <username> [--role ROLE]`.

For the case where nobody can sign in any more (no Admin remembers the password). Run it where the database
is, for example `docker compose exec -it api python -m app.reset_password admin`. Add `-it` so the password prompt
works. The password is read from the terminal with confirmation, or from stdin when stdin is not a terminal,
so it never appears in the command line or in shell history.

- Existing user, no --role: the password is replaced and every session of that user is revoked.
- Existing user, --role ROLE: the same, and the role is set to ROLE. The last active Admin cannot be demoted.
- Missing user, --role ROLE: the account is created with that role.
- Missing user, no --role: refused.

Each run writes audit rows with actor `operator`: `auth.password_reset_by_operator`, `admin.user_role_changed`
(when the role changes), or `auth.user_created_by_operator`. The password policy is enforced.
"""

from __future__ import annotations

import getpass
import sys
from typing import TextIO

from app import audit
from app.config import Settings, get_settings
from app.db import Db
from app.security import hash_password, password_policy_error, verify_password
from app.util import new_id, utc_now

ACTOR = "operator"
ACTION = "auth.password_reset_by_operator"
ROLES = ("Viewer", "Analyst", "Reviewer", "Approver", "Admin")
USAGE = "Usage: python -m app.reset_password <username> [--role ROLE]"


def _read_password(stdin: TextIO) -> str | None:
    if stdin.isatty():
        first = getpass.getpass("New password: ")
        second = getpass.getpass("Repeat new password: ")
        if first != second:
            print("The two passwords do not match. Nothing changed.", file=sys.stderr)
            return None
        return first
    line = stdin.readline()
    return line.rstrip("\r\n") if line else None


def reset(db: Db, username: str, new_password: str, role: str | None = None) -> str:
    """Apply the operator action in one transaction. Returns a short result line.

    Raises ValueError (refused, nothing changed) or LookupError (no such user and no role given)."""
    problem = password_policy_error(new_password)
    if problem is not None:
        raise ValueError(problem)
    if role is not None and role not in ROLES:
        raise ValueError(f"Role must be one of: {', '.join(ROLES)}.")
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT u.id, u.password_hash, u.status, r.role FROM users u "
            "LEFT JOIN user_roles r ON r.user_id = u.id WHERE u.username = ?", (username,)).fetchone()
        if row is None:
            if role is None:
                raise LookupError(f"No user named {username!r}. Add --role ROLE to create it.")
            user_id = new_id()
            conn.execute("INSERT INTO users (id, username, password_hash, status, created_at) "
                         "VALUES (?, ?, ?, 'active', ?)", (user_id, username, hash_password(new_password), utc_now()))
            conn.execute("INSERT INTO user_roles (user_id, role) VALUES (?, ?)", (user_id, role))
            audit.append(conn, actor=ACTOR, action="auth.user_created_by_operator", subject=user_id,
                         detail={"role": role})
            return f"Created {username} with role {role}."

        if verify_password(new_password, row["password_hash"]):
            raise ValueError("The new password must differ from the current one.")
        if role is not None and role != row["role"]:
            if row["role"] == "Admin" and row["status"] == "active":
                others = conn.execute(
                    "SELECT COUNT(*) FROM users u JOIN user_roles r ON r.user_id = u.id "
                    "WHERE r.role = 'Admin' AND u.status = 'active' AND u.id != ?", (row["id"],)).fetchone()[0]
                if others == 0:
                    raise ValueError("Cannot demote the last active Admin.")
            conn.execute("UPDATE user_roles SET role = ? WHERE user_id = ?", (role, row["id"]))
            audit.append(conn, actor=ACTOR, action="admin.user_role_changed", subject=row["id"],
                         detail={"from": row["role"], "to": role})
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), row["id"]))
        revoked = conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],)).rowcount
        audit.append(conn, actor=ACTOR, action=ACTION, subject=row["id"], detail={"sessions_revoked": revoked})
    role_note = f", role {role}" if role is not None else ""
    return f"Password reset for {username}{role_note}. Sessions revoked: {revoked}."


def main(argv: list[str] | None = None, *, settings: Settings | None = None, stdin: TextIO | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    role: str | None = None
    if "--role" in args:
        at = args.index("--role")
        if at + 1 >= len(args):
            print(USAGE, file=sys.stderr)
            return 2
        role = args[at + 1]
        del args[at:at + 2]
    if len(args) != 1 or not args[0].strip():
        print(USAGE, file=sys.stderr)
        return 2
    username = args[0].strip()
    settings = settings or get_settings()
    stdin = stdin or sys.stdin
    password = _read_password(stdin)
    if password is None:
        print("No password given. Nothing changed.", file=sys.stderr)
        return 2
    db = Db(settings.database_path)
    db.migrate()
    try:
        message = reset(db, username, password, role)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Not changed: {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
