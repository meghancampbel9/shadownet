"""Integration-bundle endpoint (RFC-0008 amendment A).

Returns the per-tenant bootstrap payload so SDK plugins (Hermes Agent,
Claude Code) can auto-discover MCP endpoint, shadowname, DID, and
supported features without manual configuration.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.deps import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["connect"])


def _build_bundle(user_id: str) -> dict:
    from app.identity import get_did
    from app.mcp_server import mcp

    tool_names = [t.name for t in mcp._tool_manager.list_tools()]

    base = settings.external_url.rstrip("/")
    shadowname = settings.shadowname
    if not shadowname:
        shadowname = f"{settings.agent_name}@localhost"

    return {
        "shadownet:v": "0.1",
        "did": get_did(),
        "shadowname": shadowname,
        "mcp_endpoint": f"{base}/mcp",
        "webhook_secret": None,
        "supported_features": ["inbox-wait", "mcp-notifications"],
        "tool_names": tool_names,
        "event_names": ["message_received"],
        "version": "0.1.0",
    }


@router.get("/v1/account/me/integration-bundle")
async def integration_bundle(user: CurrentUser) -> JSONResponse:
    return JSONResponse(content=_build_bundle(user.id))


@router.get("/v1/account/tenants/me/integration-bundle", deprecated=True)
async def integration_bundle_legacy(user: CurrentUser) -> JSONResponse:
    logger.warning(
        "deprecated path /v1/account/tenants/me/integration-bundle hit; "
        "client should migrate to /v1/account/me/integration-bundle"
    )
    return JSONResponse(content=_build_bundle(user.id))
