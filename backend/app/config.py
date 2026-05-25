from __future__ import annotations

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
    shadowname: str = ""
    jwt_secret: str = "CHANGE-ME-IN-PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 1 week
    agent_request_timeout: int = 30
    agent_retry_attempts: int = 3
    agent_retry_base_delay: float = 2.0
    allow_registration: bool = True
    sns_provider_host: str = ""
    trust_store_pairs: str = "[]"

    model_config = {"env_prefix": "SHADOWNET_", "env_file": ".env"}

    @property
    def has_valid_shadowname(self) -> bool:
        return bool(self.shadowname and _SHADOWNAME_RE.match(self.shadowname))


settings = Settings()


def validate_shadowname_at_startup() -> None:
    """Log a warning if shadowname is set but invalid."""
    import logging

    logger = logging.getLogger(__name__)
    if settings.shadowname and not settings.has_valid_shadowname:
        logger.warning(
            "SHADOWNET_SHADOWNAME=%r does not match required format "
            "'local@provider'. Plugin integration will not work. "
            "Example: meghan@shadownet.example.com",
            settings.shadowname,
        )
    elif settings.has_valid_shadowname:
        logger.info("Shadowname: %s", settings.shadowname)
