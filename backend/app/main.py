from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings, validate_shadowname_at_startup
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

    from app.mcp_auth import mcp_lifespan
    from app.protocol import init as protocol_init

    protocol_init()
    validate_shadowname_at_startup()
    logger.info("AgentCard (A2A v1.0): %s/.well-known/agent-card.json", settings.external_url)

    async with mcp_lifespan():
        yield

    logger.info("shadownet shutting down")


app = FastAPI(
    title="shadownet",
    description="Shadownet v0.2 Sidecar",
    version="0.2.0",
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

from app.onboarding import router as onboarding_router  # noqa: E402
from app.routers.a2a import router as a2a_router  # noqa: E402
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.contacts import router as contacts_router  # noqa: E402
from app.routers.messages import router as messages_router  # noqa: E402

app.include_router(a2a_router)
app.include_router(auth_router, prefix="/api")
app.include_router(contacts_router, prefix="/api")
app.include_router(messages_router, prefix="/api")
app.include_router(onboarding_router)


@app.get("/health")
def health():
    from app.identity import connection_uri, get_public_key, get_subject

    return {
        "status": "ok",
        "agent": settings.agent_name,
        "owner": settings.owner_name,
        "subject": get_subject(),
        "pk": get_public_key(),
        "connectionUri": connection_uri(),
    }


from app.mcp_auth import get_authenticated_mcp_app  # noqa: E402

app.mount(f"/u/{settings.mcp_label}", get_authenticated_mcp_app())


if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        file = STATIC_DIR / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(STATIC_DIR / "index.html")
