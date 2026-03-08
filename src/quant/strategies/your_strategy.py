from __future__ import annotations

from typing import Optional
import numpy as np

from quant.config.presets import PortfolioBTConfig
from quant.data.models import FeatureRow
from quant.core.events import SignalEvent


class YourStrategy:
    def __init__(self, cfg: PortfolioBTConfig):
        self.cfg = cfg
        self._entry_pending: dict[str, tuple[str, int, float, str]] = {}
        self._regime_state: dict[str, tuple[str, int]] = {}

    def _clear_pending(self, symbol: str) -> None:
        self._entry_pending.pop(symbol, None)

    def _update_regime_streak(self, symbol: str, regime: str) -> int:
        prev_regime, prev_streak = self._regime_state.get(symbol, ("", 0))
        if regime == prev_regime:
            streak = prev_streak + 1
        else:
            streak = 1
        self._regime_state[symbol] = (regime, streak)
        return streak

    def _emit_non_entry(self, symbol: str, action: str, reason: str) -> SignalEvent:
        self._clear_pending(symbol)
        return SignalEvent(symbol, action, None, reason)

    def _emit_entry(
        self,
        symbol: str,
        action: str,
        stop_px: float,
        reason: str,
        regime_streak: int,
        regime_confirm_bars: int,
        entry_confirm_bars: int,
    ) -> SignalEvent:
        # Require regime persistence before allowing new entries.
        if regime_confirm_bars > 1 and regime_streak < regime_confirm_bars:
            self._clear_pending(symbol)
            return SignalEvent(symbol, "HOLD", None, f"regime confirm {regime_streak}/{regime_confirm_bars}")

        # Require repeated same-direction entry signal.
        if entry_confirm_bars <= 1:
            self._clear_pending(symbol)
            return SignalEvent(symbol, action, stop_px, reason)

        prev = self._entry_pending.get(symbol)
        if prev is not None and prev[0] == action:
            count = prev[1] + 1
        else:
            count = 1
        self._entry_pending[symbol] = (action, count, stop_px, reason)

        if count >= entry_confirm_bars:
            self._clear_pending(symbol)
            return SignalEvent(symbol, action, stop_px, reason)
        return SignalEvent(symbol, "HOLD", None, f"{action.lower()} confirm {count}/{entry_confirm_bars}")

    def on_bar(self, row: FeatureRow, funding_rate: Optional[float]) -> SignalEvent:
        cfg = self.cfg
        px = float(row.close)
        a = float(row.atr14)
        regime = str(row.regime)
        regime_confirm_bars = max(1, int(getattr(cfg, "regime_confirm_bars", 1)))
        entry_confirm_bars = max(1, int(getattr(cfg, "entry_confirm_bars", 1)))
        regime_streak = self._update_regime_streak(row.symbol, regime)

        if np.isnan(a):
            return self._emit_non_entry(row.symbol, "HOLD", "atr nan")

        allow_short = bool(getattr(cfg, "enable_short", True))
        vol_strict = bool(getattr(cfg, "vol_breakout_strict", False))
        vol_near_mult = float(getattr(cfg, "vol_break_near_atr_mult", 1.0))
        enable_innov = bool(getattr(cfg, "enable_innov_trend_filter", False))
        trend_min_slope_atr = float(getattr(cfg, "trend_min_ema_slope_atr", 0.0))
        trend_min_adx_slope = float(getattr(cfg, "trend_min_adx_slope_3", -999.0))
        trend_min_spread = float(getattr(cfg, "trend_min_ema_spread_atr", 0.0))
        trend_entry_buf = float(getattr(cfg, "trend_entry_buffer_atr", 0.0))
        short_trend_min_adx = float(getattr(cfg, "trend_short_min_adx", 0.0))
        short_trend_max_adx = float(getattr(cfg, "trend_short_max_adx", 100.0))
        short_trend_min_spread = max(
            trend_min_spread, float(getattr(cfg, "trend_short_min_ema_spread_atr", 0.0))
        )
        short_trend_entry_buf = max(
            trend_entry_buf, float(getattr(cfg, "trend_short_entry_buffer_atr", 0.0))
        )
        short_trend_stop_mult = float(getattr(cfg, "trend_short_stop_atr_mult", 0.0))
        if short_trend_stop_mult <= 0.0:
            short_trend_stop_mult = float(cfg.stop_atr_mult_trend)
        enable_pullback = bool(getattr(cfg, "enable_trend_pullback_entry", False))
        pullback_max_gap_atr = float(getattr(cfg, "trend_pullback_max_gap_atr", 0.8))
        pullback_stop_mult = float(getattr(cfg, "trend_pullback_stop_atr_mult", 2.2))
        vol_min_adx = float(getattr(cfg, "vol_break_min_adx", 0.0))
        vol_max_adx = float(getattr(cfg, "vol_break_max_adx", 100.0))
        vol_min_spread = float(getattr(cfg, "vol_break_min_ema_spread_atr", 0.0))
        vol_min_slope_atr = float(getattr(cfg, "vol_break_min_ema_slope_atr", 0.0))
        vol_long_min_adx = max(vol_min_adx, float(getattr(cfg, "vol_break_long_min_adx", 0.0)))
        vol_short_min_adx = max(vol_min_adx, float(getattr(cfg, "vol_break_short_min_adx", 0.0)))
        vol_long_max_adx = min(vol_max_adx, float(getattr(cfg, "vol_break_long_max_adx", vol_max_adx)))
        vol_short_max_adx = min(vol_max_adx, float(getattr(cfg, "vol_break_short_max_adx", vol_max_adx)))
        vol_long_min_spread = max(vol_min_spread, float(getattr(cfg, "vol_break_long_min_ema_spread_atr", 0.0)))
        vol_short_min_spread = max(vol_min_spread, float(getattr(cfg, "vol_break_short_min_ema_spread_atr", 0.0)))
        vol_long_min_slope_atr = max(
            vol_min_slope_atr, float(getattr(cfg, "vol_break_long_min_ema_slope_atr", 0.0))
        )
        vol_short_min_slope_atr = max(
            vol_min_slope_atr, float(getattr(cfg, "vol_break_short_min_ema_slope_atr", 0.0))
        )
        enable_micro_trend = bool(getattr(cfg, "enable_micro_trend", False))
        micro_min_adx = float(getattr(cfg, "micro_trend_min_adx", 18.0))
        micro_max_adx = float(getattr(cfg, "micro_trend_max_adx", 30.0))
        micro_min_spread = float(getattr(cfg, "micro_trend_min_ema_spread_atr", 0.02))
        micro_entry_buf = float(getattr(cfg, "micro_trend_entry_buffer_atr", 0.02))
        micro_stop_mult = float(getattr(cfg, "micro_trend_stop_atr_mult", 1.6))
        enable_sideways_reversion_alpha = bool(getattr(cfg, "enable_sideways_reversion_alpha", False))
        enable_2025_alpha = bool(getattr(cfg, "enable_2025_alpha", False))
        enable_chop_alpha = bool(
            getattr(cfg, "enable_chop_alpha", False) or enable_sideways_reversion_alpha or enable_2025_alpha
        )
        chop_follow_ema_bias = bool(getattr(cfg, "chop_follow_ema_bias", False))
        chop_use_bb = bool(getattr(cfg, "chop_use_bb", True))
        chop_entry_z = float(getattr(cfg, "chop_entry_z", 1.2))
        chop_exit_z = float(getattr(cfg, "chop_exit_z", 0.3))
        chop_stop_mult = float(getattr(cfg, "chop_stop_atr_mult", 1.4))
        chop_max_adx = float(getattr(cfg, "chop_max_adx", 22.0))
        chop_max_spread = float(getattr(cfg, "chop_max_ema_spread_atr", 0.08))
        enable_low_adx_vol_revert_alpha = bool(getattr(cfg, "enable_low_adx_vol_revert_alpha", False))
        enable_2025_vol_revert_alpha = bool(getattr(cfg, "enable_2025_vol_revert_alpha", False))
        enable_vol_revert_alpha = bool(enable_low_adx_vol_revert_alpha or enable_2025_vol_revert_alpha)
        vol_revert_priority_when_low_trend = bool(getattr(cfg, "vol_revert_priority_when_low_trend", False))
        alpha2025_vol_revert_use_bb = bool(getattr(cfg, "alpha2025_vol_revert_use_bb", True))
        alpha2025_vol_revert_entry_z = float(getattr(cfg, "alpha2025_vol_revert_entry_z", 1.1))
        alpha2025_vol_revert_exit_z = float(getattr(cfg, "alpha2025_vol_revert_exit_z", 0.35))
        alpha2025_vol_revert_stop_mult = float(getattr(cfg, "alpha2025_vol_revert_stop_atr_mult", 1.4))
        alpha2025_vol_revert_max_adx = float(getattr(cfg, "alpha2025_vol_revert_max_adx", 18.0))
        alpha2025_vol_revert_max_spread = float(getattr(cfg, "alpha2025_vol_revert_max_ema_spread_atr", 0.08))
        ema_slope_3 = float(row.ema_fast_slope_3) if row.ema_fast_slope_3 is not None else float("nan")
        adx_slope_3 = float(row.adx_slope_3) if row.adx_slope_3 is not None else float("nan")

        def trend_quality_ok(is_long: bool) -> bool:
            if not enable_innov:
                return True
            if np.isnan(ema_slope_3):
                return False
            slope_dir = ema_slope_3 if is_long else -ema_slope_3
            if slope_dir < trend_min_slope_atr:
                return False
            if trend_min_adx_slope > -900.0:
                if np.isnan(adx_slope_3) or adx_slope_3 < trend_min_adx_slope:
                    return False
            return True

        def emit_vol_revert_signal(adx_val: float, spread_abs_atr: float):
            if not enable_vol_revert_alpha or np.isnan(adx_val):
                return None
            if adx_val > alpha2025_vol_revert_max_adx:
                return None
            if spread_abs_atr > alpha2025_vol_revert_max_spread:
                return None

            mean = row.bb_mean if alpha2025_vol_revert_use_bb else row.mr_mean
            std = row.bb_std if alpha2025_vol_revert_use_bb else row.mr_std
            if mean is None or std is None:
                return None
            mean_f = float(mean)
            std_f = float(std)
            if np.isnan(mean_f) or np.isnan(std_f) or std_f <= 0.0:
                return None

            z = (px - mean_f) / max(std_f, 1e-12)
            if abs(z) <= alpha2025_vol_revert_exit_z:
                return self._emit_non_entry(row.symbol, "FLAT", f"alpha2025 vol exit z={z:.2f}")
            if z <= -alpha2025_vol_revert_entry_z:
                return self._emit_entry(
                    row.symbol,
                    "LONG",
                    px - alpha2025_vol_revert_stop_mult * a,
                    f"alpha2025 vol long z={z:.2f}",
                    regime_streak,
                    regime_confirm_bars,
                    entry_confirm_bars,
                )
            if allow_short and z >= alpha2025_vol_revert_entry_z:
                return self._emit_entry(
                    row.symbol,
                    "SHORT",
                    px + alpha2025_vol_revert_stop_mult * a,
                    f"alpha2025 vol short z={z:.2f}",
                    regime_streak,
                    regime_confirm_bars,
                    entry_confirm_bars,
                )
            return self._emit_non_entry(row.symbol, "HOLD", f"alpha2025 vol hold z={z:.2f}")

        if regime == "STRONG_TREND":
            spread_atr = (row.ema_fast - row.ema_slow) / max(a, 1e-12)
            if (
                (row.ema_fast > row.ema_slow)
                and (px > row.ema_fast + trend_entry_buf * a)
                and (spread_atr >= trend_min_spread)
                and trend_quality_ok(is_long=True)
            ):
                return self._emit_entry(
                    row.symbol,
                    "LONG",
                    px - cfg.stop_atr_mult_trend * a,
                    "trend long",
                    regime_streak,
                    regime_confirm_bars,
                    entry_confirm_bars,
                )
            if (
                enable_pullback
                and (row.ema_fast > row.ema_slow)
                and (spread_atr >= trend_min_spread)
                and trend_quality_ok(is_long=True)
            ):
                pull_gap = (row.ema_fast - px) / max(a, 1e-12)
                if (px >= row.ema_slow) and (pull_gap >= 0.0) and (pull_gap <= pullback_max_gap_atr):
                    return self._emit_entry(
                        row.symbol,
                        "LONG",
                        px - pullback_stop_mult * a,
                        "trend pullback long",
                        regime_streak,
                        regime_confirm_bars,
                        entry_confirm_bars,
                    )
            return self._emit_non_entry(row.symbol, "FLAT", "trend flat")

        if regime == "STRONG_TREND_BEAR":
            if not allow_short:
                return self._emit_non_entry(row.symbol, "FLAT", "bear trend flat (short disabled)")
            spread_atr = (row.ema_slow - row.ema_fast) / max(a, 1e-12)
            short_adx_ok = short_trend_min_adx <= float(row.adx14) <= short_trend_max_adx
            if (
                (row.ema_fast < row.ema_slow)
                and short_adx_ok
                and (px < row.ema_fast - short_trend_entry_buf * a)
                and (spread_atr >= short_trend_min_spread)
                and trend_quality_ok(is_long=False)
            ):
                return self._emit_entry(
                    row.symbol,
                    "SHORT",
                    px + short_trend_stop_mult * a,
                    "bear trend short",
                    regime_streak,
                    regime_confirm_bars,
                    entry_confirm_bars,
                )
            if (
                enable_pullback
                and (row.ema_fast < row.ema_slow)
                and short_adx_ok
                and (spread_atr >= short_trend_min_spread)
                and trend_quality_ok(is_long=False)
            ):
                pull_gap = (px - row.ema_fast) / max(a, 1e-12)
                if (px <= row.ema_slow) and (pull_gap >= 0.0) and (pull_gap <= pullback_max_gap_atr):
                    return self._emit_entry(
                        row.symbol,
                        "SHORT",
                        px + pullback_stop_mult * a,
                        "trend pullback short",
                        regime_streak,
                        regime_confirm_bars,
                        entry_confirm_bars,
                    )
            return self._emit_non_entry(row.symbol, "FLAT", "bear trend flat")

        if regime == "VOL_EXPAND":
            hh = row.donchian_hh
            ll = row.donchian_ll
            if hh is None or ll is None:
                return self._emit_non_entry(row.symbol, "HOLD", "donchian not ready")

            hh_f = float(hh)
            ll_f = float(ll)
            adx = float(row.adx14) if row.adx14 is not None else float("nan")
            if not np.isnan(adx) and adx > vol_max_adx:
                return self._emit_non_entry(row.symbol, "HOLD", "vol hold (adx max filter)")

            bull_spread_atr = (row.ema_fast - row.ema_slow) / max(a, 1e-12)
            bear_spread_atr = (row.ema_slow - row.ema_fast) / max(a, 1e-12)
            spread_abs_atr = abs(row.ema_fast - row.ema_slow) / max(a, 1e-12)
            if np.isnan(adx):
                long_adx_ok = vol_long_min_adx <= 0.0
                short_adx_ok = vol_short_min_adx <= 0.0
            else:
                long_adx_ok = (adx >= vol_long_min_adx) and (adx <= vol_long_max_adx)
                short_adx_ok = (adx >= vol_short_min_adx) and (adx <= vol_short_max_adx)

            long_spread_ok = (vol_long_min_spread <= 0.0) or (bull_spread_atr >= vol_long_min_spread)
            short_spread_ok = (vol_short_min_spread <= 0.0) or (bear_spread_atr >= vol_short_min_spread)
            long_slope_ok = (vol_long_min_slope_atr <= 0.0) or (
                (not np.isnan(ema_slope_3)) and (ema_slope_3 >= vol_long_min_slope_atr)
            )
            short_slope_ok = (vol_short_min_slope_atr <= 0.0) or (
                (not np.isnan(ema_slope_3)) and (-ema_slope_3 >= vol_short_min_slope_atr)
            )

            if vol_revert_priority_when_low_trend:
                priority_sig = emit_vol_revert_signal(adx, spread_abs_atr)
                if priority_sig is not None:
                    return priority_sig

            if vol_strict:
                if px >= hh_f and long_adx_ok and long_spread_ok and long_slope_ok:
                    return self._emit_entry(
                        row.symbol,
                        "LONG",
                        px - cfg.stop_atr_mult_vol * a,
                        "vol break long",
                        regime_streak,
                        regime_confirm_bars,
                        entry_confirm_bars,
                    )
                if px <= ll_f and short_adx_ok and short_spread_ok and short_slope_ok:
                    if not allow_short:
                        return self._emit_non_entry(row.symbol, "HOLD", "vol hold (short disabled)")
                    return self._emit_entry(
                        row.symbol,
                        "SHORT",
                        px + cfg.stop_atr_mult_vol * a,
                        "vol break short",
                        regime_streak,
                        regime_confirm_bars,
                        entry_confirm_bars,
                    )
            else:
                if px >= hh_f - vol_near_mult * a and long_adx_ok and long_spread_ok and long_slope_ok:
                    return self._emit_entry(
                        row.symbol,
                        "LONG",
                        px - cfg.stop_atr_mult_vol * a,
                        "vol break long",
                        regime_streak,
                        regime_confirm_bars,
                        entry_confirm_bars,
                    )
                if px <= ll_f + vol_near_mult * a and short_adx_ok and short_spread_ok and short_slope_ok:
                    if not allow_short:
                        return self._emit_non_entry(row.symbol, "HOLD", "vol hold (short disabled)")
                    return self._emit_entry(
                        row.symbol,
                        "SHORT",
                        px + cfg.stop_atr_mult_vol * a,
                        "vol break short",
                        regime_streak,
                        regime_confirm_bars,
                        entry_confirm_bars,
                    )

            # VOL_EXPAND 구간에서 기존 돌파 신호가 없을 때 작은 추세(micro trend) 포착
            # - 과한 추세(고 ADX)는 기존 STRONG_TREND가 담당
            # - 약한/초기 추세를 EMA 정렬 + buffer로 선별
            if enable_micro_trend and not np.isnan(adx):
                if (adx >= micro_min_adx) and (adx <= micro_max_adx):
                    if (
                        (row.ema_fast > row.ema_slow)
                        and (px > row.ema_fast + micro_entry_buf * a)
                        and (bull_spread_atr >= micro_min_spread)
                    ):
                        return self._emit_entry(
                            row.symbol,
                            "LONG",
                            px - micro_stop_mult * a,
                            "micro trend long",
                            regime_streak,
                            regime_confirm_bars,
                            entry_confirm_bars,
                        )

                    if allow_short and (
                        (row.ema_fast < row.ema_slow)
                        and (px < row.ema_fast - micro_entry_buf * a)
                        and (bear_spread_atr >= micro_min_spread)
                    ):
                        return self._emit_entry(
                            row.symbol,
                            "SHORT",
                            px + micro_stop_mult * a,
                            "micro trend short",
                            regime_streak,
                            regime_confirm_bars,
                            entry_confirm_bars,
                        )

            # Additional 2025 alpha: low-ADX VOL_EXPAND mean-reversion overlay.
            # This only runs when breakout/micro-trend signals were not emitted above.
            if enable_vol_revert_alpha and not vol_revert_priority_when_low_trend:
                vol_revert_sig = emit_vol_revert_signal(adx, spread_abs_atr)
                if vol_revert_sig is not None:
                    return vol_revert_sig

            return self._emit_non_entry(row.symbol, "HOLD", "vol hold")

        if regime == "CHOP" and enable_chop_alpha:
            adx = float(row.adx14) if row.adx14 is not None else float("nan")
            if np.isnan(adx) or adx > chop_max_adx:
                return self._emit_non_entry(row.symbol, "HOLD", "chop hold (adx filter)")

            spread_atr = abs(row.ema_fast - row.ema_slow) / max(a, 1e-12)
            if spread_atr > chop_max_spread:
                return self._emit_non_entry(row.symbol, "HOLD", "chop hold (spread filter)")

            mean = row.bb_mean if chop_use_bb else row.mr_mean
            std = row.bb_std if chop_use_bb else row.mr_std
            if mean is None or std is None:
                return self._emit_non_entry(row.symbol, "HOLD", "chop hold (mean/std not ready)")
            mean_f = float(mean)
            std_f = float(std)
            if np.isnan(mean_f) or np.isnan(std_f) or std_f <= 0.0:
                return self._emit_non_entry(row.symbol, "HOLD", "chop hold (invalid std)")

            long_allowed = True
            short_allowed = allow_short
            if chop_follow_ema_bias:
                if row.ema_fast >= row.ema_slow:
                    short_allowed = False
                else:
                    long_allowed = False

            z = (px - mean_f) / max(std_f, 1e-12)
            if abs(z) <= chop_exit_z:
                return self._emit_non_entry(row.symbol, "FLAT", f"chop exit z={z:.2f}")
            if long_allowed and z <= -chop_entry_z:
                return self._emit_entry(
                    row.symbol,
                    "LONG",
                    px - chop_stop_mult * a,
                    f"chop long z={z:.2f}",
                    regime_streak,
                    regime_confirm_bars,
                    entry_confirm_bars,
                )
            if short_allowed and z >= chop_entry_z:
                return self._emit_entry(
                    row.symbol,
                    "SHORT",
                    px + chop_stop_mult * a,
                    f"chop short z={z:.2f}",
                    regime_streak,
                    regime_confirm_bars,
                    entry_confirm_bars,
                )
            return self._emit_non_entry(row.symbol, "HOLD", f"chop hold z={z:.2f}")

        if funding_rate is not None and abs(float(funding_rate)) >= float(cfg.funding_extreme):
            fr = float(funding_rate)
            if fr > cfg.funding_extreme:
                if not allow_short:
                    return self._emit_non_entry(row.symbol, "HOLD", "funding hold (short disabled)")
                return self._emit_entry(
                    row.symbol,
                    "SHORT",
                    px + cfg.stop_atr_mult_funding * a,
                    f"funding+ {fr:.6f}",
                    regime_streak,
                    regime_confirm_bars,
                    entry_confirm_bars,
                )
            if fr < -cfg.funding_extreme:
                return self._emit_entry(
                    row.symbol,
                    "LONG",
                    px - cfg.stop_atr_mult_funding * a,
                    f"funding- {fr:.6f}",
                    regime_streak,
                    regime_confirm_bars,
                    entry_confirm_bars,
                )

        return self._emit_non_entry(row.symbol, "HOLD", "default hold")
