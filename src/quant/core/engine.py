from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

import numpy as np
import pandas as pd

from quant.config.presets import PortfolioBTConfig
from quant.data.models import FeatureRow
from quant.core.portfolio import Portfolio
from quant.core.risk import RiskManager
from quant.execution.broker_base import Broker
from quant.core.events import SignalEvent


@dataclass
class EngineResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame


class Engine:
    def __init__(self, cfg: PortfolioBTConfig, strategy, broker: Broker, risk: RiskManager, portfolio: Portfolio):
        self.cfg = cfg
        self.strategy = strategy
        self.broker = broker
        self.risk = risk
        self.portfolio = portfolio

        self.peak = portfolio.equity
        self.curve_rows: List[dict] = []
        # Dynamic Params v2: trail_atr_mult locked at entry time, per symbol.
        self._entry_trail_mult: dict[str, float] = {}

    def _elapsed_bars(self, current_time: Optional[datetime], entry_time: Optional[datetime]) -> Optional[float]:
        if current_time is None or entry_time is None:
            return None
        interval_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
        bar_secs = interval_map.get(self.cfg.interval, 14400)
        return (current_time - entry_time).total_seconds() / bar_secs

    def _stop_check_intrabar(self, t: datetime, symbol: str, o: float, h: float, l: float) -> None:
        p = self.portfolio.positions[symbol]
        if p.side == 0 or p.stop is None:
            return

        if p.side > 0 and l <= p.stop:
            exit_px = float(p.stop) * (1 - float(self.cfg.slippage))
            notional = abs(exit_px * p.qty)
            fee = notional * float(self.cfg.fee_rate)
            self.portfolio.cash -= fee
            pnl = (exit_px - p.entry) * p.qty
            self.portfolio.cash += pnl
            self.portfolio.trades.append(
                {
                    "time": t,
                    "symbol": symbol,
                    "type": "STOP_LONG",
                    "entry": p.entry,
                    "exit": exit_px,
                    "qty": p.qty,
                    "pnl": float(pnl),
                    "note": "",
                }
            )
            self.portfolio.last_exit_time[symbol] = t
            self.portfolio.last_exit_side[symbol] = p.side
            self.portfolio.positions[symbol] = p.__class__()
            self._entry_trail_mult.pop(symbol, None)

        elif p.side < 0 and h >= p.stop:
            exit_px = float(p.stop) * (1 + float(self.cfg.slippage))
            notional = abs(exit_px * p.qty)
            fee = notional * float(self.cfg.fee_rate)
            self.portfolio.cash -= fee
            pnl = (p.entry - exit_px) * p.qty
            self.portfolio.cash += pnl
            self.portfolio.trades.append(
                {
                    "time": t,
                    "symbol": symbol,
                    "type": "STOP_SHORT",
                    "entry": p.entry,
                    "exit": exit_px,
                    "qty": p.qty,
                    "pnl": float(pnl),
                    "note": "",
                }
            )
            self.portfolio.last_exit_time[symbol] = t
            self.portfolio.last_exit_side[symbol] = p.side
            self.portfolio.positions[symbol] = p.__class__()
            self._entry_trail_mult.pop(symbol, None)

    def _trail_update(
        self,
        symbol: str,
        close_px: float,
        atr14: float,
        current_time: Optional[datetime] = None,
        row: Optional[FeatureRow] = None,
    ) -> None:
        p = self.portfolio.positions[symbol]
        if p.side == 0:
            self._entry_trail_mult.pop(symbol, None)
            return
        if np.isnan(atr14):
            return

        min_hold = int(getattr(self.cfg, "min_hold_bars", 0))
        if min_hold > 0 and current_time is not None and p.entry_time is not None:
            elapsed_bars = self._elapsed_bars(current_time, p.entry_time)
            if elapsed_bars is not None and elapsed_bars < min_hold:
                return

        # Dynamic Params v2: use trail_mult locked at entry time (ADX-tier based).
        # Mutually exclusive with enable_adaptive_trail.
        if bool(getattr(self.cfg, "enable_dynamic_params", False)) and symbol in self._entry_trail_mult:
            trail_mult = self._entry_trail_mult[symbol]
        else:
            trail_mult = float(self.cfg.trail_atr_mult)
            if bool(getattr(self.cfg, "enable_adaptive_trail", False)) and row is not None:
                adx_v = float(getattr(row, "adx14", float("nan")))
                if not np.isnan(adx_v):
                    if adx_v >= float(getattr(self.cfg, "trail_adx_widen_threshold", 38.0)):
                        trail_mult *= float(getattr(self.cfg, "trail_widen_mult", 1.2))
                    elif adx_v <= float(getattr(self.cfg, "trail_adx_tighten_threshold", 22.0)):
                        trail_mult *= float(getattr(self.cfg, "trail_tighten_mult", 0.9))
                if str(getattr(row, "regime", "")) == "VOL_EXPAND":
                    trail_mult *= float(getattr(self.cfg, "trail_vol_expand_mult", 1.0))
                trail_mult = max(0.5, trail_mult)

        if p.side > 0:
            new_stop = close_px - trail_mult * atr14
            p.stop = max(p.stop if p.stop is not None else -np.inf, new_stop)
        else:
            new_stop = close_px + trail_mult * atr14
            p.stop = min(p.stop if p.stop is not None else np.inf, new_stop)

        self.portfolio.positions[symbol] = p

    def on_bar(self, row: FeatureRow, funding_rate: Optional[float] = None) -> None:
        t = row.ts
        s = row.symbol

        self.portfolio.update_close(s, row.close)
        self.portfolio.bar_count += 1
        self._stop_check_intrabar(t, s, row.open, row.high, row.low)

        sig: SignalEvent = self.strategy.on_bar(row, funding_rate)
        if sig is None:
            return

        min_signal_exit_hold = int(getattr(self.cfg, "min_signal_exit_hold_bars", 0))
        if min_signal_exit_hold > 0 and sig.action == "FLAT":
            p = self.portfolio.positions[s]
            if p.side != 0:
                elapsed_bars = self._elapsed_bars(t, p.entry_time)
                if elapsed_bars is not None and elapsed_bars < min_signal_exit_hold:
                    sig = SignalEvent(s, "HOLD", None, f"signal exit hold ({elapsed_bars:.1f}/{min_signal_exit_hold} bars)")

        flip_cd = int(getattr(self.cfg, "flip_cooldown_bars", 0))
        if flip_cd > 0 and sig.action in ("LONG", "SHORT"):
            last_exit_t = self.portfolio.last_exit_time.get(s)
            last_exit_side = self.portfolio.last_exit_side.get(s, 0)
            if last_exit_t is not None and last_exit_side != 0:
                new_side = 1 if sig.action == "LONG" else -1
                if new_side != last_exit_side:
                    interval_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
                    bar_secs = interval_map.get(self.cfg.interval, 14400)
                    elapsed = (t - last_exit_t).total_seconds() / bar_secs
                    if elapsed < flip_cd:
                        sig = SignalEvent(s, "HOLD", None, f"flip cooldown ({elapsed:.1f}/{flip_cd} bars)")

        order_tuples = self.risk.signal_to_orders(sig, self.portfolio, row.close, row)

        new_entry_filled = False
        for od, is_pyramid in order_tuples:
            fill = self.broker.execute(od, t, row.close)
            if fill is None:
                continue
            self.portfolio.apply_fill(fill, stop_price=od.stop_price, is_pyramid=is_pyramid)
            if not is_pyramid and sig.action in ("LONG", "SHORT"):
                new_entry_filled = True

        # Dynamic Params v2: lock ADX-tier trail_atr_mult at entry time.
        if new_entry_filled and bool(getattr(self.cfg, "enable_dynamic_params", False)):
            from quant.core.dynamic_params import resolve
            override = resolve(row)
            self._entry_trail_mult[s] = override.trail_atr_mult

        self._trail_update(s, row.close, row.atr14, current_time=t, row=row)

    def snapshot_curve(self, t: datetime) -> None:
        eq = float(self.portfolio.equity)
        self.peak = max(self.peak, eq)
        dd = (eq / self.peak) - 1.0

        row = {"time": t, "equity": eq, "drawdown": float(dd)}
        for s in self.cfg.symbols:
            row[f"pos_{s}"] = int(self.portfolio.positions[s].side)
        self.curve_rows.append(row)

    def result(self) -> EngineResult:
        ec = pd.DataFrame(self.curve_rows).set_index("time") if self.curve_rows else pd.DataFrame()
        tr = pd.DataFrame(self.portfolio.trades) if self.portfolio.trades else pd.DataFrame()
        return EngineResult(ec, tr)
