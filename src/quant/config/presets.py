# Project_4h/src/quant/config/presets.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class PortfolioBTConfig:
    symbols: Tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    interval: str = "4h"
    start: str = "2022-01-01"
    end: str = "2025-04-12"
    initial_equity: float = 10000.0

    # Risk
    risk_per_trade: float = 0.012
    portfolio_risk_cap: float = 0.03
    max_leverage: float = 5.0

    # Costs (paper/backtest fill model)
    fee_rate: float = 0.0005
    slippage: float = 0.0003

    # Signals / Features
    ema_fast: int = 20
    ema_slow: int = 45
    adx_trend: float = 30.0
    atr_expand_ratio: float = 1.2
    donchian_window: int = 30

    # Funding
    funding_extreme: float = 0.0005

    # Stops
    stop_atr_mult_trend: float = 2.0
    stop_atr_mult_vol: float = 1.5
    stop_atr_mult_funding: float = 1.2
    trail_atr_mult: float = 3.0
    enable_adaptive_trail: bool = False
    trail_adx_widen_threshold: float = 38.0
    trail_widen_mult: float = 1.2
    trail_adx_tighten_threshold: float = 22.0
    trail_tighten_mult: float = 0.9
    trail_vol_expand_mult: float = 1.0
    vol_breakout_strict: bool = False
    vol_break_near_atr_mult: float = 1.0

    # Trend entry quality filters (win-rate oriented)
    # - ema spread filter: (ema_fast - ema_slow) / atr14 >= threshold for long
    # - entry buffer: close must be beyond ema_fast by N * atr14
    enable_innov_trend_filter: bool = False
    trend_min_ema_slope_atr: float = 0.0
    trend_min_adx_slope_3: float = -999.0
    trend_min_ema_spread_atr: float = 0.0
    trend_entry_buffer_atr: float = 0.0
    enable_conditional_trend_long_guard: bool = False
    trend_long_guard_allowed_market_regimes: Tuple[str, ...] = ("STRONG_TREND",)
    trend_long_guard_symbol_spread_atr_min: float = 0.0
    trend_long_guard_market_spread_atr_min: float = 0.0
    trend_long_guard_market_regime_streak_min: int = 0
    trend_long_guard_market_adx_max: float = 100.0
    trend_long_guard_mode: str = "block"
    trend_long_guard_pullback_max_wait_bars: int = 0
    trend_long_guard_size_down_scale: float = 1.0
    enable_trend_pullback_entry: bool = False
    trend_pullback_max_gap_atr: float = 0.8
    trend_pullback_stop_atr_mult: float = 2.2
    trend_short_min_adx: float = 0.0
    trend_short_max_adx: float = 100.0
    trend_short_min_ema_spread_atr: float = 0.0
    trend_short_entry_buffer_atr: float = 0.0
    trend_short_stop_atr_mult: float = 0.0
    # VOL_EXPAND breakout quality filters
    vol_break_min_adx: float = 0.0
    vol_break_max_adx: float = 100.0
    vol_break_min_ema_spread_atr: float = 0.0
    vol_break_min_ema_slope_atr: float = 0.0
    vol_break_long_min_adx: float = 0.0
    vol_break_short_min_adx: float = 0.0
    vol_break_long_max_adx: float = 100.0
    vol_break_short_max_adx: float = 100.0
    vol_break_long_min_ema_spread_atr: float = 0.0
    vol_break_short_min_ema_spread_atr: float = 0.0
    vol_break_long_min_ema_slope_atr: float = 0.0
    vol_break_short_min_ema_slope_atr: float = 0.0
    vol_revert_priority_when_low_trend: bool = False

    # Micro-trend capture (비추세 연도/구간에서 작은 추세 포착)
    # VOL_EXPAND에서 기존 돌파 신호가 없을 때 EMA/ADX 기반의 약한 추세 진입을 허용
    enable_micro_trend: bool = False
    micro_trend_min_adx: float = 18.0
    micro_trend_max_adx: float = 30.0
    micro_trend_min_ema_spread_atr: float = 0.02
    micro_trend_entry_buffer_atr: float = 0.02
    micro_trend_stop_atr_mult: float = 1.6

    # CHOP alpha (mean-reversion for sideways periods)
    enable_chop_alpha: bool = False
    # Generic alias for CHOP mean-reversion overlay (date-agnostic).
    enable_sideways_reversion_alpha: bool = False
    # Legacy alias (kept for backward compatibility).
    enable_2025_alpha: bool = False
    # If True, CHOP alpha side follows EMA bias:
    # - ema_fast >= ema_slow: only long-side CHOP entries
    # - ema_fast <  ema_slow: only short-side CHOP entries
    chop_follow_ema_bias: bool = False
    chop_use_bb: bool = True
    chop_entry_z: float = 1.2
    chop_exit_z: float = 0.3
    chop_stop_atr_mult: float = 1.4
    chop_max_adx: float = 22.0
    chop_max_ema_spread_atr: float = 0.08
    # Generic low-trend VOL_EXPAND mean-reversion overlay (date-agnostic).
    enable_low_adx_vol_revert_alpha: bool = False
    # Legacy alias (kept for backward compatibility).
    enable_2025_vol_revert_alpha: bool = False
    alpha2025_vol_revert_use_bb: bool = True
    alpha2025_vol_revert_entry_z: float = 1.1
    alpha2025_vol_revert_exit_z: float = 0.35
    alpha2025_vol_revert_stop_atr_mult: float = 1.4
    alpha2025_vol_revert_max_adx: float = 18.0
    alpha2025_vol_revert_max_ema_spread_atr: float = 0.08


    # Market regime gate (market_symbol 湲곗?)
    enable_regime_gate: bool = True
    market_symbol: str = "BTCUSDT"
    allow_regimes: Tuple[str, ...] = ("STRONG_TREND", "VOL_EXPAND")
    market_off_allow_symbol_regimes: Tuple[str, ...] = ()
    state_gate_symbol_regimes: Tuple[str, ...] = ()
    state_gate_allowed_market_regimes: Tuple[str, ...] = ()
    state_gate_min_drawdown: float = -1.0
    state_gate_max_drawdown: float = 0.0
    state_gate_min_market_adx: float = 0.0
    state_gate_max_market_adx: float = 100.0
    state_gate_min_market_ema_spread_atr: float = 0.0
    state_gate_min_market_regime_streak: int = 1
    state_gate_max_market_regime_streak: int = 10_000
    bear_short_gate_allowed_market_regimes: Tuple[str, ...] = ()
    bear_short_gate_min_market_adx: float = 0.0

    # Vol-scaled risk manager
    enable_vol_risk: bool = False
    target_stop_pct: float = 0.020
    vol_min_scale: float = 0.5
    vol_max_scale: float = 1.5
    min_stop_pct_floor: float = 0.003
    # Drawdown guard: if equity DD breaches threshold, force-close and pause new entries.
    enable_dd_guard: bool = False
    dd_guard_threshold: float = -0.16
    dd_guard_cooldown_bars: int = 24
    # Regime-aware sizing multipliers used by VolScaledRiskManager
    risk_scale_strong_trend: float = 1.0
    risk_scale_bear_trend: float = 1.0
    risk_scale_vol_expand: float = 1.0
    risk_scale_chop: float = 1.0

    # Mean-Reversion (CHOP ?꾩슜)
    mr_window: int = 50
    mr_bb_window: int = 14       # BB Z-score window (14 bars, optimal from analysis)
    mr_use_bb: bool = True       # True: use BB Z-score, False: rolling-mean Z-score
    mr_entry_z: float = 1.5
    mr_exit_z: float = 0.3
    mr_stop_atr_mult: float = 2.0
    mr_max_hold_bars: int = 12

    # Dual Portfolio (MR + Trend separation)
    enable_dual_portfolio: bool = False
    trend_equity_ratio: float = 0.7   # 70% for trend strategy
    mr_equity_ratio: float = 0.3      # 30% for MR strategy

    # Direction filter
    # enable_short=False ?대㈃ vol break short / trend short / funding short ?좏샇瑜?HOLD濡?泥섎━
    enable_short: bool = True

    # Bear regime switch (STEP7)
    # True  ??features.py媛 STRONG_TREND_BEAR ?덉쭚??遺꾨━ ?앹꽦
    #          strategy媛 ?대떦 ?덉쭚?먯꽌 SHORT ?쇰씪誘몃뵫 寃쎈줈 ?쒖슜
    # False ??湲곗〈怨??숈씪 (STRONG_TREND ?⑥씪 ?덉쭚, SHORT 寃쎈줈 ?놁쓬)
    # ??STEP7 ?ㅽ뿕 寃곕줎: STEP5($96,482, Sharpe 1.942) > STEP7($91,385, Sharpe 1.653)
    #   SHORT ?섏씡 +$12,730?댁?留?LONG ?쇰씪誘몃뵫 ?섏씡 -$27,412 ???쒗슚怨?-$14,682
    #   ?섎씫?μ뿉?쒕쭔 ?좊━, ?곸듅???먯떎 援ъ“????湲곕낯媛?False ?좎?
    enable_bear_regime: bool = False

    # Minimum holding bars before trailing stop activates
    # 吏꾩엯 ??N遊??숈븞 ?몃젅?쇰쭅 ?ㅽ넲 ?낅뜲?댄듃瑜?鍮꾪솢?깊솕
    # ??珥덇린 ?몄씠利?援ш컙(??遊??먯떎 -$27,923 = 珥?PnL??30.8%)??議곌린 泥?궛 諛⑹?
    # 0 = 鍮꾪솢??(湲곗〈 ?숈옉 ?좎?)
    min_hold_bars: int = 0
    min_signal_exit_hold_bars: int = 0  # block strategy-generated FLAT exits for the first N bars

    # Flip cooldown: 泥?궛 ??諛섎?諛⑺뼢 吏꾩엯 湲덉? 遊???
    # 泥?궛(EXIT/STOP) ??N遊??숈븞 諛섎?諛⑺뼢 ?좏샇瑜?HOLD濡?泥섎━
    # ??flip ?ъ쭊???먯떎 ?쒓굅 (??遊?flip 37嫄?紐⑤몢 ?먯떎, -$12,643 ?뚯닔 湲곕?)
    # 0 = 鍮꾪솢??(湲곗〈 ?숈옉 ?좎?)
    flip_cooldown_bars: int = 0

    # Overfitting guards
    regime_confirm_bars: int = 1
    entry_confirm_bars: int = 1

    # Dynamic Params v2: lock ADX-tier params (trail_atr_mult) at entry time per symbol.
    # Applied only when a new position opens; does not change trail during open positions.
    # See core/dynamic_params.py for tier table.
    enable_dynamic_params: bool = False

    # Pyramiding
    # - 議곌굔: 湲곗〈 ?ъ??섏씠 pyramid_min_profit_atr x ATR ?댁긽 ?섏씡 以묒씪 ?뚮쭔
    # - 由ъ뒪?? 湲곕낯 吏꾩엯??pyramid_risk_scale 諛곗닔濡?以꾩뿬??吏꾩엯
    # - ?잛닔: pyramid_max_adds ?뚭퉴吏
    # - 異붽? 議곌굔: ADX >= pyramid_min_adx (異붿꽭 媛뺣룄 ?꾪꽣)
    #              EMA slope > pyramid_min_ema_slope (紐⑤찘? 媛???꾪꽣)
    enable_pyramiding: bool = False
    pyramid_max_adds: int = 2
    pyramid_min_profit_atr: float = 1.0
    pyramid_risk_scale: float = 0.5
    pyramid_low_trend_adx_threshold: float = 0.0
    pyramid_low_trend_ema_spread_atr_threshold: float = 0.0
    pyramid_low_trend_max_adds: int = -1
    pyramid_min_adx: float = 0.0        # ?쇰씪誘몃뵫 理쒖냼 ADX (0=鍮꾪솢??
    pyramid_min_ema_slope: float = 0.0  # EMA slope 理쒖냼媛?(ATR?⑥쐞, 0=鍮꾪솢??
    pyramid_cooldown_bars: int = 0      # 留덉?留??쇰씪誘몃뵫 ??理쒖냼 ?湲?遊???(0=鍮꾪솢??

    # Binance keys (optional injection)
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_fapi_base_url: str = ""


