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

    # Market data / broker selection: "public" (Swissquote public quotes, no credentials),
    # "oanda" (OANDA v20 REST) or "mt5" (MetaTrader 5 via the ATLAS MT5 bridge or native package).
    data_source: Literal["public", "oanda", "mt5", "metaapi"] = "public"
    broker: Literal["none", "oanda", "mt5", "metaapi"] = "none"
    public_quotes_url: str = "https://forex-data-feed.swissquote.com"
    public_quote_interval_seconds: float = 10.0
    calendar_url: str = "https://nfs.faireconomy.media"
    http_timeout_seconds: float = 10.0

    # OANDA v20 — practice (demo) environment by default. Token/account come from the environment ONLY.
    oanda_environment: Literal["practice", "live"] = "practice"
    oanda_token: SecretStr | None = None
    oanda_account_id: str | None = None

    # MetaTrader 5 — via the bridge service running next to the terminal (Windows), or the native
    # MetaTrader5 package when ATLAS itself runs on Windows. MT5 login/password stay in the terminal/bridge.
    mt5_bridge_url: str | None = None
    mt5_bridge_token: SecretStr | None = None
    mt5_symbol_suffix: str = ""  # e.g. ".a" or "m" depending on the broker
    mt5_magic: int = 770077

    # MetaTrader 5 WITHOUT Windows — via MetaApi (metaapi.cloud). The MT5 login/password are entered in the
    # MetaApi web app; ATLAS stores only the MetaApi token + account id (environment only).
    metaapi_token: SecretStr | None = None
    metaapi_account_id: str | None = None
    metaapi_region: str | None = None  # auto-detected from the account if empty

    # Optional AI commentary (Claude). Commentary never changes execution.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    ai_commentary_model: str = "claude-opus-5-5"
    ai_commentary_enabled: bool = True

    # Live (real-money) broker accounts — hard env-level gate on top of the in-app switches.
    live_trading_allowed: bool = False

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    frontend_dist: str | None = None  # path to the static Next.js export

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def oanda_configured(self) -> bool:
        return bool(self.oanda_token and self.oanda_account_id)

    @property
    def metaapi_configured(self) -> bool:
        return bool(self.metaapi_token and self.metaapi_account_id)

    @property
    def mt5_configured(self) -> bool:
        return bool(self.mt5_bridge_url)

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and "change-me" in s.secret_key.get_secret_value():
        raise RuntimeError("ATLAS_SECRET_KEY must be set to a strong random value in production")
    return s
