from __future__ import annotations

from typing import List, Tuple

from quant.config.presets import PortfolioBTConfig
from quant.core.risk import RiskManager
from quant.core.events import SignalEvent, OrderEvent
from quant.core.portfolio import Portfolio
from quant.core.types import Side, OrderType, TimeInForce


class VolScaledRiskManager(RiskManager):
    def __init__(self, cfg: PortfolioBTConfig):
        super().__init__(cfg)
        self._peak_equity = float(cfg.initial_equity)
        self._guard_until_bar = -1

    def _dd_guard_state(self, portfolio: Portfolio) -> tuple[bool, float]:
        cfg = self.cfg
        if not bool(getattr(cfg, "enable_dd_guard", False)):
            return False, 0.0

        equity = max(float(portfolio.equity), 1e-12)
        self._peak_equity = max(self._peak_equity, equity)
        dd = equity / max(self._peak_equity, 1e-12) - 1.0

        threshold = float(getattr(cfg, "dd_guard_threshold", -0.16))
        cooldown = int(getattr(cfg, "dd_guard_cooldown_bars", 24))
        if dd <= threshold:
            self._guard_until_bar = max(self._guard_until_bar, int(portfolio.bar_count) + max(0, cooldown))

        active = int(portfolio.bar_count) <= int(self._guard_until_bar)
        return active, float(dd)

    def _regime_risk_scale(self, row) -> float:
        cfg = self.cfg
        if row is None:
            return 1.0
        regime = str(getattr(row, "regime", ""))
        if regime == "STRONG_TREND":
            return float(getattr(cfg, "risk_scale_strong_trend", 1.0))
        if regime == "STRONG_TREND_BEAR":
            return float(getattr(cfg, "risk_scale_bear_trend", getattr(cfg, "risk_scale_strong_trend", 1.0)))
        if regime == "VOL_EXPAND":
            return float(getattr(cfg, "risk_scale_vol_expand", 1.0))
        return float(getattr(cfg, "risk_scale_chop", 1.0))

    def _calc_qty(self, equity: float, stop_pct: float, close_px: float, risk_scale: float = 1.0) -> float:
        cfg = self.cfg
        stop_pct = max(stop_pct, cfg.min_stop_pct_floor)
        scale = cfg.target_stop_pct / stop_pct
        scale = max(cfg.vol_min_scale, min(scale, cfg.vol_max_scale))
        risk_usdt = equity * cfg.risk_per_trade * scale * risk_scale
        notional = risk_usdt / stop_pct
        notional = min(notional, equity * cfg.max_leverage)
        return notional / close_px

    def signal_to_orders(self, signal: SignalEvent, portfolio: Portfolio, close_px: float, row=None) -> List[Tuple[OrderEvent, bool]]:
        cfg = self.cfg
        s = signal.symbol
        p = portfolio.positions[s]
        orders: List[Tuple[OrderEvent, bool]] = []

        if signal is None:
            return orders

        dd_guard_active, dd_now = self._dd_guard_state(portfolio)
        if dd_guard_active:
            if p.side != 0:
                orders.append(
                    (
                        OrderEvent(
                            symbol=s,
                            side=Side.SELL if p.side > 0 else Side.BUY,
                            qty=p.qty,
                            order_type=OrderType.MARKET,
                            tif=TimeInForce.GTC,
                            reduce_only=True,
                            reason=f"DD_GUARD_CLOSE|dd={dd_now:.4f}",
                        ),
                        False,
                    )
                )
            # While guard is active, block all new entries.
            return orders

        if signal.action == "HOLD":
            return orders

        if signal.action == "FLAT":
            if p.side != 0:
                orders.append(
                    (
                        OrderEvent(
                            symbol=s,
                            side=Side.SELL if p.side > 0 else Side.BUY,
                            qty=p.qty,
                            order_type=OrderType.MARKET,
                            tif=TimeInForce.GTC,
                            reduce_only=True,
                            reason="CLOSE_BY_SIGNAL",
                        ),
                        False,
                    )
                )
            return orders

        if signal.action not in ("LONG", "SHORT") or signal.stop_price is None:
            return orders

        desired = 1 if signal.action == "LONG" else -1
        regime_scale = self._regime_risk_scale(row)
        signal_scale = self._signal_entry_scale(signal)

        if p.side == desired and getattr(cfg, "enable_pyramiding", False):
            if signal_scale < 0.999:
                return orders
            max_adds = int(getattr(cfg, "pyramid_max_adds", 2))
            min_profit_atr = float(getattr(cfg, "pyramid_min_profit_atr", 1.0))
            risk_scale = float(getattr(cfg, "pyramid_risk_scale", 0.5))
            min_adx = float(getattr(cfg, "pyramid_min_adx", 0.0))
            min_slope = float(getattr(cfg, "pyramid_min_ema_slope", 0.0))
            low_trend_adx_threshold = float(getattr(cfg, "pyramid_low_trend_adx_threshold", 0.0))
            low_trend_spread_threshold = float(getattr(cfg, "pyramid_low_trend_ema_spread_atr_threshold", 0.0))
            low_trend_max_adds = int(getattr(cfg, "pyramid_low_trend_max_adds", -1))

            effective_max_adds = max_adds
            if row is not None and low_trend_max_adds >= 0:
                adx_val = float(getattr(row, "adx14", 0.0))
                ema_f = float(getattr(row, "ema_fast", close_px))
                ema_s = float(getattr(row, "ema_slow", close_px))
                atr_v = float(getattr(row, "atr14", 1.0))
                if desired > 0:
                    ema_spread = (ema_f - ema_s) / max(atr_v, 1e-8)
                else:
                    ema_spread = (ema_s - ema_f) / max(atr_v, 1e-8)
                low_trend_hit = False
                if low_trend_adx_threshold > 0.0 and adx_val < low_trend_adx_threshold:
                    low_trend_hit = True
                if low_trend_spread_threshold > 0.0 and ema_spread < low_trend_spread_threshold:
                    low_trend_hit = True
                if low_trend_hit:
                    effective_max_adds = min(effective_max_adds, low_trend_max_adds)

            if p.add_count >= effective_max_adds:
                return orders

            if min_adx > 0 and row is not None:
                adx_val = float(getattr(row, "adx14", 0.0))
                if adx_val < min_adx:
                    return orders

            if min_slope > 0 and row is not None:
                ema_f = float(getattr(row, "ema_fast", close_px))
                ema_s = float(getattr(row, "ema_slow", close_px))
                atr_v = float(getattr(row, "atr14", 1.0))
                if desired > 0:
                    ema_spread = (ema_f - ema_s) / max(atr_v, 1e-8)
                else:
                    ema_spread = (ema_s - ema_f) / max(atr_v, 1e-8)
                if ema_spread < min_slope:
                    return orders

            cooldown = int(getattr(cfg, "pyramid_cooldown_bars", 0))
            if cooldown > 0:
                bars_since = portfolio.bar_count - p.last_add_bar
                if bars_since < cooldown:
                    return orders

            atr_val = abs(close_px - float(signal.stop_price)) / max(float(getattr(cfg, "stop_atr_mult_trend", 2.0)), 1e-6)
            profit_in_atr = portfolio.current_profit_atr(s, atr_val)
            if profit_in_atr < min_profit_atr:
                return orders

            equity = portfolio.equity
            stop_pct = abs(close_px - float(signal.stop_price)) / max(close_px, 1e-12)
            qty = self._calc_qty(
                equity,
                stop_pct,
                close_px,
                risk_scale=(risk_scale * regime_scale * signal_scale),
            )
            if qty <= 0:
                return orders

            est_risk = abs(close_px - float(signal.stop_price)) * qty
            if portfolio.open_risk_usdt() + est_risk > equity * cfg.portfolio_risk_cap:
                return orders

            orders.append(
                (
                    OrderEvent(
                        symbol=s,
                        side=Side.BUY if desired > 0 else Side.SELL,
                        qty=qty,
                        order_type=OrderType.MARKET,
                        tif=TimeInForce.GTC,
                        reduce_only=False,
                        stop_price=signal.stop_price,
                        reason=f"{signal.note}|pyramid#{p.add_count+1}",
                    ),
                    True,
                )
            )
            return orders

        if p.side != 0 and p.side != desired:
            orders.append(
                (
                    OrderEvent(
                        symbol=s,
                        side=Side.SELL if p.side > 0 else Side.BUY,
                        qty=p.qty,
                        order_type=OrderType.MARKET,
                        tif=TimeInForce.GTC,
                        reduce_only=True,
                        reason="FLIP_CLOSE",
                    ),
                    False,
                )
            )

        if p.side == desired:
            return orders

        equity = portfolio.equity
        stop_pct = abs(close_px - float(signal.stop_price)) / max(close_px, 1e-12)
        qty = self._calc_qty(equity, stop_pct, close_px, risk_scale=(regime_scale * signal_scale))
        if qty <= 0:
            return orders

        est_risk = abs(close_px - float(signal.stop_price)) * qty
        if portfolio.open_risk_usdt() + est_risk > equity * cfg.portfolio_risk_cap:
            return orders

        orders.append(
            (
                OrderEvent(
                    symbol=s,
                    side=Side.BUY if desired > 0 else Side.SELL,
                    qty=qty,
                    order_type=OrderType.MARKET,
                    tif=TimeInForce.GTC,
                    reduce_only=False,
                    stop_price=signal.stop_price,
                    reason=f"{signal.note}|scale={cfg.target_stop_pct/max(stop_pct,cfg.min_stop_pct_floor):.2f}|regScale={regime_scale:.2f}|stopPct={stop_pct:.4f}",
                ),
                False,
            )
        )
        return orders