def preset_regime_only_live() -> PortfolioBTConfig:
    """
    Main live preset. Proven optimal params from Phase 1 analysis (2026-03-05):
      trail_atr_mult=2.5 and stop_atr_mult_trend=1.8 vs baseline (trail=3.0, stop=2.0):
      5.56x → 6.81x (+22%), Sharpe 1.675 → 1.779, 2025: -2.1% → +0.3%
    """
    return PortfolioBTConfig(
        symbols=("BTCUSDT", "ETHUSDT"),
        interval="4h",
        start="2022-01-01",
        end="2025-04-12",
        initial_equity=10000.0,
        risk_per_trade=0.012,
        portfolio_risk_cap=0.03,
        max_leverage=5.0,
        fee_rate=0.0005,
        slippage=0.0003,
        enable_regime_gate=True,
        market_symbol="BTCUSDT",
        allow_regimes=("STRONG_TREND", "VOL_EXPAND"),
        enable_vol_risk=True,
        target_stop_pct=0.020,
        trend_min_ema_spread_atr=0.05,
        trend_entry_buffer_atr=0.0,
        enable_pyramiding=True,
        pyramid_max_adds=2,
        pyramid_min_profit_atr=1.2,
        pyramid_risk_scale=0.5,
        flip_cooldown_bars=3,
        trail_atr_mult=2.5,
        stop_atr_mult_trend=1.8,
        entry_confirm_bars=1,
    )


