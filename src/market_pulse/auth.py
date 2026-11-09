"""API-key verification helpers (framework independent)."""

from __future__ import annotations

import secrets
from collections.abc import Iterable


def is_valid_api_key(supplied: str | None, keys: Iterable[str]) -> bool:
    """Constant-time comparison of ``supplied`` against every configured key."""
    if not supplied:
        return False
    # Evaluate every key (no short-circuit) so timing does not depend on key position.
    matches = [secrets.compare_digest(supplied.encode(), key.encode()) for key in keys]
    return any(matches)
