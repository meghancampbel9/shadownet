"""RFC-0008 onboarding surface: integration bundle + connect pages.

Wires the SDK's `build_connect_router` into shadownet-local. The
bundle_builder validates the caller's JWT and returns the tenant's
IntegrationBundle, enabling one-token plugin installs for Hermes Agent,
Claude Code, and Cursor.
"""

from __future__ import annotations

import logging

import jwt
from shadownet.connect.bundle import IntegrationBundle
from shadownet.connect.fastapi import build_connect_router
from sqlmodel import select

from app.config import settings
from app.database import engine
from app.identity import get_did
from app.models import User

logger = logging.getLogger(__name__)

MCP_TOOL_NAMES = [
    "social_contacts",
    "social_contact_detail",
    "social_resolve",
    "social_add_contact",
    "social_send",
    "social_inbox",
    "social_inbox_wait",
    "social_respond",
    "social_coordinate",
    "social_confirm_plan",
    "social_accept_plan",
    "social_interactions",
    "social_grant",
    "social_identity",
]


def _mcp_endpoint() -> str:
    base = settings.external_url.rstrip("/")
    sn = settings.shadowname
    if sn:
        return f"{base}/u/{sn}/mcp"
    return f"{base}/mcp"


async def _bundle_builder(token: str) -> IntegrationBundle | None:
    """Validate a Bearer token (JWT) and return the integration bundle."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.InvalidTokenError:
        return None

    from sqlmodel import Session

    with Session(engine) as session:
        user_id = payload.get("sub")
        user = session.exec(select(User).where(User.id == user_id)).first()
        if user is None:
            return None

    endpoint = _mcp_endpoint()
    sn = settings.shadowname
    if not sn:
        sn = f"{settings.agent_name}@localhost"

    return IntegrationBundle.model_validate(
        {
            "shadownet:v": "0.1",
            "did": get_did(),
            "shadowname": sn,
            "mcp_endpoint": endpoint,
            "webhook_secret": None,
            "supported_features": [
                "mcp",
                "inbox-wait",
                "bundle",
                "connect-url",
            ],
            "tool_names": MCP_TOOL_NAMES,
            "event_names": ["inbox.message"],
            "version": "0.3.0",
        }
    )


def get_connect_router():
    """Build and return the RFC-0008 connect router."""
    return build_connect_router(bundle_builder=_bundle_builder)