def preset_dynamic_params_v2() -> PortfolioBTConfig:
    """
    Dynamic Params v2: optimized 4h BTC/ETH preset targeting ~8.0x return with MDD inside -20%.
    ADX-tier trail_atr_mult is locked at entry time per symbol and does NOT change while a
    position is open (v1 flaw fixed).

    ADX tier → trail_atr_mult at entry:
      STRONG  (ADX>38): 2.5  (same as static — strong trends already good)
      MEDIUM  (ADX>30): 2.5
      WEAK    (ADX>20): 2.0  (cut winners faster in weak trends)
      VERY_WEAK(<20) : 1.5  (quick exit in choppy markets)
    """
    cfg = preset_regime_only_live()
    # STRONG tier trail_atr_mult is 2.7 in quant.core.dynamic_params._TIER_PARAMS.
    cfg.enable_dynamic_params = True
    cfg.risk_per_trade = 0.0115
    cfg.trend_min_ema_spread_atr = 0.10
    cfg.pyramid_max_adds = 3
    cfg.pyramid_min_profit_atr = 1.2
    cfg.pyramid_risk_scale = 0.42
    cfg.vol_break_min_ema_slope_atr = 0.01
    cfg.vol_break_long_min_adx = 20.0
    cfg.trend_short_min_ema_spread_atr = 0.30
    cfg.trend_short_entry_buffer_atr = 0.10
    cfg.trend_short_stop_atr_mult = 1.5
    cfg.risk_scale_bear_trend = 0.5
    cfg.flip_cooldown_bars = 3
    cfg.risk_scale_vol_expand = 0.8
    return cfg


