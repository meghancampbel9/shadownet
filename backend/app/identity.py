from __future__ import annotations

import base64
import logging
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from shadownet.crypto.ed25519 import Ed25519KeyPair
from shadownet.did.key import derive_did_key

from app.config import settings

logger = logging.getLogger(__name__)

_keypair: Ed25519KeyPair | None = None


def _identity_dir() -> Path:
    return Path(settings.data_dir) / "identity"


def init_identity() -> None:
    global _keypair

    identity_dir = _identity_dir()
    identity_dir.mkdir(parents=True, exist_ok=True)
    private_path = identity_dir / "private.key"
    public_path = identity_dir / "public.key"

    if private_path.exists():
        raw = private_path.read_bytes()
        _keypair = Ed25519KeyPair.from_seed(raw[:32])
        logger.info("Loaded existing Ed25519 identity")
    else:
        _keypair = Ed25519KeyPair.generate()
        seed = _keypair.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        private_path.write_bytes(seed)
        private_path.chmod(0o600)
        logger.info("Generated new Ed25519 identity")

    public_path.write_text(get_public_key_b64())


def get_keypair() -> Ed25519KeyPair:
    if _keypair is None:
        raise RuntimeError("Identity not initialized — call init_identity() first")
    return _keypair


def get_did() -> str:
    return derive_did_key(get_keypair().public_bytes)


def get_public_key_b64() -> str:
    return base64.b64encode(get_keypair().public_bytes).decode()


def get_agent_card() -> dict:
    """Return an A2A + shadownet-local compliant Agent Card."""
    base_url = settings.external_url.rstrip("/")

    return {
        "name": settings.agent_name,
        "description": f"Agent-to-agent communication layer — owned by {settings.owner_name}",
        "version": "1.0.0",
        "url": f"{base_url}/a2a",
        "did": get_did(),
        "publicKey": get_keypair().public_jwk(),
        "shadownet:v": "0.1",
        "supportedInterfaces": [
            {
                "url": f"{base_url}/a2a",
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            },
        ],
        "provider": {
            "organization": settings.owner_name,
            "url": base_url,
        },
        "capabilities": {
            "streaming": False,
            "pushNotifications": True,
        },
        "securitySchemes": {
            "bearerJwt": {
                "httpAuthSecurityScheme": {
                    "scheme": "Bearer",
                    "bearerFormat": "JWT (EdDSA / Ed25519)",
                    "description": ("DID-bound session token + Verifiable Presentation handshake."),
                },
            },
        },
        "securityRequirements": [{"bearerJwt": []}],
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json", "text/plain"],
        "skills": [
            {
                "id": "messaging",
                "name": "Agent Communication",
                "description": "Send and receive structured messages between agents.",
                "tags": ["messaging", "a2a"],
            },
        ],
        "metadata": {
            "publicKey": get_public_key_b64(),
        },
    }
