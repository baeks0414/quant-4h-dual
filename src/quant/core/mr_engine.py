# src/quant/core/mr_engine.py
# ============================================================
# MR 전용 Engine (Dual Portfolio 방식)
# - Engine 기본 기능 상속
# - CHOP MR 포지션의 max_hold_bars 타임아웃 관리
# - 추세 전환 시 MR 포지션 즉시 청산 (MRStrategy에서 FLAT 신호 발생)
# ============================================================

from __future__ import annotations

from typing import Optional, Dict
from datetime import datetime

import numpy as np

from quant.core.engine import Engine, EngineResult
from quant.config.presets import PortfolioBTConfig
from quant.data.models import FeatureRow
from quant.core.portfolio import Portfolio
from quant.core.risk import RiskManager
from quant.execution.broker_base import Broker


class MREngine(Engine):
    """
    MR 전용 엔진. max_hold_bars 타임아웃을 심볼별로 추적.
    """

    def __init__(self, cfg: PortfolioBTConfig, strategy, broker: Broker,
                 risk: RiskManager, portfolio: Portfolio):
        super().__init__(cfg, strategy, broker, risk, portfolio)
        # 심볼별 MR 포지션 보유봉 카운터
        self._mr_hold_bars: Dict[str, int] = {s: 0 for s in cfg.symbols}
        self._mr_max_hold = int(getattr(cfg, "mr_max_hold_bars", 12))

    def on_bar(self, row: FeatureRow, funding_rate: Optional[float] = None) -> None:
        t = row.ts
        s = row.symbol

        self.portfolio.update_close(s, row.close)
        self.portfolio.bar_count += 1
        self._stop_check_intrabar(t, s, row.open, row.high, row.low)

        p = self.portfolio.positions[s]

        # ── MR hold-bar 타임아웃 체크 ──
        if s not in self._mr_hold_bars:
            self._mr_hold_bars[s] = 0

        if p.side != 0:
            self._mr_hold_bars[s] += 1
            if self._mr_hold_bars[s] >= self._mr_max_hold:
                # 최대 보유봉 초과 → 현재가에서 강제 청산
                slippage = float(self.cfg.slippage)
                if p.side > 0:
                    exit_px = float(row.close) * (1.0 - slippage)
                    pnl = (exit_px - p.entry) * p.qty
                    trade_type = "STOP_LONG"
                else:
                    exit_px = float(row.close) * (1.0 + slippage)
                    pnl = (p.entry - exit_px) * p.qty
                    trade_type = "STOP_SHORT"

                notional = abs(exit_px * p.qty)
                fee = notional * float(self.cfg.fee_rate)
                self.portfolio.cash -= fee
                self.portfolio.cash += pnl
                self.portfolio.trades.append({
                    "time": t, "symbol": s,
                    "type": trade_type,
                    "entry": p.entry, "exit": exit_px,
                    "qty": p.qty, "pnl": float(pnl),
                    "note": f"mr_timeout_{self._mr_hold_bars[s]}bars",
                })
                self.portfolio.positions[s] = p.__class__()
                self._mr_hold_bars[s] = 0
                self._trail_update(s, row.close, row.atr14)
                return
        else:
            # 포지션 없으면 카운터 리셋
            self._mr_hold_bars[s] = 0

        # ── 전략 신호 처리 ──
        from quant.core.events import SignalEvent
        sig: SignalEvent = self.strategy.on_bar(row, funding_rate)
        if sig is None:
            return

        order_tuples = self.risk.signal_to_orders(sig, self.portfolio, row.close, row)

        for od, is_pyramid in order_tuples:
            fill = self.broker.execute(od, t, row.close)
            if fill is None:
                continue
            # 새 진입 시 hold-bar 카운터 리셋
            if not is_pyramid and od.reduce_only is False:
                self._mr_hold_bars[s] = 0
            self.portfolio.apply_fill(fill, stop_price=od.stop_price,
                                      is_pyramid=is_pyramid)

        self._trail_update(s, row.close, row.atr14)
