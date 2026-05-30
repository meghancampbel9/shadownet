"""A2A HTTP+JSON receiver — RFC 0001 §8. Drives the SDK receiver pipeline."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from shadownet.a2a import (
    ParseError,
    ShadownetWireError,
    acceptance_headers,
    build_acceptance_response,
    problem_response,
)
from shadownet.receiver import ensure_extension_declared

from app.config import settings
from app.executor import persist_inbound
from app.identity import get_agent_card, get_provider_card
from app.protocol import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["a2a"])


@router.get("/.well-known/agent-card.json")
def agent_card():
    return get_agent_card()


@router.get("/identity/{local}")
def provider_agent_card(local: str):
    if not settings.is_shadowname_mode:
        return JSONResponse({"error": "not_found"}, status_code=404)
    expected_local = settings.shadowname.split("@", 1)[0]
    if local != expected_local:
        return JSONResponse({"error": "unknown_recipient"}, status_code=404)
    return get_provider_card(local)


def _problem(error: ShadownetWireError) -> JSONResponse:
    status_code, body, headers = problem_response(error)
    # RFC 0001 §11 agent opacity: the canonical `type`/`title`/`status` are
    # spec-defined, but the SDK's free-text `detail` can echo sender identifiers
    # and classification state — strip it before it crosses the wire.
    body.pop("detail", None)
    return JSONResponse(body, status_code=status_code, headers=headers)


@router.post("/a2a/message:send")
async def a2a_message_send(request: Request):
    try:
        ensure_extension_declared(request.headers.get("A2A-Extensions"))
        body = await request.json()
    except ShadownetWireError as exc:
        return _problem(exc)
    except Exception as exc:
        return _problem(ParseError(f"request body not JSON: {exc}"))

    try:
        decision = await run_in_threadpool(get_pipeline().receive, body)
    except ShadownetWireError as exc:
        return _problem(exc)
    except Exception as exc:
        logger.exception("Receiver pipeline error")
        return _problem(ParseError(str(exc)))

    message = body.get("message", {})
    message_id = message.get("messageId", "")
    context_id = message.get("contextId")
    persist_inbound(decision, message_id=message_id, context_id=context_id or "")

    return JSONResponse(
        build_acceptance_response(context_id=context_id),
        headers=acceptance_headers(),
    )