def preset_dynamic_bear_state_trend() -> PortfolioBTConfig:
    """
    State-gated bear-overlay trend engine.
    Designed as the trend sleeve in the dual-engine allocation found on 2026-03-07.

    Standalone verify:
      total_return=12.5711, max_drawdown=-0.2102, y2024=+138.1%, y2025=+30.1%
    The 2022 return remains negative standalone, so this preset is intended to be paired
    with a positive-2022 sleeve rather than deployed alone.
    """
    cfg = preset_dynamic_params_v2()
    cfg.enable_bear_regime = True
    cfg.market_off_allow_symbol_regimes = ("STRONG_TREND_BEAR",)
    cfg.state_gate_symbol_regimes = ("STRONG_TREND_BEAR",)
    cfg.state_gate_allowed_market_regimes = ("STRONG_TREND_BEAR",)
    cfg.state_gate_min_market_adx = 30.0
    cfg.state_gate_max_market_adx = 35.0
    cfg.state_gate_min_market_ema_spread_atr = 0.30
    cfg.state_gate_min_market_regime_streak = 4
    cfg.state_gate_max_market_regime_streak = 7
    cfg.risk_scale_bear_trend = 1.5
    cfg.min_signal_exit_hold_bars = 2
    # 2026-03-07 stop-cluster iteration:
    # modestly tighten trend-long quality without adding entry confirmation.
    cfg.trend_min_ema_spread_atr = 0.105
    cfg.trend_entry_buffer_atr = 0.02
    # 2026-03-08 adopted guard:
    # avoid stale direct trend-long chases; if the guard hits, wait for a pullback and
    # re-enter with reduced size instead of fully discarding the opportunity.
    cfg.enable_conditional_trend_long_guard = True
    cfg.trend_long_guard_allowed_market_regimes = ("STRONG_TREND",)
    cfg.trend_long_guard_symbol_spread_atr_min = 1.0
    cfg.trend_long_guard_market_regime_streak_min = 10
    cfg.trend_long_guard_mode = "pullback_only"
    cfg.trend_long_guard_pullback_max_wait_bars = 8
    cfg.trend_long_guard_size_down_scale = 0.5
    return cfg


def preset_balanced_alpha_sleeve_aggressive() -> PortfolioBTConfig:
    """
    Positive-2022 alpha sleeve used with the state-gated bear trend engine.

    Standalone verify:
      total_return=5.7189, max_drawdown=-0.2762, y2022=+54.1%, y2025=+47.7%
    """
    cfg = preset_relaxed_2025_alpha_balanced()
    cfg.risk_per_trade = 0.023
    cfg.portfolio_risk_cap = 0.092
    # 2026-03-07 churn review:
    # tighten generic trend-long entries in the aggressive alpha sleeve only.
    cfg.trend_min_ema_spread_atr = 0.06
    cfg.trend_entry_buffer_atr = 0.06
    # Allow alpha bear-trend shorts in trend/chop markets, but skip VOL_EXPAND entries.
    cfg.bear_short_gate_allowed_market_regimes = ("STRONG_TREND_BEAR", "STRONG_TREND", "CHOP")
    return cfg


def preset_relaxed_2025_alpha_balanced() -> PortfolioBTConfig:
    """
    Relaxed-target balanced preset (2026-03-05 local search)
    - Objective: keep drawdown in a tighter band while lifting 2025 return.
    - Constraint profile: MDD > -0.20 and y2025 >= 0.20.
    """
    return PortfolioBTConfig(
        symbols=("BTCUSDT", "ETHUSDT"),
        interval="4h",
        start="2022-01-01",
        end="2025-04-12",
        initial_equity=10000.0,
        risk_per_trade=0.011,
        portfolio_risk_cap=0.05,
        max_leverage=5.0,
        fee_rate=0.0005,
        slippage=0.0003,
        funding_extreme=0.001,
        enable_short=True,
        enable_regime_gate=True,
        market_symbol="BTCUSDT",
        allow_regimes=("STRONG_TREND", "VOL_EXPAND", "STRONG_TREND_BEAR", "CHOP"),
        enable_bear_regime=True,
        enable_vol_risk=True,
        target_stop_pct=0.018,
        vol_min_scale=0.5,
        vol_max_scale=2.5,
        min_stop_pct_floor=0.005,
        stop_atr_mult_trend=1.4,
        stop_atr_mult_vol=1.6,
        stop_atr_mult_funding=1.0,
        trail_atr_mult=1.8,
        enable_adaptive_trail=False,
        trail_widen_mult=1.4,
        trail_vol_expand_mult=0.8,
        enable_innov_trend_filter=True,
        trend_min_ema_slope_atr=0.02,
        trend_min_adx_slope_3=0.03,
        trend_min_ema_spread_atr=0.0,
        trend_entry_buffer_atr=0.01,
        enable_trend_pullback_entry=False,
        trend_pullback_max_gap_atr=0.8,
        trend_pullback_stop_atr_mult=1.8,
        vol_breakout_strict=False,
        vol_break_near_atr_mult=1.0,
        vol_break_min_adx=14.0,
        vol_break_max_adx=40.0,
        vol_break_min_ema_spread_atr=0.03,
        vol_break_min_ema_slope_atr=0.03,
        enable_micro_trend=True,
        micro_trend_min_adx=20.0,
        micro_trend_max_adx=24.0,
        micro_trend_min_ema_spread_atr=0.03,
        micro_trend_entry_buffer_atr=0.0,
        micro_trend_stop_atr_mult=1.8,
        enable_chop_alpha=True,
        enable_2025_alpha=True,
        chop_use_bb=False,
        chop_entry_z=0.9,
        chop_exit_z=0.4,
        chop_stop_atr_mult=1.6,
        chop_max_adx=22.0,
        chop_max_ema_spread_atr=0.18,
        enable_2025_vol_revert_alpha=True,
        enable_dd_guard=False,
        dd_guard_threshold=-0.20,
        dd_guard_cooldown_bars=24,
        risk_scale_strong_trend=0.7,
        risk_scale_vol_expand=1.8,
        risk_scale_chop=1.1,
        enable_pyramiding=False,
        min_hold_bars=3,
        flip_cooldown_bars=4,
        regime_confirm_bars=3,
        entry_confirm_bars=2,
    )


