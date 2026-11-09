"""Provider that serves candles from CSV files (``<SYMBOL>_<interval>.csv``)."""

from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path

import pandas as pd

from market_pulse.errors import ProviderError, SymbolNotFoundError, UnsupportedIntervalError
from market_pulse.providers.base import (
    SUPPORTED_INTERVALS,
    MarketDataProvider,
    SymbolInfo,
    normalize_candles,
    split_symbol,
)

_FILE_RE = re.compile(r"^(?P<symbol>[A-Z0-9]+)_(?P<interval>\d+[mhd])\.csv$")


class CSVProvider(MarketDataProvider):
    """Read OHLCV candles from a directory of CSV files.

    Lines starting with ``#`` are treated as comments, which the bundled data uses to
    label itself as synthetic. Parsed files are memoized by modification time.
    """

    name = "csv"

    def __init__(self, data_dir: Path | str, *, synthetic: bool = True) -> None:
        self.data_dir = Path(data_dir)
        self.synthetic = synthetic
        self._frames: dict[Path, tuple[float, pd.DataFrame]] = {}
        self._lock = threading.Lock()

    def _index(self) -> dict[str, dict[str, Path]]:
        """Map ``symbol -> interval -> path`` for files present in ``data_dir``."""
        if not self.data_dir.is_dir():
            raise ProviderError(f"data directory not found: {self.data_dir}")
        index: dict[str, dict[str, Path]] = {}
        for path in sorted(self.data_dir.glob("*.csv")):
            match = _FILE_RE.match(path.name)
            if match and match["interval"] in SUPPORTED_INTERVALS:
                index.setdefault(match["symbol"], {})[match["interval"]] = path
        return index

    def _load(self, path: Path) -> pd.DataFrame:
        mtime = path.stat().st_mtime
        with self._lock:
            cached = self._frames.get(path)
            if cached and cached[0] == mtime:
                return cached[1]
        try:
            frame = normalize_candles(pd.read_csv(path, comment="#"))
        except (ValueError, KeyError, pd.errors.ParserError) as exc:
            raise ProviderError(f"failed to parse {path.name}: {exc}") from exc
        with self._lock:
            self._frames[path] = (mtime, frame)
        return frame

    def _get_ohlcv_sync(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        index = self._index()
        intervals = index.get(symbol.upper())
        if intervals is None:
            raise SymbolNotFoundError(
                f"unknown symbol {symbol!r}", details={"available": sorted(index)}
            )
        path = intervals.get(interval)
        if path is None:
            raise UnsupportedIntervalError(
                f"interval {interval!r} not available for {symbol.upper()}",
                details={"supported": sorted(intervals)},
            )
        return self._load(path).tail(limit).reset_index(drop=True)

    async def list_symbols(self) -> list[SymbolInfo]:
        """List symbols found on disk with the intervals available for each."""
        index = await asyncio.to_thread(self._index)
        infos = []
        for symbol, intervals in index.items():
            base, quote = split_symbol(symbol)
            ordered = tuple(i for i in SUPPORTED_INTERVALS if i in intervals)
            infos.append(SymbolInfo(symbol, ordered, base, quote, synthetic=self.synthetic))
        return infos

    async def get_ohlcv(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """Return the last ``limit`` candles from the matching CSV file."""
        return await asyncio.to_thread(self._get_ohlcv_sync, symbol, interval, limit)
