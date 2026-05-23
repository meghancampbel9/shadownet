"""Authenticated MCP mount for the main FastAPI app (port 8340).

Wraps FastMCP's streamable_http_app() with a thin ASGI middleware that
validates Bearer JWT tokens before allowing access to the MCP endpoint.
This enables the monorepo Hermes plugin to connect via a single base URL.

The streamable_http_app() exposes a route at /mcp internally, so when
mounted at /u/{shadowname} the full path becomes /u/{shadowname}/mcp.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import jwt as pyjwt
from sqlmodel import Session, select
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.database import engine
from app.models import User

logger = logging.getLogger(__name__)

_mcp_starlette_app: Starlette | None = None


def _get_mcp_app() -> Starlette:
    """Lazily create and cache the MCP Starlette sub-app."""
    global _mcp_starlette_app
    if _mcp_starlette_app is None:
        from app.mcp_server import mcp

        _mcp_starlette_app = mcp.streamable_http_app()
    return _mcp_starlette_app


class BearerAuthMiddleware:
    """ASGI middleware that requires a valid Bearer JWT on every request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()

        if not auth_header.lower().startswith("bearer "):
            response = JSONResponse(
                status_code=401,
                content={"error": "missing_bearer_token", "shadownet:v": "0.1"},
            )
            await response(scope, receive, send)
            return

        token = auth_header[7:].strip()
        try:
            payload = pyjwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        except pyjwt.InvalidTokenError:
            response = JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "shadownet:v": "0.1"},
            )
            await response(scope, receive, send)
            return

        with Session(engine) as session:
            user_id = payload.get("sub")
            user = session.exec(select(User).where(User.id == user_id)).first()
            if user is None:
                response = JSONResponse(
                    status_code=401,
                    content={"error": "invalid_token", "shadownet:v": "0.1"},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def get_authenticated_mcp_app() -> ASGIApp:
    """Return the MCP streamable HTTP app wrapped with Bearer auth."""
    inner_app = _get_mcp_app()
    return BearerAuthMiddleware(inner_app)


@asynccontextmanager
async def mcp_lifespan():
    """Start the MCP session manager's task group for streamable HTTP."""
    app = _get_mcp_app()
    session_manager = app.routes[0].app.session_manager
    async with session_manager.run():
        yield