def preset_relaxed_2025_alpha_aggressive() -> PortfolioBTConfig:
    """
    Relaxed-target aggressive preset (2026-03-05 local search)
    - Objective: maximize return and y2025 under relaxed rule (MDD > -0.20 OR y2025 >= 0.20).
    - Expected to tolerate deeper drawdowns than balanced preset.
    """
    return PortfolioBTConfig(
        symbols=("BTCUSDT", "ETHUSDT"),
        interval="4h",
        start="2022-01-01",
        end="2025-04-12",
        initial_equity=10000.0,
        risk_per_trade=0.015,
        portfolio_risk_cap=0.04,
        max_leverage=5.0,
        fee_rate=0.0005,
        slippage=0.0003,
        funding_extreme=1.0,
        enable_short=True,
        enable_regime_gate=True,
        market_symbol="BTCUSDT",
        allow_regimes=("STRONG_TREND", "VOL_EXPAND", "STRONG_TREND_BEAR", "CHOP"),
        enable_bear_regime=True,
        enable_vol_risk=True,
        target_stop_pct=0.018,
        vol_min_scale=0.5,
        vol_max_scale=2.5,
        min_stop_pct_floor=0.005,
        stop_atr_mult_trend=1.4,
        stop_atr_mult_vol=1.8,
        stop_atr_mult_funding=1.0,
        trail_atr_mult=2.2,
        enable_adaptive_trail=False,
        trail_widen_mult=1.4,
        trail_vol_expand_mult=0.8,
        enable_innov_trend_filter=True,
        trend_min_ema_slope_atr=0.01,
        trend_min_adx_slope_3=-999.0,
        trend_min_ema_spread_atr=0.0,
        trend_entry_buffer_atr=0.02,
        enable_trend_pullback_entry=True,
        trend_pullback_max_gap_atr=0.6,
        trend_pullback_stop_atr_mult=2.2,
        vol_breakout_strict=True,
        vol_break_near_atr_mult=1.0,
        vol_break_min_adx=10.0,
        vol_break_max_adx=28.0,
        vol_break_min_ema_spread_atr=0.01,
        vol_break_min_ema_slope_atr=0.03,
        enable_micro_trend=True,
        micro_trend_min_adx=20.0,
        micro_trend_max_adx=24.0,
        micro_trend_min_ema_spread_atr=0.02,
        micro_trend_entry_buffer_atr=0.0,
        micro_trend_stop_atr_mult=2.0,
        enable_chop_alpha=True,
        enable_2025_alpha=True,
        chop_use_bb=False,
        chop_entry_z=0.9,
        chop_exit_z=0.3,
        chop_stop_atr_mult=1.4,
        chop_max_adx=22.0,
        chop_max_ema_spread_atr=0.15,
        enable_2025_vol_revert_alpha=False,
        enable_dd_guard=False,
        dd_guard_threshold=-0.18,
        dd_guard_cooldown_bars=36,
        risk_scale_strong_trend=1.0,
        risk_scale_vol_expand=1.2,
        risk_scale_chop=1.0,
        enable_pyramiding=True,
        pyramid_max_adds=4,
        pyramid_min_profit_atr=1.5,
        pyramid_risk_scale=0.8,
        pyramid_min_adx=0.0,
        pyramid_min_ema_slope=0.0,
        pyramid_cooldown_bars=2,
        min_hold_bars=3,
        flip_cooldown_bars=3,
        regime_confirm_bars=1,
        entry_confirm_bars=1,
    )


