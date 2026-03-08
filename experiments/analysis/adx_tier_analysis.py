#!/usr/bin/env python3
"""
ADX Tier / Regime / Direction P&L Deep-Dive
=============================================
Dynamic v2 기준으로 각 trade에 entry 시점의 컨텍스트를 붙여
수익/손실 구조를 다차원으로 분석한다.

분석 축:
  1. ADX tier at entry (STRONG/MEDIUM/WEAK/VERY_WEAK)
  2. Regime at entry (STRONG_TREND / VOL_EXPAND)
  3. Direction (LONG / SHORT)
  4. Entry year
  5. Symbol
  6. 조합: tier × direction, tier × year, regime × direction, direction × year
  7. Exit type (STOP vs EXIT)
  8. 보유 기간 (bars)

실행:
  cd quant_4h_1
  python experiments/analysis/adx_tier_analysis.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# src를 path에 추가
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ["QUANT_BT_SAVE_ARTIFACTS"] = "0"
os.environ["QUANT_BT_PROGRESS_EVERY"] = "0"

import numpy as np
import pandas as pd

from quant.config.presets import preset_dynamic_params_v2
from quant.cli.backtest import _build_price_funding, _FundingCursor
from quant.core.engine import Engine
from quant.core.portfolio import Portfolio
from quant.core.risk_vol import VolScaledRiskManager
from quant.execution.paper_broker import PaperBroker
from quant.strategies.your_strategy import YourStrategy
from quant.strategies.wrappers import MarketRegimeGate, MarketRegimeGateConfig
from quant.core.dynamic_params import adx_tier


# ──────────────────────────────────────────────
# 분석용 백테스트 러너
# ──────────────────────────────────────────────

def run_annotated_backtest(cfg) -> tuple[pd.DataFrame, object]:
    """
    일반 run_backtest()와 동일하지만,
    각 closing trade에 entry 시점의 ADX tier / regime / direction 을 붙여 반환.
    """
    _, _, funding_map, idx, feature_dicts, sorted_funding = _build_price_funding(cfg)

    base = YourStrategy(cfg)
    strategy = MarketRegimeGate(
        base,
        MarketRegimeGateConfig(
            market_symbol=cfg.market_symbol,
            allow_regimes=cfg.allow_regimes,
            market_off_allow_symbol_regimes=getattr(cfg, "market_off_allow_symbol_regimes", ()),
            state_gate_symbol_regimes=getattr(cfg, "state_gate_symbol_regimes", ()),
            state_gate_allowed_market_regimes=getattr(cfg, "state_gate_allowed_market_regimes", ()),
            state_gate_min_drawdown=float(getattr(cfg, "state_gate_min_drawdown", -1.0)),
            state_gate_max_drawdown=float(getattr(cfg, "state_gate_max_drawdown", 0.0)),
            state_gate_min_market_adx=float(getattr(cfg, "state_gate_min_market_adx", 0.0)),
            state_gate_max_market_adx=float(getattr(cfg, "state_gate_max_market_adx", 100.0)),
            state_gate_min_market_ema_spread_atr=float(getattr(cfg, "state_gate_min_market_ema_spread_atr", 0.0)),
            state_gate_min_market_regime_streak=int(getattr(cfg, "state_gate_min_market_regime_streak", 1)),
            state_gate_max_market_regime_streak=int(getattr(cfg, "state_gate_max_market_regime_streak", 10_000)),
            enable_conditional_trend_long_guard=bool(
                getattr(cfg, "enable_conditional_trend_long_guard", False)
            ),
            trend_long_guard_allowed_market_regimes=getattr(
                cfg, "trend_long_guard_allowed_market_regimes", ("STRONG_TREND",)
            ),
            trend_long_guard_symbol_spread_atr_min=float(
                getattr(cfg, "trend_long_guard_symbol_spread_atr_min", 0.0)
            ),
            trend_long_guard_market_spread_atr_min=float(
                getattr(cfg, "trend_long_guard_market_spread_atr_min", 0.0)
            ),
            trend_long_guard_market_regime_streak_min=int(
                getattr(cfg, "trend_long_guard_market_regime_streak_min", 0)
            ),
            trend_long_guard_market_adx_max=float(
                getattr(cfg, "trend_long_guard_market_adx_max", 100.0)
            ),
            entry_block_only=False,
        ),
    )
    risk = VolScaledRiskManager(cfg)
    portfolio = Portfolio(symbols=list(cfg.symbols), initial_cash=cfg.initial_equity)
    broker = PaperBroker(cfg)
    engine = Engine(cfg, strategy, broker, risk, portfolio)

    funding_cursor = {
        sym: _FundingCursor(sorted_funding[sym][0], sorted_funding[sym][1])
        for sym in cfg.symbols
    }

    # symbol → entry 시점 컨텍스트
    entry_ctx: dict[str, dict] = {}
    annotated: list[dict] = []

    INTERVAL_BARS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    bar_secs = INTERVAL_BARS.get(cfg.interval, 14400)

    for t in idx:
        t_py = t.to_pydatetime()

        # 1) funding
        for sym in cfg.symbols:
            rate = funding_map[sym].get(t_py)
            if rate is not None:
                portfolio.update_close(sym, feature_dicts[sym][t].close)
                portfolio.apply_funding(t_py, sym, rate)

        # 2) market regime gate 업데이트
        if getattr(cfg, "enable_regime_gate", False):
            strategy.update_market(feature_dicts[cfg.market_symbol][t], equity=portfolio.equity)

        # 3) 각 symbol on_bar
        for sym in cfg.symbols:
            fr = funding_cursor[sym].advance_to(t_py)
            row = feature_dicts[sym][t]

            side_before = portfolio.positions[sym].side
            n_before = len(portfolio.trades)

            engine.on_bar(row, funding_rate=fr)

            side_after = portfolio.positions[sym].side
            n_after = len(portfolio.trades)

            adx_val = float(row.adx14) if row.adx14 is not None else float("nan")
            tier = adx_tier(adx_val) if not np.isnan(adx_val) else "UNKNOWN"

            # 새 포지션 진입
            if side_before == 0 and side_after != 0:
                entry_ctx[sym] = {
                    "adx": adx_val,
                    "adx_tier": tier,
                    "regime": str(row.regime),
                    "direction": "LONG" if side_after > 0 else "SHORT",
                    "entry_year": t_py.year,
                    "entry_time": t_py,
                }

            # 새 trade 기록이 생겼으면 closing trade를 어노테이션
            if n_after > n_before:
                ctx = entry_ctx.get(sym, {})
                for trade in portfolio.trades[n_before:n_after]:
                    ttype = trade["type"]
                    # closing trade만 (STOP_LONG/SHORT, EXIT) → pnl이 있는 것들
                    if ttype in ("ENTRY_LONG", "ENTRY_SHORT",
                                 "PYRAMID_LONG", "PYRAMID_SHORT", "FUNDING"):
                        continue
                    rec = dict(trade)
                    rec["adx_tier"]    = ctx.get("adx_tier", "UNKNOWN")
                    rec["entry_regime"]= ctx.get("regime", "UNKNOWN")
                    rec["direction"]   = ctx.get("direction", "UNKNOWN")
                    rec["entry_year"]  = ctx.get("entry_year", t_py.year)
                    rec["entry_adx"]   = ctx.get("adx", float("nan"))
                    rec["entry_time"]  = ctx.get("entry_time", None)
                    rec["exit_year"]   = t_py.year
                    # 보유 기간 bars
                    if rec["entry_time"] is not None:
                        hold_secs = (t_py - rec["entry_time"]).total_seconds()
                        rec["hold_bars"] = int(round(hold_secs / bar_secs))
                    else:
                        rec["hold_bars"] = 0
                    annotated.append(rec)

            # 포지션 종료 시 컨텍스트 제거
            if side_after == 0:
                entry_ctx.pop(sym, None)

        engine.snapshot_curve(t_py)

    return pd.DataFrame(annotated), engine


# ──────────────────────────────────────────────
# 출력 헬퍼
# ──────────────────────────────────────────────

SEP = "=" * 70

def _summary(g: pd.DataFrame) -> pd.Series:
    n = len(g)
    wins = (g["pnl"] > 0).sum()
    return pd.Series({
        "trades":   n,
        "win_rate": f"{wins/n*100:.1f}%" if n else "N/A",
        "total_pnl":f"${g['pnl'].sum():,.0f}",
        "avg_pnl":  f"${g['pnl'].mean():,.0f}" if n else "$0",
        "med_pnl":  f"${g['pnl'].median():,.0f}" if n else "$0",
        "best":     f"${g['pnl'].max():,.0f}" if n else "$0",
        "worst":    f"${g['pnl'].min():,.0f}" if n else "$0",
        "avg_hold": f"{g['hold_bars'].mean():.1f}b" if n else "0b",
    })


def section(title: str, grouped) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)
    df = grouped.apply(_summary).reset_index()
    print(df.to_string(index=False))


def analyze(df: pd.DataFrame) -> None:
    if df.empty:
        print("closing trades 없음")
        return

    df["pnl"] = df["pnl"].astype(float)

    # ADX tier 순서 정의
    tier_order = pd.CategoricalDtype(
        ["STRONG", "MEDIUM", "WEAK", "VERY_WEAK", "UNKNOWN"], ordered=True
    )
    df["adx_tier"] = df["adx_tier"].astype(tier_order)

    print(f"\n{'#'*70}")
    print(f"  DYNAMIC v2 P&L BREAKDOWN  (총 closing trades: {len(df)})")
    print(f"{'#'*70}")
    print(f"  전체 실현 PnL: ${df['pnl'].sum():,.0f}")
    print(f"  전체 승률    : {(df['pnl']>0).mean()*100:.1f}%")

    section("1. ADX TIER at ENTRY",
            df.groupby("adx_tier", observed=True))

    section("2. REGIME at ENTRY",
            df.groupby("entry_regime"))

    section("3. DIRECTION",
            df.groupby("direction"))

    section("4. ENTRY YEAR",
            df.groupby("entry_year"))

    section("5. SYMBOL",
            df.groupby("symbol"))

    section("6. EXIT TYPE  (STOP vs EXIT)",
            df.groupby("type"))

    section("7. ADX TIER × DIRECTION",
            df.groupby(["adx_tier", "direction"], observed=True))

    section("8. ADX TIER × ENTRY YEAR",
            df.groupby(["adx_tier", "entry_year"], observed=True))

    section("9. REGIME × DIRECTION",
            df.groupby(["entry_regime", "direction"]))

    section("10. DIRECTION × ENTRY YEAR",
            df.groupby(["direction", "entry_year"]))

    section("11. SYMBOL × DIRECTION × YEAR",
            df.groupby(["symbol", "direction", "entry_year"]))

    # 12. ADX 구간별 상세 (실제 ADX 값 히스토그램)
    print(f"\n{SEP}")
    print("  12. ENTRY ADX 분포 (10단위 구간별)")
    print(SEP)
    bins = list(range(0, 81, 10)) + [float("inf")]
    labels = [f"{b}~{bins[i+1]}" if bins[i+1] != float("inf") else f"{b}+" for i, b in enumerate(bins[:-1])]
    df["adx_bin"] = pd.cut(df["entry_adx"].clip(0, 80), bins=bins, labels=labels, right=False)
    section("", df.groupby("adx_bin", observed=False))

    # 13. 보유 기간별 PnL
    print(f"\n{SEP}")
    print("  13. 보유 기간 구간별")
    print(SEP)
    hold_bins = [0, 2, 5, 10, 20, 40, float("inf")]
    hold_labels = ["1b", "2~4b", "5~9b", "10~19b", "20~39b", "40b+"]
    df["hold_bin"] = pd.cut(df["hold_bars"], bins=hold_bins, labels=hold_labels, right=False)
    section("", df.groupby("hold_bin", observed=False))


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    cfg = preset_dynamic_params_v2()
    print("Dynamic v2 백테스트 실행 중...")
    df, engine = run_annotated_backtest(cfg)
    print(f"캡처된 closing trades: {len(df)}")
    analyze(df)
