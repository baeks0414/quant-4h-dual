from __future__ import annotations

from enum import Enum


class Side(int, Enum):
    BUY = 1
    SELL = -1


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
