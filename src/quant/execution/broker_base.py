# src/quant/execution/broker_base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Protocol, Dict, runtime_checkable
from datetime import datetime

from quant.core.events import OrderEvent, FillEvent


class Broker(ABC):
    @abstractmethod
    def execute(self, order: OrderEvent, ts: datetime, ref_price: float) -> Optional[FillEvent]:
        ...


@runtime_checkable
class SupportsPositions(Protocol):
    def get_open_positions(self) -> Dict[str, float]: ...


@runtime_checkable
class SupportsBalance(Protocol):
    def get_usdt_wallet_balance(self) -> float: ...