def preset_context_adaptive_general() -> PortfolioBTConfig:
    """
    Context-adaptive unified preset (date-agnostic).
    - Uses only bar-context conditions (ADX / spread / regime) without any date input.
    - Target: keep high total return while improving low-trend-period handling.
    - Local verify (2026-03-05):
      total_return=11.9102, max_drawdown=-0.4016, y2024=1.4381, y2025=0.2115
    """
    return PortfolioBTConfig(
        symbols=("BTCUSDT", "ETHUSDT"),
        interval="4h",
        start="2022-01-01",
        end="2025-04-12",
        initial_equity=10000.0,
        risk_per_trade=0.010,
        portfolio_risk_cap=0.09,
        max_leverage=5.0,
        fee_rate=0.0005,
        slippage=0.0003,
        funding_extreme=0.0005,
        enable_short=True,
        enable_regime_gate=True,
        market_symbol="BTCUSDT",
        allow_regimes=("STRONG_TREND", "VOL_EXPAND", "STRONG_TREND_BEAR"),
        enable_bear_regime=True,
        enable_vol_risk=True,
        target_stop_pct=0.026,
        vol_min_scale=0.6,
        vol_max_scale=2.5,
        min_stop_pct_floor=0.004,
        stop_atr_mult_trend=1.6,
        stop_atr_mult_vol=1.6,
        stop_atr_mult_funding=1.0,
        trail_atr_mult=2.2,
        enable_adaptive_trail=True,
        trail_widen_mult=1.3,
        trail_vol_expand_mult=0.9,
        enable_innov_trend_filter=False,
        trend_min_ema_slope_atr=0.0,
        trend_min_adx_slope_3=0.05,
        trend_min_ema_spread_atr=0.02,
        trend_entry_buffer_atr=0.01,
        enable_trend_pullback_entry=False,
        trend_pullback_max_gap_atr=0.6,
        trend_pullback_stop_atr_mult=2.2,
        vol_breakout_strict=False,
        vol_break_near_atr_mult=0.5,
        vol_break_min_adx=14.0,
        vol_break_max_adx=32.0,
        vol_break_min_ema_spread_atr=0.015,
        vol_break_min_ema_slope_atr=0.01,
        enable_micro_trend=True,
        micro_trend_min_adx=16.0,
        micro_trend_max_adx=26.0,
        micro_trend_min_ema_spread_atr=0.01,
        micro_trend_entry_buffer_atr=0.0,
        micro_trend_stop_atr_mult=2.0,
        enable_chop_alpha=False,
        enable_sideways_reversion_alpha=False,
        enable_low_adx_vol_revert_alpha=True,
        alpha2025_vol_revert_use_bb=True,
        alpha2025_vol_revert_entry_z=1.2,
        alpha2025_vol_revert_exit_z=0.45,
        alpha2025_vol_revert_stop_atr_mult=1.6,
        alpha2025_vol_revert_max_adx=16.0,
        alpha2025_vol_revert_max_ema_spread_atr=0.10,
        enable_dd_guard=False,
        dd_guard_threshold=-0.18,
        dd_guard_cooldown_bars=12,
        risk_scale_strong_trend=1.4,
        risk_scale_vol_expand=1.0,
        risk_scale_chop=0.7,
        enable_pyramiding=True,
        pyramid_max_adds=2,
        pyramid_min_profit_atr=1.2,
        pyramid_risk_scale=0.8,
        pyramid_min_adx=0.0,
        pyramid_min_ema_slope=0.02,
        pyramid_cooldown_bars=3,
        min_hold_bars=3,
        flip_cooldown_bars=4,
        regime_confirm_bars=3,
        entry_confirm_bars=1,
    )


