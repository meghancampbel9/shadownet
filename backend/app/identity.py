from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from shadownet.agentcard import build_direct_signed_agent_card, build_signed_agent_card
from shadownet.crypto.ed25519 import Ed25519KeyPair
from shadownet.identifiers import encode_public_key

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
        _keypair = Ed25519KeyPair.from_seed(private_path.read_bytes()[:32])
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

    public_path.write_text(get_public_key())


def get_keypair() -> Ed25519KeyPair:
    if _keypair is None:
        raise RuntimeError("Identity not initialized — call init_identity() first")
    return _keypair


def get_public_key() -> str:
    """The Shadow's signing key as a multibase Ed25519 identifier (z6Mk...)."""
    return encode_public_key(get_keypair().public_bytes)


def get_subject() -> str:
    """The wire identity this sidecar is addressed by: shadowname or bare key."""
    if settings.is_shadowname_mode:
        return settings.shadowname
    return get_public_key()


def _a2a_url() -> str:
    return settings.external_url.rstrip("/") + "/a2a"


def connection_uri() -> str:
    """Shareable address for this Shadow.

    Direct mode: shadow://key:<pk>@<host>:<port>. Shadowname mode: the bare
    shadowname (resolved by peers via DNS + provider AgentCard).
    """
    if settings.is_shadowname_mode:
        return settings.shadowname
    parsed = urlparse(settings.external_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"shadow://key:{get_public_key()}@{host}:{port}"


def get_agent_card() -> dict:
    """Self-signed direct-mode AgentCard served at /.well-known/agent-card.json."""
    return build_direct_signed_agent_card(
        name=settings.agent_name,
        description=f"Shadownet Sidecar — owned by {settings.owner_name}",
        version="0.2.0",
        a2a_url=_a2a_url(),
        shadow_key=get_keypair(),
    )


def get_provider_card(local: str) -> dict:
    """Provider-signed Shadowname-mode AgentCard served at /identity/<local>."""
    return build_signed_agent_card(
        name=settings.agent_name,
        description=f"Shadownet Sidecar — owned by {settings.owner_name}",
        version="0.2.0",
        a2a_url=_a2a_url(),
        shadow_public_key=get_public_key(),
        provider_key=get_keypair(),
        provider_domain=settings.provider_domain,
    )
