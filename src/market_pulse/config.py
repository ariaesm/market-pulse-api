"""Application settings loaded from environment variables.

Settings are a plain pydantic model populated from ``MP_*`` environment variables,
which keeps the dependency footprint small (no ``pydantic-settings`` needed).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

ENV_PREFIX = "MP_"

#: ``src/market_pulse/config.py`` -> repository root ``data/`` directory.
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class SettingsError(ValueError):
    """Raised when environment configuration is invalid."""


class Settings(BaseModel):
    """Runtime configuration for the service."""

    model_config = {"frozen": True}

    app_name: str = "market-pulse-api"
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    log_json: bool = True

    data_provider: Literal["csv", "binance"] = "csv"
    data_dir: Path = DEFAULT_DATA_DIR
    binance_base_url: str = "https://api.binance.com"
    binance_symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    provider_timeout_seconds: float = Field(default=10.0, gt=0)

    cache_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: float = Field(default=30.0, ge=0)
    cache_max_entries: int = Field(default=1024, ge=1)

    api_keys: list[str] = Field(default_factory=list)

    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = Field(default=120, ge=1)
    rate_limit_burst: int = Field(default=30, ge=1)

    alert_eval_enabled: bool = True
    alert_eval_interval_seconds: float = Field(default=15.0, gt=0)
    alert_lookback: int = Field(default=300, ge=50, le=1000)

    default_limit: int = Field(default=200, ge=1)
    max_limit: int = Field(default=1000, ge=1)

    @field_validator("api_keys", "binance_symbols", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        """Allow comma-separated strings for list fields."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {value!r}")
        return level

    @property
    def auth_enabled(self) -> bool:
        """API-key auth is active only when at least one key is configured."""
        return bool(self.api_keys)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Build settings from ``MP_``-prefixed environment variables.

        Unknown ``MP_*`` variables are ignored. Values are validated by pydantic.
        """
        env = os.environ if environ is None else environ
        values: dict[str, Any] = {}
        for name in cls.model_fields:
            raw = env.get(f"{ENV_PREFIX}{name.upper()}")
            if raw is not None:
                values[name] = raw
        try:
            return cls.model_validate(values)
        except ValidationError as exc:
            raise SettingsError(str(exc)) from exc
