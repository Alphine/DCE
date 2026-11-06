"""Bounded stream helpers shared by the runners."""

from __future__ import annotations

import asyncio

from app.sandbox.security import OUTPUT_EXCERPT_BYTES

_CHUNK = 64 * 1024


async def read_capped(stream: asyncio.StreamReader | None, limit: int) -> tuple[bytes, bool]:
    """Read to EOF, keeping at most `limit` bytes. Excess is drained and discarded.

    Returns (kept_bytes, truncated). Draining keeps the child process from blocking on a full pipe.
    """
    if stream is None:
        return b"", False
    kept = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(_CHUNK)
        if not chunk:
            break
        room = limit - len(kept)
        if room > 0:
            kept.extend(chunk[:room])
        if len(chunk) > room:
            truncated = True
    return bytes(kept), truncated


def excerpt(data: bytes) -> str:
    """Decode a captured stream for the result. Invalid bytes are replaced, never raised."""
    return data[:OUTPUT_EXCERPT_BYTES].decode("utf-8", errors="replace")
