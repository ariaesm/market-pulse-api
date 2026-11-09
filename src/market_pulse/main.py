"""ASGI entry point: ``uvicorn market_pulse.main:app``."""

from __future__ import annotations

from market_pulse.api.app import create_app
from market_pulse.config import Settings
from market_pulse.log import configure_logging

settings = Settings.from_env()
configure_logging(settings.log_level, settings.log_json)
app = create_app(settings)
