"""Application configuration loaded from environment variables.

Secrets are only ever read from the environment (or a secrets file mounted by
the deployment platform). Nothing secret is stored in source code or returned
by the API.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_", env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://atlas@localhost:5432/atlas"  # override with ATLAS_DATABASE_URL
    redis_url: str | None = "redis://localhost:6379/0"

    # Auth / sessions
    secret_key: SecretStr = SecretStr("change-me-in-production-please-use-64-random-bytes")
    session_ttl_minutes: int = 60 * 12
    cookie_secure: bool = False
    admin_username: str = "admin"
    admin_password: SecretStr | None = None  # used once to bootstrap the first admin

    # Process topology: run the trading engine inside the API process (single
    # process dev mode) or as a separate worker (``python -m atlas.worker``).
    embedded_worker: bool = True

    # Market data providers
    binance_rest_url: str = "https://data-api.binance.vision"
    coinbase_rest_url: str = "https://api.exchange.coinbase.com"
    coinbase_ws_url: str = "wss://ws-feed.exchange.coinbase.com"
    kraken_rest_url: str = "https://api.kraken.com"
    kraken_ws_url: str = "wss://ws.kraken.com/v2"
    dexscreener_url: str = "https://api.dexscreener.com"
    jupiter_url: str = "https://lite-api.jup.ag"
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    enable_websockets: bool = True
    http_timeout_seconds: float = 10.0

    # Optional AI commentary (Claude). Commentary never changes execution.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    ai_commentary_model: str = "claude-opus-5-5"
    ai_commentary_enabled: bool = True

    # Live trading — hard env-level gate on top of the in-app switches.
    live_trading_allowed: bool = False
    solana_keypair_path: str | None = None  # path to a keypair file mounted as a secret

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    frontend_dist: str | None = None  # path to the static Next.js export

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and "change-me" in s.secret_key.get_secret_value():
        raise RuntimeError("ATLAS_SECRET_KEY must be set to a strong random value in production")
    return s
