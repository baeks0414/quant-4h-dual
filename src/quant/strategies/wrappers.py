from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional

from quant.core.events import SignalEvent
from quant.data.models import FeatureRow
from quant.strategies.base import Strategy


@dataclass(frozen=True)
class MarketRegimeGateConfig:
    market_symbol: str
    allow_regimes: Iterable[str] = ("STRONG_TREND", "VOL_EXPAND")
    market_off_allow_symbol_regimes: Iterable[str] = ()
    state_gate_symbol_regimes: Iterable[str] = ()
    state_gate_allowed_market_regimes: Iterable[str] = ()
    state_gate_min_drawdown: float = -1.0
    state_gate_max_drawdown: float = 0.0
    state_gate_min_market_adx: float = 0.0
    state_gate_max_market_adx: float = 100.0
    state_gate_min_market_ema_spread_atr: float = 0.0
    state_gate_min_market_regime_streak: int = 1
    state_gate_max_market_regime_streak: int = 10_000
    bear_short_gate_allowed_market_regimes: Iterable[str] = ()
    bear_short_gate_min_market_adx: float = 0.0
    enable_conditional_trend_long_guard: bool = False
    trend_long_guard_allowed_market_regimes: Iterable[str] = ("STRONG_TREND",)
    trend_long_guard_symbol_spread_atr_min: float = 0.0
    trend_long_guard_market_spread_atr_min: float = 0.0
    trend_long_guard_market_regime_streak_min: int = 0
    trend_long_guard_market_adx_max: float = 100.0
    entry_block_only: bool = False
    per_symbol_direction: bool = False


