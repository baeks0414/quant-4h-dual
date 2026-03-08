from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Bar:
    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Funding:
    symbol: str
    ts: datetime
    rate: float


@dataclass(frozen=True)
class FeatureRow:
    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    ema_fast: float
    ema_slow: float
    atr14: float
    atr30: float
    adx14: float

    regime: str
    donchian_hh: Optional[float] = None
    donchian_ll: Optional[float] = None

    # CHOP Mean-Reversion features
    mr_mean: Optional[float] = None
    mr_std: Optional[float] = None

    # BB-based MR features
    bb_mean: Optional[float] = None
    bb_std: Optional[float] = None

    # Trend innovation features
    ema_fast_slope_3: Optional[float] = None
    adx_slope_3: Optional[float] = None
