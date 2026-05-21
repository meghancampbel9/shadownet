"""SSE stream of newly stored inbound A2A messages.

Alternative to the outbound webhook for host agents that prefer to pull
events (e.g. a Claude Code background monitor running ``curl -N``) instead
of exposing an HTTP receiver. Both delivery paths fire from
``notify_message_received`` so the webhook and the stream stay in sync.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

_subscribers: set[asyncio.Queue[str]] = set()
_KEEPALIVE_SECONDS = 15
_SUBSCRIBER_QUEUE_SIZE = 100


def publish(event: dict) -> None:
    """Fan out an event to all current subscribers."""
    if not _subscribers:
        return
    payload = json.dumps(event)
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("inbox_stream: dropping event for slow subscriber")


async def _stream() -> AsyncIterator[bytes]:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_SIZE)
    _subscribers.add(q)
    try:
        yield b": connected\n\n"
        while True:
            try:
                payload = await asyncio.wait_for(q.get(), timeout=_KEEPALIVE_SECONDS)
                yield f"data: {payload}\n\n".encode()
            except TimeoutError:
                yield b": keepalive\n\n"
    finally:
        _subscribers.discard(q)


router = APIRouter(prefix="/v1", tags=["inbox-stream"])


@router.get("/inbox/stream")
async def inbox_stream() -> StreamingResponse:
    return StreamingResponse(_stream(), media_type="text/event-stream")