class MarketRegimeGate(Strategy):
    def __init__(self, base: Strategy, cfg: MarketRegimeGateConfig):
        self.base = base
        self.cfg = cfg
        self._allow_regimes = set(cfg.allow_regimes)
        self._market_off_allow_symbol_regimes = set(cfg.market_off_allow_symbol_regimes)
        self._state_gate_symbol_regimes = set(cfg.state_gate_symbol_regimes)
        self._state_gate_allowed_market_regimes = set(cfg.state_gate_allowed_market_regimes)
        self._bear_short_gate_allowed_market_regimes = set(cfg.bear_short_gate_allowed_market_regimes)
        self._trend_long_guard_allowed_market_regimes = set(cfg.trend_long_guard_allowed_market_regimes)
        self.market_on: bool = False
        self.last_market_regime: Optional[str] = None
        self.last_market_regime_streak: int = 0
        self.current_drawdown: float = 0.0
        self._peak_equity: Optional[float] = None
        self.last_market_adx: Optional[float] = None
        self.last_market_ema_spread_atr: Optional[float] = None
        self._symbol_bar_seq: dict[str, int] = {}
        self._guarded_pullback_arms: dict[str, int] = {}

    def _cfg_value(self, name: str, default):
        base_cfg = getattr(self.base, "cfg", None)
        if base_cfg is not None and hasattr(base_cfg, name):
            return getattr(base_cfg, name)
        return getattr(self.cfg, name, default)

    def _next_symbol_bar_seq(self, symbol: str) -> int:
        seq = int(self._symbol_bar_seq.get(symbol, 0)) + 1
        self._symbol_bar_seq[symbol] = seq
        return seq

    def _clear_guarded_pullback_arm(self, symbol: str) -> None:
        self._guarded_pullback_arms.pop(symbol, None)

    def _arm_guarded_pullback(self, symbol: str) -> None:
        wait_bars = max(0, int(self._cfg_value("trend_long_guard_pullback_max_wait_bars", 0)))
        if wait_bars <= 0:
            self._clear_guarded_pullback_arm(symbol)
            return
        current_seq = int(self._symbol_bar_seq.get(symbol, 0))
        self._guarded_pullback_arms[symbol] = current_seq + wait_bars

    def _guarded_pullback_is_armed(self, symbol: str) -> bool:
        expiry = self._guarded_pullback_arms.get(symbol)
        if expiry is None:
            return False
        current_seq = int(self._symbol_bar_seq.get(symbol, 0))
        if current_seq > expiry:
            self._clear_guarded_pullback_arm(symbol)
            return False
        return True

    def update_market(self, market_row: FeatureRow, equity: Optional[float] = None) -> None:
        regime = str(market_row.regime)
        if regime == self.last_market_regime:
            self.last_market_regime_streak += 1
        else:
            self.last_market_regime_streak = 1
        self.last_market_regime = regime
        self.market_on = regime in self._allow_regimes

        adx_v = getattr(market_row, "adx14", None)
        adx_f = float(adx_v) if adx_v is not None else float("nan")
        self.last_market_adx = None if math.isnan(adx_f) else adx_f

        atr_v = float(getattr(market_row, "atr14", float("nan")))
        ema_f = float(getattr(market_row, "ema_fast", float("nan")))
        ema_s = float(getattr(market_row, "ema_slow", float("nan")))
        if math.isnan(atr_v) or atr_v <= 0.0 or math.isnan(ema_f) or math.isnan(ema_s):
            self.last_market_ema_spread_atr = None
        else:
            self.last_market_ema_spread_atr = abs(ema_f - ema_s) / atr_v

        if equity is not None:
            equity_f = max(float(equity), 1e-12)
            if self._peak_equity is None:
                self._peak_equity = equity_f
            self._peak_equity = max(self._peak_equity, equity_f)
            self.current_drawdown = equity_f / max(self._peak_equity, 1e-12) - 1.0

    def _trend_quality_ok_long(self, row: FeatureRow) -> bool:
        if not bool(self._cfg_value("enable_innov_trend_filter", False)):
            return True
        ema_slope_3 = getattr(row, "ema_fast_slope_3", None)
        adx_slope_3 = getattr(row, "adx_slope_3", None)
        if ema_slope_3 is None:
            return False
        ema_slope_3 = float(ema_slope_3)
        if math.isnan(ema_slope_3):
            return False
        if ema_slope_3 < float(self._cfg_value("trend_min_ema_slope_atr", 0.0)):
            return False
        min_adx_slope = float(self._cfg_value("trend_min_adx_slope_3", -999.0))
        if min_adx_slope > -900.0:
            if adx_slope_3 is None:
                return False
            adx_slope_3 = float(adx_slope_3)
            if math.isnan(adx_slope_3) or adx_slope_3 < min_adx_slope:
                return False
        return True

    def _guarded_pullback_signal(self, row: FeatureRow) -> Optional[SignalEvent]:
        if str(self._cfg_value("trend_long_guard_mode", "block")) != "pullback_only":
            return None
        if not self._guarded_pullback_is_armed(row.symbol):
            return None
        if str(getattr(row, "regime", "")) != "STRONG_TREND":
            self._clear_guarded_pullback_arm(row.symbol)
            return None

        atr_v = float(getattr(row, "atr14", float("nan")))
        ema_fast = float(getattr(row, "ema_fast", float("nan")))
        ema_slow = float(getattr(row, "ema_slow", float("nan")))
        close_px = float(getattr(row, "close", float("nan")))
        if (
            math.isnan(atr_v)
            or atr_v <= 0.0
            or math.isnan(ema_fast)
            or math.isnan(ema_slow)
            or math.isnan(close_px)
        ):
            return None
        if ema_fast <= ema_slow:
            self._clear_guarded_pullback_arm(row.symbol)
            return None
        spread_atr = (ema_fast - ema_slow) / atr_v
        if spread_atr < float(self._cfg_value("trend_min_ema_spread_atr", 0.0)):
            return None
        if not self._trend_quality_ok_long(row):
            return None

        pull_gap = (ema_fast - close_px) / atr_v
        pull_gap_max = float(self._cfg_value("trend_pullback_max_gap_atr", 0.8))
        if close_px < ema_slow or pull_gap < 0.0 or pull_gap > pull_gap_max:
            return None

        stop_mult = float(self._cfg_value("trend_pullback_stop_atr_mult", 2.2))
        size_scale = float(self._cfg_value("trend_long_guard_size_down_scale", 1.0))
        self._clear_guarded_pullback_arm(row.symbol)
        note = "guarded trend pullback long"
        if size_scale < 0.999:
            note += f"|guard_size_down={size_scale:.3f}"
        return SignalEvent(row.symbol, "LONG", close_px - stop_mult * atr_v, note)

    def _state_gate_allows(self, symbol_regime: str) -> bool:
        if symbol_regime not in self._state_gate_symbol_regimes:
            return True

        if self._state_gate_allowed_market_regimes and self.last_market_regime not in self._state_gate_allowed_market_regimes:
            return False

        dd = float(self.current_drawdown)
        if dd < float(self.cfg.state_gate_min_drawdown):
            return False
        if dd > float(self.cfg.state_gate_max_drawdown):
            return False

        if self.last_market_regime_streak < int(self.cfg.state_gate_min_market_regime_streak):
            return False
        if self.last_market_regime_streak > int(self.cfg.state_gate_max_market_regime_streak):
            return False

        min_adx = float(self.cfg.state_gate_min_market_adx)
        max_adx = float(self.cfg.state_gate_max_market_adx)
        if min_adx > 0.0 or max_adx < 100.0:
            if self.last_market_adx is None:
                return False
            if self.last_market_adx < min_adx or self.last_market_adx > max_adx:
                return False

        min_spread = float(self.cfg.state_gate_min_market_ema_spread_atr)
        if min_spread > 0.0:
            if self.last_market_ema_spread_atr is None:
                return False
            if self.last_market_ema_spread_atr < min_spread:
                return False

        return True

    def _bear_short_gate_allows(self, sig: SignalEvent) -> bool:
        if sig.action != "SHORT":
            return True
        note = str(getattr(sig, "note", ""))
        if "bear trend short" not in note:
            return True

        if self._bear_short_gate_allowed_market_regimes and self.last_market_regime not in self._bear_short_gate_allowed_market_regimes:
            return False

        min_adx = float(self.cfg.bear_short_gate_min_market_adx)
        if min_adx > 0.0:
            if self.last_market_adx is None or self.last_market_adx < min_adx:
                return False

        return True

    def _conditional_trend_long_guard_blocks(self, row: FeatureRow, sig: SignalEvent) -> bool:
        if not bool(self._cfg_value("enable_conditional_trend_long_guard", False)):
            return False
        if sig.action != "LONG":
            return False
        if str(getattr(sig, "note", "")) != "trend long":
            return False
        if self._trend_long_guard_allowed_market_regimes and self.last_market_regime not in self._trend_long_guard_allowed_market_regimes:
            return False

        atr_v = float(getattr(row, "atr14", float("nan")))
        if math.isnan(atr_v) or atr_v <= 0.0:
            return False
        symbol_spread = abs(float(row.ema_fast) - float(row.ema_slow)) / atr_v

        sym_spread_min = float(self._cfg_value("trend_long_guard_symbol_spread_atr_min", 0.0))
        if sym_spread_min > 0.0 and symbol_spread < sym_spread_min:
            return False

        market_spread_min = float(self._cfg_value("trend_long_guard_market_spread_atr_min", 0.0))
        if market_spread_min > 0.0:
            if self.last_market_ema_spread_atr is None or float(self.last_market_ema_spread_atr) < market_spread_min:
                return False

        streak_min = int(self._cfg_value("trend_long_guard_market_regime_streak_min", 0))
        if streak_min > 0 and self.last_market_regime_streak < streak_min:
            return False

        adx_max = float(self._cfg_value("trend_long_guard_market_adx_max", 100.0))
        if adx_max < 100.0:
            if self.last_market_adx is None or self.last_market_adx > adx_max:
                return False

        return True

    def on_bar(self, row: FeatureRow, funding_rate: Optional[float]) -> SignalEvent:
        self._next_symbol_bar_seq(row.symbol)
        sig = self.base.on_bar(row, funding_rate)
        if sig is None:
            return None  # type: ignore[return-value]

        if sig.action in ("LONG", "SHORT"):
            symbol_regime = str(getattr(row, "regime", ""))
            if not self._state_gate_allows(symbol_regime):
                return SignalEvent(
                    row.symbol,
                    "HOLD",
                    None,
                    f"state_gate_block({symbol_regime}|mkt={self.last_market_regime}|dd={self.current_drawdown:.4f})",
                )
            if not self._bear_short_gate_allows(sig):
                return SignalEvent(
                    row.symbol,
                    "HOLD",
                    None,
                    f"bear_short_gate_block(mkt={self.last_market_regime}|adx={self.last_market_adx})",
                )
            if self._conditional_trend_long_guard_blocks(row, sig):
                guard_mode = str(self._cfg_value("trend_long_guard_mode", "block"))
                size_scale = float(self._cfg_value("trend_long_guard_size_down_scale", 1.0))
                if guard_mode == "size_down":
                    note = "guarded trend long"
                    if size_scale < 0.999:
                        note += f"|guard_size_down={size_scale:.3f}"
                    return SignalEvent(row.symbol, "LONG", sig.stop_price, note)
                if guard_mode == "pullback_only":
                    self._arm_guarded_pullback(row.symbol)
                    return SignalEvent(
                        row.symbol,
                        "HOLD",
                        None,
                        (
                            "conditional_trend_long_guard_arm("
                            f"mkt={self.last_market_regime}|"
                            f"adx={self.last_market_adx}|"
                            f"spread={self.last_market_ema_spread_atr}|"
                            f"streak={self.last_market_regime_streak})"
                        ),
                    )
                return SignalEvent(
                    row.symbol,
                    "HOLD",
                    None,
                    (
                        "conditional_trend_long_guard("
                        f"mkt={self.last_market_regime}|"
                        f"adx={self.last_market_adx}|"
                        f"spread={self.last_market_ema_spread_atr}|"
                        f"streak={self.last_market_regime_streak})"
                    ),
                )
        elif sig.action in ("HOLD", "FLAT"):
            guarded_sig = self._guarded_pullback_signal(row)
            if guarded_sig is not None:
                return guarded_sig

        if self.market_on:
            return sig

        if sig.action in ("LONG", "SHORT"):
            symbol_regime = str(getattr(row, "regime", ""))
            if symbol_regime in self._market_off_allow_symbol_regimes:
                return sig
            return SignalEvent(row.symbol, "HOLD", None, "mkt_off_entry_block")

        if not self.cfg.entry_block_only and sig.action != "HOLD":
            return SignalEvent(row.symbol, "FLAT", None, f"mkt_off_force_flat({self.last_market_regime})")

        return sig
