from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from quant.core.types import Side, OrderType, TimeInForce


@dataclass(frozen=True)
class SignalEvent:
    symbol: str
    action: str  # "LONG"|"SHORT"|"FLAT"|"HOLD"
    stop_price: Optional[float]
    note: str = ""


@dataclass(frozen=True)
class OrderEvent:
    symbol: str
    side: Side
    qty: float
    order_type: OrderType = OrderType.MARKET
    tif: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    stop_price: Optional[float] = None
    reason: str = ""


@dataclass(frozen=True)
class FillEvent:
    symbol: str
    ts: datetime
    side: Side
    qty: float
    price: float
    fee: float
    reason: str = ""
