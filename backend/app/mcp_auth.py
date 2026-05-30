"""Bearer-auth wrapper for the streamable-HTTP MCP mount (RFC 0003 access tokens)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

_mcp_starlette_app: Starlette | None = None


def _get_mcp_app() -> Starlette:
    global _mcp_starlette_app
    if _mcp_starlette_app is None:
        from app.mcp_server import mcp

        _mcp_starlette_app = mcp.streamable_http_app()
    return _mcp_starlette_app


class BearerAuthMiddleware:
    """Requires a live RFC 0003 access token on every MCP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from app.onboarding import validate_access_token

        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        subject = validate_access_token(token) if token else None
        if subject is None:
            response = JSONResponse(status_code=401, content={"error": "unauthorized"})
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def get_authenticated_mcp_app() -> ASGIApp:
    return BearerAuthMiddleware(_get_mcp_app())


@asynccontextmanager
async def mcp_lifespan():
    app = _get_mcp_app()
    session_manager = app.routes[0].app.session_manager
    async with session_manager.run():
        yield
