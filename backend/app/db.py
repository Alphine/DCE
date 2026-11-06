"""SQLite access: connections, transactions, and numbered migrations (SDD 16.5)."""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("dce.db")

MIGRATIONS_DIR = Path(__file__).parent / "database" / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    pass


class Db:
    """Thin wrapper that opens a short-lived connection per use. Safe across threads."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Write transaction. Commits on normal exit, rolls back on any exception."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def migrate(self) -> list[int]:
        """Apply pending migrations. Each file runs in its own transaction; a failure stops startup."""
        applied_now: list[int] = []
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
            for version, name, sql_path in _discover_migrations():
                if version <= current:
                    continue
                sql = sql_path.read_text(encoding="utf-8")
                try:
                    conn.executescript(
                        "BEGIN IMMEDIATE;\n" + sql +
                        f"\nINSERT INTO schema_version (version, name, applied_at) VALUES "
                        f"({version}, '{name}', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));\nCOMMIT;"
                    )
                except sqlite3.Error as exc:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise MigrationError(f"migration {name} failed: {exc}") from exc
                applied_now.append(version)
                logger.info("applied migration %s", name)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise MigrationError(f"integrity_check failed: {integrity}")
        finally:
            conn.close()
        return applied_now


def _discover_migrations() -> list[tuple[int, str, Path]]:
    found: list[tuple[int, str, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _MIGRATION_RE.match(path.name)
        if not match:
            raise MigrationError(f"bad migration file name: {path.name}")
        found.append((int(match.group(1)), path.name, path))
    versions = [v for v, _, _ in found]
    if len(versions) != len(set(versions)):
        raise MigrationError("duplicate migration version")
    return found
