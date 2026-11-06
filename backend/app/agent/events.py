"""In-process pub/sub per task for SSE. Publish is safe from worker threads and from the event loop."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

QUEUE_SIZE = 256


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[tuple[str, dict[str, Any]]]]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, task_id: str) -> asyncio.Queue[tuple[str, dict[str, Any]]]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subs[task_id].add(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[tuple[str, dict[str, Any]]]) -> None:
        subs = self._subs.get(task_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subs.pop(task_id, None)

    def publish(self, task_id: str, event: str, data: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._dispatch, task_id, event, data)

    def _dispatch(self, task_id: str, event: str, data: dict[str, Any]) -> None:
        for queue in list(self._subs.get(task_id, ())):
            try:
                queue.put_nowait((event, data))
            except asyncio.QueueFull:
                # A slow client drops intermediate log lines; state and end events stay in the replay path.
                pass


def sse_frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