def preset_mdd_gt_neg02_max_return() -> PortfolioBTConfig:
    """
    Strict-MDD preset (MDD > -0.20) with max return among local search candidates.
    Local verify (2026-03-05):
      total_return=3.0491, max_drawdown=-0.1991, sharpe=1.4873
    """
    return PortfolioBTConfig(
        symbols=("BTCUSDT", "ETHUSDT"),
        interval="4h",
        start="2022-01-01",
        end="2025-04-12",
        initial_equity=10000.0,
        risk_per_trade=0.010,
        portfolio_risk_cap=0.020,
        max_leverage=5.0,
        fee_rate=0.0005,
        slippage=0.0003,
        funding_extreme=0.0005,
        enable_short=True,
        enable_regime_gate=True,
        market_symbol="BTCUSDT",
        allow_regimes=("STRONG_TREND", "VOL_EXPAND", "STRONG_TREND_BEAR"),
        enable_bear_regime=True,
        enable_vol_risk=True,
        target_stop_pct=0.018,
        vol_min_scale=0.4,
        vol_max_scale=2.0,
        min_stop_pct_floor=0.006,
        stop_atr_mult_trend=1.8,
        stop_atr_mult_vol=1.2,
        stop_atr_mult_funding=1.0,
        trail_atr_mult=2.6,
        enable_adaptive_trail=True,
        trail_widen_mult=1.4,
        trail_vol_expand_mult=1.0,
        enable_innov_trend_filter=True,
        trend_min_ema_slope_atr=0.0,
        trend_min_adx_slope_3=-999.0,
        trend_min_ema_spread_atr=0.0,
        trend_entry_buffer_atr=0.02,
        enable_trend_pullback_entry=False,
        trend_pullback_max_gap_atr=0.8,
        trend_pullback_stop_atr_mult=2.0,
        vol_breakout_strict=False,
        vol_break_near_atr_mult=0.5,
        vol_break_min_adx=16.0,
        vol_break_max_adx=24.0,
        vol_break_min_ema_spread_atr=0.02,
        vol_break_min_ema_slope_atr=0.02,
        enable_micro_trend=False,
        micro_trend_min_adx=20.0,
        micro_trend_max_adx=26.0,
        micro_trend_min_ema_spread_atr=0.02,
        micro_trend_entry_buffer_atr=0.02,
        micro_trend_stop_atr_mult=2.0,
        enable_chop_alpha=False,
        enable_sideways_reversion_alpha=False,
        enable_low_adx_vol_revert_alpha=False,
        enable_dd_guard=False,
        dd_guard_threshold=-0.20,
        dd_guard_cooldown_bars=24,
        risk_scale_strong_trend=1.4,
        risk_scale_vol_expand=0.7,
        risk_scale_chop=0.5,
        enable_pyramiding=True,
        pyramid_max_adds=2,
        pyramid_min_profit_atr=1.5,
        pyramid_risk_scale=0.8,
        pyramid_min_adx=10.0,
        pyramid_min_ema_slope=0.01,
        pyramid_cooldown_bars=3,
        min_hold_bars=2,
        flip_cooldown_bars=4,
        regime_confirm_bars=1,
        entry_confirm_bars=1,
    )


def preset_live_small_test() -> PortfolioBTConfig:
    return PortfolioBTConfig(
        symbols=("ETHUSDT",),
        interval="4h",
        start="2022-01-01",
        end="2025-04-12",
        initial_equity=100.0,
        risk_per_trade=0.02,
        portfolio_risk_cap=0.05,
        max_leverage=1.0,
        fee_rate=0.0005,
        slippage=0.0003,
        enable_regime_gate=True,
        market_symbol="BTCUSDT",
        allow_regimes=("STRONG_TREND", "VOL_EXPAND"),
        enable_vol_risk=True,
        target_stop_pct=0.02,
        mr_window=50,
        mr_entry_z=1.8,
        mr_exit_z=0.4,
        mr_max_hold_bars=10,
    )


def preset_mr_only() -> PortfolioBTConfig:
    """
    MR ?꾩슜 preset - Dual Portfolio?먯꽌 MR ?붿쭊???ъ슜.
    CHOP 援ш컙?먯꽌 BB(14) Z-score 湲곕컲 Mean Reversion???ㅽ뻾.
    mr_equity_ratio 鍮꾩쑉??珥덇린?먮낯???좊떦.
    """
    return PortfolioBTConfig(
        symbols=("BTCUSDT", "ETHUSDT"),
        interval="4h",
        start="2022-01-01",
        end="2025-04-12",
        initial_equity=10000.0,
        risk_per_trade=0.015,
        portfolio_risk_cap=0.04,
        max_leverage=3.0,
        fee_rate=0.0005,
        slippage=0.0003,
        enable_regime_gate=False,  # MR? 吏곸젒 ?덉쭚 寃뚯씠???놁쓬 (MRStrategy?먯꽌 ?먯껜 泥섎━)
        enable_vol_risk=True,
        target_stop_pct=0.020,
        vol_min_scale=0.5,
        vol_max_scale=1.5,
        min_stop_pct_floor=0.003,
        # MR ?ㅼ젙
        mr_bb_window=14,
        mr_use_bb=True,
        mr_entry_z=1.5,
        mr_exit_z=0.3,
        mr_stop_atr_mult=1.5,
        mr_max_hold_bars=12,
        # ?쇰씪誘몃뵫 OFF (?④린 MR ?꾨왂)
        enable_pyramiding=False,
    )


# ?????????????????????????????????????????????????????????????????????????????
# ?ㅽ뿕???꾨━??(STEP3 媛쒖꽑 ?ㅽ뿕)
# ?????????????????????????????????????????????????????????????????????????????

def preset_exp1_no_short() -> PortfolioBTConfig:
    """
    ?ㅽ뿕 1: SHORT ?꾩쟾 鍮꾪솢?깊솕
    - vol break short / trend short / funding short ?좏샇 紐⑤몢 HOLD 泥섎━
    - 遺꾩꽍 洹쇨굅: 2024~2025??SHORT??-$7,089 ?먯떎
    - SHORT ?꾩껜 PnL +$4,065 ?댁?留?理쒓렐 2???곸옄 吏?????쒓굅 ?④낵 寃利?
    - STEP2 湲곗?: $88,509 / Sharpe 1.903 / MDD -22.4%
    """
    cfg = preset_regime_only_live()
    cfg.enable_short = False
    return cfg


