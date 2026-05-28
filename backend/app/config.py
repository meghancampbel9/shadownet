from __future__ import annotations

from pydantic_settings import BaseSettings


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


settings = Settings()
