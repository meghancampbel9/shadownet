from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.identity import init_identity

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("shadownet starting up")
    init_db()
    init_identity()

    from app.signing import init_protocol

    init_protocol()
    logger.info("Agent card (A2A v1.0): %s/.well-known/agent-card.json", settings.external_url)
    yield
    logger.info("shadownet shutting down")


app = FastAPI(
    title="shadownet",
    description="Agent-to-agent communication layer",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)

# ── Routers ────────────────────────────────────────────────────────────────

from app.inbox_stream import router as inbox_stream_router  # noqa: E402
from app.routers.a2a import router as a2a_router  # noqa: E402
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.connect import router as connect_router  # noqa: E402
from app.routers.contacts import router as contacts_router  # noqa: E402
from app.routers.interactions import router as interactions_router  # noqa: E402
from app.routers.messages import router as messages_router  # noqa: E402

app.include_router(a2a_router)
app.include_router(connect_router)
app.include_router(auth_router, prefix="/api")
app.include_router(contacts_router, prefix="/api")
app.include_router(interactions_router, prefix="/api")
app.include_router(messages_router, prefix="/api")
app.include_router(inbox_stream_router)

# ── Health ─────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    from app.identity import get_did, get_public_key_b64

    return {
        "status": "ok",
        "agent": settings.agent_name,
        "owner": settings.owner_name,
        "did": get_did(),
        "public_key": get_public_key_b64(),
    }


# ── SPA static files (must be last) ───────────────────────────────────────

if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        file = STATIC_DIR / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(STATIC_DIR / "index.html")