def preset_exp2_pyramid_atr15() -> PortfolioBTConfig:
    """
    ?ㅽ뿕 2: ?쇰씪誘몃뵫 吏꾩엯 ?꾧퀎媛??꾪솕 (2.0 ATR ??1.5 ATR)
    - ?꾩옱 ?쇰씪誘몃뵫 2??鍮꾩쑉: 30.2% (108/358嫄?
    - 1.5 ATR濡???텛硫????대Ⅸ ?쒖젏???쇰씪誘몃뵫 異붽? ??2??嫄댁닔 利앷? 紐⑺몴
    - ?쇰씪誘몃뵫 2???됯퇏 PnL: +$1,262 (vs 1?? -$9, 0?? -$261)
    - 二쇱쓽: ?덈Т ??쑝硫?議곌린 ?쇰씪誘몃뵫?쇰줈 ?먯떎 ?뺣? 媛??
    """
    cfg = preset_regime_only_live()
    cfg.pyramid_min_profit_atr = 1.5
    return cfg


def preset_exp3_vol_filter() -> PortfolioBTConfig:
    """
    ?ㅽ뿕 3: VOL_EXPAND 吏꾩엯 議곌굔 媛뺥솕 (?쇰씪誘몃뵫 0???먯떎 ?꾪꽣)
    - ?꾩옱 vol break long ?쇰씪誘몃뵫 0?? 25嫄? -$9,153
    - ?꾩옱 vol break short ?쇰씪誘몃뵫 0?? 48嫄? -$12,792 (SHORT ?ы븿)
    - 媛쒖꽑: VOL_EXPAND?먯꽌 ?덉튂??HH瑜??ㅼ젣 ?뚰뙆(close >= donchian_hh)?덉쓣 ?뚮쭔 吏꾩엯
    - 湲곗〈 ATR 洹쇱젒 議곌굔 ?쒓굅 ???뺤떎???뚰뙆留??덉슜
    - SHORT 鍮꾪솢?깊솕???④퍡 ?곸슜 (?ㅽ뿕 1 ?④낵 ?좎?)
    """
    cfg = preset_regime_only_live()
    cfg.enable_short = False
    cfg.vol_breakout_strict = True   # your_strategy.py?먯꽌 李몄“
    return cfg


def preset_exp4_min_hold(min_hold: int = 4) -> PortfolioBTConfig:
    """
    ?ㅽ뿕 4: 理쒖냼 蹂댁쑀遊????꾩엯 (min_hold_bars)
    - 臾몄젣: ??遊?議곌린泥?궛 115嫄? ?밸쪧 0%, 珥??먯떎 -$28,892 (珥?PnL??30.8%)
    - ?먯씤: ?몃젅?쇰쭅 ?ㅽ넲??吏꾩엯 吏곹썑遺???낅뜲?댄듃?섏뼱 ?묒? ??갑???吏곸엫?먮룄 泥?궛
    - ?닿껐: 吏꾩엯 ??N遊??숈븞 trail stop ?낅뜲?댄듃 鍮꾪솢?깊솕
            ??珥덇린 怨좎젙 stop留??좎??섎떎媛 N遊??댄썑 trail ?쒖옉
    - 湲곕낯媛?4遊? STEP3 遺꾩꽍?먯꽌 5遊??대궡 P0 ?먯떎??-$27,923 (111嫄?
    - STEP3 湲곗?: $92,721, Sharpe 1.920, MDD -21.11%
    """
    cfg = preset_regime_only_live()
    cfg.min_hold_bars = min_hold
    return cfg


def preset_exp5_flip_cooldown(cooldown: int = 3) -> PortfolioBTConfig:
    """
    ?ㅽ뿕 5: Flip ?ъ쭊??荑⑤떎??(flip_cooldown_bars)
    - 臾몄젣: 泥?궛 ??利됱떆 諛섎?諛⑺뼢 吏꾩엯(flip)??二쇱슂 ?먯떎??
      쨌 flip 吏꾩엯 115嫄?以???遊?泥?궛: 37嫄? PnL -$12,643, ?밸쪧 0%
      쨌 ??遊?flip ?먯떎? 100% ?먯떎 (?섏씡 0嫄?
    - ?닿껐: EXIT/STOP 泥?궛 ??N遊??숈븞 諛섎?諛⑺뼢 ?좏샇 HOLD 泥섎━
    - 荑⑤떎???덉긽 ?④낵 (?ㅽ봽?쇱씤 遺꾩꽍):
      N=1: 李⑤떒 7嫄????쒗슚怨?+$2,442
      N=2: 李⑤떒 17嫄????쒗슚怨?+$5,824
      N=3: 李⑤떒 23嫄????쒗슚怨?+$7,643
      N=4: 李⑤떒 32嫄????쒗슚怨?+$10,889
      N=5: 李⑤떒 37嫄????쒗슚怨?+$12,643
    - STEP3 湲곗?: $92,721, Sharpe 1.920, MDD -21.11%
    """
    cfg = preset_regime_only_live()
    cfg.flip_cooldown_bars = cooldown
    return cfg
