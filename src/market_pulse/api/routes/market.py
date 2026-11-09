"""Market data endpoints: symbols, OHLCV, indicators and signals."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from market_pulse.api.container import Container
from market_pulse.api.deps import get_container
from market_pulse.api.schemas import (
    SYMBOL_PATTERN,
    CandleOut,
    ErrorResponse,
    IndicatorsResponse,
    Interval,
    OHLCVResponse,
    SignalOut,
    SignalsResponse,
    SymbolOut,
    SymbolsResponse,
)
from market_pulse.api.serialization import frame_to_records
from market_pulse.errors import ProviderError
from market_pulse.indicators import compute_indicators, parse_specs
from market_pulse.signals import generate_signals, summarize_bias

#: Extra bars fetched before the requested window so indicators are warmed up.
INDICATOR_WARMUP_BARS = 250
SIGNAL_LOOKBACK_BARS = 300

router = APIRouter(
    responses={
        404: {"model": ErrorResponse, "description": "Unknown symbol"},
        422: {"model": ErrorResponse, "description": "Invalid parameters"},
        502: {"model": ErrorResponse, "description": "Upstream provider error"},
    },
)

SymbolPath = Annotated[
    str,
    Path(pattern=SYMBOL_PATTERN, description="Trading pair, e.g. BTCUSDT", examples=["BTCUSDT"]),
]
IntervalQuery = Annotated[Interval, Query(description="Candle interval")]
LimitQuery = Annotated[
    int | None, Query(ge=1, le=1000, description="Number of most recent bars to return")
]


def _resolve_limit(container: Container, limit: int | None) -> int:
    settings = container.settings
    return min(limit or settings.default_limit, settings.max_limit)


@router.get(
    "/symbols", response_model=SymbolsResponse, tags=["market data"], summary="List symbols"
)
async def list_symbols(container: Container = Depends(get_container)) -> SymbolsResponse:
    """List the symbols (and intervals) available from the active data provider."""
    infos = await container.provider.list_symbols()
    return SymbolsResponse(
        provider=container.provider.name,
        symbols=[
            SymbolOut(
                symbol=i.symbol,
                base=i.base,
                quote=i.quote,
                intervals=list(i.intervals),
                synthetic=i.synthetic,
            )
            for i in infos
        ],
    )


@router.get(
    "/ohlcv/{symbol}", response_model=OHLCVResponse, tags=["market data"], summary="OHLCV candles"
)
async def get_ohlcv(
    symbol: SymbolPath,
    interval: IntervalQuery = "1h",
    limit: LimitQuery = None,
    container: Container = Depends(get_container),
) -> OHLCVResponse:
    """Return the most recent candles for a symbol, oldest first."""
    symbol = symbol.upper()
    frame = await container.provider.get_ohlcv(symbol, interval, _resolve_limit(container, limit))
    return OHLCVResponse(
        symbol=symbol,
        interval=interval,
        provider=container.provider.name,
        synthetic=container.provider.synthetic,
        count=len(frame),
        candles=[CandleOut(**row) for row in frame_to_records(frame)],
    )


@router.get(
    "/indicators/{symbol}",
    response_model=IndicatorsResponse,
    tags=["indicators"],
    summary="Technical indicators",
)
async def get_indicators(
    symbol: SymbolPath,
    names: Annotated[
        str,
        Query(
            description="Comma-separated specs: sma_N, ema_N, rsi[_N], macd, bbands[_N], "
            "atr[_N], stoch[_N]",
            examples=["rsi,ema_20,macd,bbands,atr"],
            max_length=200,
        ),
    ] = "rsi,ema_20,macd,bbands,atr",
    interval: IntervalQuery = "1h",
    limit: LimitQuery = None,
    container: Container = Depends(get_container),
) -> IndicatorsResponse:
    """Compute indicators over the latest ``limit`` bars (warm-up bars are fetched too)."""
    symbol = symbol.upper()
    specs = parse_specs(names)
    window = _resolve_limit(container, limit)
    candles = await container.provider.get_ohlcv(symbol, interval, window + INDICATOR_WARMUP_BARS)
    values = compute_indicators(candles, specs)
    frame = candles[["open_time", "close"]].join(values).tail(window)
    return IndicatorsResponse(
        symbol=symbol,
        interval=interval,
        indicators=[s.key for s in specs],
        columns=list(values.columns),
        count=len(frame),
        data=frame_to_records(frame),
    )


@router.get(
    "/signals/{symbol}",
    response_model=SignalsResponse,
    tags=["signals"],
    summary="Rule-based signals (not financial advice)",
)
async def get_signals(
    symbol: SymbolPath,
    interval: IntervalQuery = "1h",
    container: Container = Depends(get_container),
) -> SignalsResponse:
    """Evaluate RSI oversold/overbought, EMA(9/21) cross and Bollinger breakout signals."""
    symbol = symbol.upper()
    candles = await container.provider.get_ohlcv(symbol, interval, SIGNAL_LOOKBACK_BARS)
    if candles.empty:
        raise ProviderError(f"no candles available for {symbol}")
    signals = generate_signals(candles)
    return SignalsResponse(
        symbol=symbol,
        interval=interval,
        as_of=candles["open_time"].iloc[-1].to_pydatetime(),
        close=float(candles["close"].iloc[-1]),
        bias=summarize_bias(signals),
        signals=[SignalOut(**s.to_dict()) for s in signals],
    )
