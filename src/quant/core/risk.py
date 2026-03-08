from __future__ import annotations

from typing import List

from quant.config.presets import PortfolioBTConfig
from quant.core.events import SignalEvent, OrderEvent
from quant.core.types import Side, OrderType, TimeInForce
from quant.core.portfolio import Portfolio


class RiskManager:
    def __init__(self, cfg: PortfolioBTConfig):
        self.cfg = cfg

    def _signal_entry_scale(self, signal: SignalEvent) -> float:
        note = str(getattr(signal, "note", ""))
        marker = "guard_size_down="
        if marker not in note:
            return 1.0
        tail = note.split(marker, 1)[1]
        raw = tail.split("|", 1)[0].strip()
        try:
            value = float(raw)
        except ValueError:
            return 1.0
        return max(0.0, min(value, 1.0))

    def signal_to_orders(self, signal: SignalEvent, portfolio: Portfolio,
                         close_px: float, row=None) -> List[tuple]:
        """반환: List of (OrderEvent, is_pyramid)"""
        cfg = self.cfg
        s = signal.symbol
        p = portfolio.positions[s]
        orders: List[tuple] = []

        if signal is None:
            return orders
        if signal.action == "HOLD":
            return orders

        if signal.action == "FLAT":
            if p.side != 0:
                orders.append((
                    OrderEvent(
                        symbol=s,
                        side=Side.SELL if p.side > 0 else Side.BUY,
                        qty=p.qty,
                        order_type=OrderType.MARKET,
                        tif=TimeInForce.GTC,
                        reduce_only=True,
                        reason="CLOSE_BY_SIGNAL",
                    ), False
                ))
            return orders

        if signal.action not in ("LONG", "SHORT") or signal.stop_price is None:
            return orders

        desired = 1 if signal.action == "LONG" else -1
        signal_scale = self._signal_entry_scale(signal)

        # 동일 방향 → 무시 (기본 RiskManager는 피라미딩 없음)
        if p.side == desired:
            return orders

        # 반대 방향 → 청산
        if p.side != 0 and p.side != desired:
            orders.append((
                OrderEvent(
                    symbol=s,
                    side=Side.SELL if p.side > 0 else Side.BUY,
                    qty=p.qty,
                    order_type=OrderType.MARKET,
                    tif=TimeInForce.GTC,
                    reduce_only=True,
                    reason="FLIP_CLOSE",
                ), False
            ))
        equity = portfolio.equity
        risk_usdt = equity * cfg.risk_per_trade

        stop_pct = abs(close_px - signal.stop_price) / max(close_px, 1e-12)
        stop_pct = max(stop_pct, 0.001)

        notional = (risk_usdt * signal_scale) / stop_pct
        notional = min(notional, equity * cfg.max_leverage)
        qty = notional / close_px

        est_risk = abs(close_px - signal.stop_price) * qty
        if portfolio.open_risk_usdt() + est_risk > equity * cfg.portfolio_risk_cap:
            return orders

        orders.append((
            OrderEvent(
                symbol=s,
                side=Side.BUY if desired > 0 else Side.SELL,
                qty=qty,
                order_type=OrderType.MARKET,
                tif=TimeInForce.GTC,
                reduce_only=False,
                stop_price=signal.stop_price,
                reason=signal.note,
            ), False
        ))
        return orders
