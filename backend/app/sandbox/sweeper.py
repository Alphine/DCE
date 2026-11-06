"""Orphan sweeper helpers (SDD 9.2, 21.3). Pure selection logic plus a periodic loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from app.sandbox.base import SandboxRunner

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_S = 60
ORPHAN_GRACE_S = 30
SWEEP_LABEL = "dce.task"


def orphan_threshold_s(timeout_s: int) -> int:
    """A labelled container older than hard timeout plus grace is an orphan."""
    return timeout_s + ORPHAN_GRACE_S


def parse_listing(text: str) -> list[tuple[str, int | None]]:
    """Parse lines of the form '<container_id>\\t<dce.created or empty>'."""
    entries: list[tuple[str, int | None]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        cid, _, created = line.partition("\t")
        try:
            created_ts: int | None = int(created)
        except ValueError:
            created_ts = None
        entries.append((cid, created_ts))
    return entries


def select_orphans(
    entries: Iterable[tuple[str, int | None]],
    *,
    now: int,
    max_age_s: int,
    active: set[str],
) -> list[str]:
    """Return container IDs to remove. Missing or unparseable creation times count as orphans.

    `active` holds full container IDs owned by runs in this process; they are never selected.
    """
    selected: list[str] = []
    for cid, created in entries:
        if cid in active:
            continue
        if created is None or now - created > max_age_s:
            selected.append(cid)
    return selected


async def sweep_loop(runner: SandboxRunner, stop: asyncio.Event, interval_s: int = SWEEP_INTERVAL_S) -> None:
    """Run runner.sweep_orphans() every interval until stop is set."""
    while not stop.is_set():
        try:
            removed = await runner.sweep_orphans()
            if removed:
                logger.warning("orphan sweeper removed %d sandbox container(s)", removed)
        except Exception:  # keep the loop alive; the next tick retries
            logger.exception("orphan sweep failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            continue
