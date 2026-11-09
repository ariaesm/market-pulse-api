from pathlib import Path

import pytest

from market_pulse.config import Settings, SettingsError
from market_pulse.errors import SymbolNotFoundError


def test_defaults_have_auth_disabled() -> None:
    settings = Settings.from_env({})
    assert settings.api_keys == []
    assert settings.auth_enabled is False
    assert settings.data_provider == "csv"
    assert settings.cache_backend == "memory"


def test_from_env_parses_prefixed_values() -> None:
    settings = Settings.from_env(
        {
            "MP_API_KEYS": "alpha, beta,,",
            "MP_CACHE_BACKEND": "redis",
            "MP_RATE_LIMIT_PER_MINUTE": "60",
            "MP_LOG_LEVEL": "debug",
            "MP_DATA_DIR": "/tmp/data",
            "UNRELATED": "x",
        }
    )
    assert settings.api_keys == ["alpha", "beta"]
    assert settings.auth_enabled is True
    assert settings.cache_backend == "redis"
    assert settings.rate_limit_per_minute == 60
    assert settings.log_level == "DEBUG"
    assert settings.data_dir == Path("/tmp/data")


def test_invalid_env_raises_settings_error() -> None:
    with pytest.raises(SettingsError):
        Settings.from_env({"MP_CACHE_BACKEND": "memcached"})


def test_error_envelope_shape() -> None:
    err = SymbolNotFoundError("unknown symbol", details={"symbol": "XYZ"})
    assert err.status_code == 404
    assert err.to_dict() == {
        "error": {
            "code": "symbol_not_found",
            "message": "unknown symbol",
            "details": {"symbol": "XYZ"},
        }
    }
