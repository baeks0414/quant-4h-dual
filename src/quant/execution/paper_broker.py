from __future__ import annotations

from typing import Optional
from datetime import datetime

from quant.config.presets import PortfolioBTConfig
from quant.core.events import OrderEvent, FillEvent
from quant.execution.broker_base import Broker
from quant.core.types import Side


class PaperBroker(Broker):
    def __init__(self, cfg: PortfolioBTConfig):
        self.cfg = cfg

    def execute(self, order: OrderEvent, ts: datetime, ref_price: float) -> Optional[FillEvent]:
        if order.qty <= 0:
            return None

        # slippage model
        if order.side == Side.BUY:
            px = float(ref_price) * (1 + float(self.cfg.slippage))
        else:
            px = float(ref_price) * (1 - float(self.cfg.slippage))

        notional = abs(px * float(order.qty))
        fee = notional * float(self.cfg.fee_rate)

        return FillEvent(
            symbol=order.symbol,
            ts=ts,
            side=order.side,
            qty=float(order.qty),
            price=float(px),
            fee=float(fee),
            reason=order.reason,
        )
