from __future__ import annotations

import json
import re

from pydantic_settings import BaseSettings

_SHADOWNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,63}@[A-Za-z0-9.-]+$")


class Settings(BaseSettings):
    environment: str = "production"
    database_url: str = "sqlite:///./data/shadownet.db"
    data_dir: str = "./data"
    agent_name: str = "shadownet"
    owner_name: str = "User"
    external_url: str = "http://localhost:8340"

    # Addressing (RFC 0001 §3). "direct" = key-based, self-signed AgentCard, no
    # DNS/provider. "shadowname" = this sidecar runs as its own provider for
    # `provider_domain` and serves a provider-signed card at /identity/<local>.
    addressing_mode: str = "direct"
    shadowname: str = ""
    provider_domain: str = ""

    # Trust (RFC 0001 §7). `trust_store` is a JSON list of {issuer, accept};
    # `acceptance_policy` a JSON {fromContact, fromStranger} ("" = SDK default).
    trust_store: str = "[]"
    acceptance_policy: str = ""
    same_provider_org: bool = False
    credentials_path: str = ""

    # Portal / MCP access-token signing (opaque to host LLMs, RFC 0003 §6.2).
    jwt_secret: str = "CHANGE-ME-IN-PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    allow_registration: bool = True

    # Outbound A2A (RFC 0001 §8.10).
    agent_request_timeout: int = 30
    agent_retry_attempts: int = 3
    agent_retry_base_delay: float = 2.0

    model_config = {"env_prefix": "SHADOWNET_", "env_file": ".env"}

    @property
    def has_valid_shadowname(self) -> bool:
        return bool(self.shadowname and _SHADOWNAME_RE.match(self.shadowname))

    @property
    def is_shadowname_mode(self) -> bool:
        return self.addressing_mode == "shadowname" and self.has_valid_shadowname

    @property
    def mcp_label(self) -> str:
        """Local routing label for the /u/<label>/mcp mount (not a wire id)."""
        return self.shadowname or self.agent_name

    def trust_store_entries(self) -> list[dict]:
        return json.loads(self.trust_store or "[]")

    def acceptance_policy_dict(self) -> dict | None:
        return json.loads(self.acceptance_policy) if self.acceptance_policy else None


settings = Settings()


def validate_shadowname_at_startup() -> None:
    """Warn if shadowname mode is selected with a missing or malformed shadowname."""
    import logging

    logger = logging.getLogger(__name__)
    if settings.addressing_mode == "shadowname" and not settings.has_valid_shadowname:
        logger.warning(
            "SHADOWNET_ADDRESSING_MODE=shadowname but SHADOWNET_SHADOWNAME=%r is missing or "
            "malformed (expected local@provider). Falling back to direct mode.",
            settings.shadowname,
        )
    elif settings.is_shadowname_mode:
        logger.info(
            "Shadowname mode: %s (provider %s)", settings.shadowname, settings.provider_domain
        )
    else:
        logger.info("Direct addressing mode (key-based identity)")
