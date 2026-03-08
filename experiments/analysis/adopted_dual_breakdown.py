#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QUANT_BT_SAVE_ARTIFACTS", "0")
os.environ.setdefault("QUANT_BT_PROGRESS_EVERY", "0")
os.environ.setdefault("QUANT_BT_USE_MEM_CACHE", "1")

from quant.cli.backtest import _FundingCursor, _build_price_funding
from quant.config.presets import (
    preset_balanced_alpha_sleeve_aggressive,
    preset_dynamic_bear_state_trend,
)
from quant.core.dynamic_params import adx_tier
from quant.core.engine import Engine
from quant.core.portfolio import Portfolio
from quant.core.risk import RiskManager
from quant.core.risk_vol import VolScaledRiskManager
from quant.execution.paper_broker import PaperBroker
from quant.strategies.wrappers import MarketRegimeGate, MarketRegimeGateConfig
from quant.strategies.your_strategy import YourStrategy


OUTDIR = ROOT / "results" / "analysis" / "result_adopted_dual_breakdown_20260307"
INTERVAL_BARS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def classify_entry_family(note: str) -> str:
    n = str(note).lower()
    if "bear trend short" in n:
        return "BEAR_TREND_SHORT"
    if "trend pullback short" in n:
        return "TREND_PULLBACK_SHORT"
    if "trend pullback long" in n:
        return "TREND_PULLBACK_LONG"
    if "trend long" in n:
        return "TREND_LONG"
    if "vol break long" in n:
        return "VOL_BREAK_LONG"
    if "vol break short" in n:
        return "VOL_BREAK_SHORT"
    if "micro trend long" in n:
        return "MICRO_TREND_LONG"
    if "micro trend short" in n:
        return "MICRO_TREND_SHORT"
    if "alpha2025 vol long" in n:
        return "VOL_REVERT_LONG"
    if "alpha2025 vol short" in n:
        return "VOL_REVERT_SHORT"
    if "chop long" in n:
        return "CHOP_LONG"
    if "chop short" in n:
        return "CHOP_SHORT"
    if "funding+" in n:
        return "FUNDING_SHORT"
    if "funding-" in n:
        return "FUNDING_LONG"
    return "OTHER"


def build_strategy(cfg):
    base = YourStrategy(cfg)
    if getattr(cfg, "enable_regime_gate", False):
        return MarketRegimeGate(
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
                state_gate_min_market_ema_spread_atr=float(
                    getattr(cfg, "state_gate_min_market_ema_spread_atr", 0.0)
                ),
                state_gate_min_market_regime_streak=int(getattr(cfg, "state_gate_min_market_regime_streak", 1)),
                state_gate_max_market_regime_streak=int(
                    getattr(cfg, "state_gate_max_market_regime_streak", 10_000)
                ),
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
    return base


def build_risk(cfg):
    return VolScaledRiskManager(cfg) if getattr(cfg, "enable_vol_risk", False) else RiskManager(cfg)


def run_annotated_backtest(cfg, sleeve_name: str) -> pd.DataFrame:
    _, _, funding_map, idx, feature_dicts, sorted_funding = _build_price_funding(cfg)

    strategy = build_strategy(cfg)
    risk = build_risk(cfg)
    portfolio = Portfolio(symbols=list(cfg.symbols), initial_cash=cfg.initial_equity)
    broker = PaperBroker(cfg)
    engine = Engine(cfg, strategy, broker, risk, portfolio)

    funding_cursor = {
        sym: _FundingCursor(sorted_funding[sym][0], sorted_funding[sym][1]) for sym in cfg.symbols
    }
    bar_secs = INTERVAL_BARS.get(cfg.interval, 14400)

    entry_ctx: dict[str, dict] = {}
    annotated: list[dict] = []

    for t in idx:
        t_py = t.to_pydatetime()

        for sym in cfg.symbols:
            rate = funding_map[sym].get(t_py)
            if rate is not None:
                portfolio.update_close(sym, feature_dicts[sym][t].close)
                portfolio.apply_funding(t_py, sym, rate)

        market_row = None
        if getattr(cfg, "enable_regime_gate", False):
            market_row = feature_dicts[cfg.market_symbol][t]
            strategy.update_market(market_row, equity=portfolio.equity)

        for sym in cfg.symbols:
            fr = funding_cursor[sym].advance_to(t_py)
            row = feature_dicts[sym][t]
            n_before = len(portfolio.trades)

            engine.on_bar(row, funding_rate=fr)

            if len(portfolio.trades) == n_before:
                continue

            row_adx = float(row.adx14) if row.adx14 is not None else float("nan")
            row_adx_tier = adx_tier(row_adx) if np.isfinite(row_adx) else "UNKNOWN"

            if market_row is not None:
                market_adx = float(getattr(strategy, "last_market_adx", np.nan))
                market_adx_tier = adx_tier(market_adx) if np.isfinite(market_adx) else "UNKNOWN"
                market_regime = str(getattr(strategy, "last_market_regime", "UNKNOWN"))
                market_streak = int(getattr(strategy, "last_market_regime_streak", 0))
                market_spread_atr = getattr(strategy, "last_market_ema_spread_atr", None)
                gate_dd = float(getattr(strategy, "current_drawdown", 0.0))
            else:
                market_adx = float("nan")
                market_adx_tier = "UNKNOWN"
                market_regime = "UNKNOWN"
                market_streak = 0
                market_spread_atr = None
                gate_dd = 0.0

            for trade in portfolio.trades[n_before:]:
                trade_type = str(trade["type"])

                if trade_type in ("ENTRY_LONG", "ENTRY_SHORT"):
                    entry_ctx[sym] = {
                        "sleeve": sleeve_name,
                        "entry_time": trade["time"],
                        "entry_year": t_py.year,
                        "symbol": sym,
                        "direction": "LONG" if trade_type == "ENTRY_LONG" else "SHORT",
                        "entry_reason": str(trade.get("note", "")),
                        "entry_family": classify_entry_family(str(trade.get("note", ""))),
                        "entry_regime": str(row.regime),
                        "entry_adx": row_adx,
                        "adx_tier": row_adx_tier,
                        "market_regime": market_regime,
                        "market_adx": market_adx,
                        "market_adx_tier": market_adx_tier,
                        "market_regime_streak": market_streak,
                        "market_ema_spread_atr": (
                            float(market_spread_atr) if market_spread_atr is not None else np.nan
                        ),
                        "gate_drawdown": gate_dd,
                        "pyramid_adds": 0,
                    }
                    continue

                if trade_type in ("PYRAMID_LONG", "PYRAMID_SHORT"):
                    if sym in entry_ctx:
                        entry_ctx[sym]["pyramid_adds"] = int(entry_ctx[sym].get("pyramid_adds", 0)) + 1
                    continue

                if trade_type == "FUNDING":
                    continue

                ctx = dict(entry_ctx.get(sym, {}))
                hold_bars = 0
                if ctx.get("entry_time") is not None:
                    hold_bars = int(round((t_py - ctx["entry_time"]).total_seconds() / bar_secs))

                annotated.append(
                    {
                        "sleeve": sleeve_name,
                        "symbol": sym,
                        "time": trade["time"],
                        "type": trade_type,
                        "pnl": float(trade["pnl"]),
                        "entry_time": ctx.get("entry_time"),
                        "entry_year": ctx.get("entry_year", t_py.year),
                        "exit_year": t_py.year,
                        "direction": ctx.get("direction", "UNKNOWN"),
                        "entry_reason": ctx.get("entry_reason", ""),
                        "entry_family": ctx.get("entry_family", "UNKNOWN"),
                        "entry_regime": ctx.get("entry_regime", "UNKNOWN"),
                        "entry_adx": ctx.get("entry_adx", np.nan),
                        "adx_tier": ctx.get("adx_tier", "UNKNOWN"),
                        "market_regime": ctx.get("market_regime", "UNKNOWN"),
                        "market_adx": ctx.get("market_adx", np.nan),
                        "market_adx_tier": ctx.get("market_adx_tier", "UNKNOWN"),
                        "market_regime_streak": ctx.get("market_regime_streak", 0),
                        "market_ema_spread_atr": ctx.get("market_ema_spread_atr", np.nan),
                        "gate_drawdown": ctx.get("gate_drawdown", 0.0),
                        "pyramid_adds": ctx.get("pyramid_adds", 0),
                        "hold_bars": hold_bars,
                    }
                )
                entry_ctx.pop(sym, None)

        engine.snapshot_curve(t_py)

    return pd.DataFrame(annotated)


def summarize(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    total_loss = float(-df.loc[df["pnl"] < 0, "pnl"].sum())
    total_profit = float(df.loc[df["pnl"] > 0, "pnl"].sum())

    for key, g in df.groupby(group_cols, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        record = {col: val for col, val in zip(group_cols, key)}
        wins = int((g["pnl"] > 0).sum())
        losses = int((g["pnl"] <= 0).sum())
        gross_profit = float(g.loc[g["pnl"] > 0, "pnl"].sum())
        gross_loss = float(-g.loc[g["pnl"] < 0, "pnl"].sum())
        record.update(
            {
                "trades": int(len(g)),
                "wins": wins,
                "losses": losses,
                "win_rate": float(wins / max(1, wins + losses)),
                "total_pnl": float(g["pnl"].sum()),
                "avg_pnl": float(g["pnl"].mean()),
                "median_pnl": float(g["pnl"].median()),
                "best_pnl": float(g["pnl"].max()),
                "worst_pnl": float(g["pnl"].min()),
                "avg_hold_bars": float(g["hold_bars"].mean()),
                "gross_profit": gross_profit,
                "gross_loss": -gross_loss,
                "profit_factor": float(gross_profit / gross_loss) if gross_loss > 1e-12 else np.inf,
                "loss_share": float(gross_loss / total_loss) if total_loss > 1e-12 else 0.0,
                "profit_share": float(gross_profit / total_profit) if total_profit > 1e-12 else 0.0,
            }
        )
        rows.append(record)

    return pd.DataFrame(rows).sort_values("total_pnl", ascending=False).reset_index(drop=True)


def add_hold_bin(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    bins = [0, 2, 5, 10, 20, 40, float("inf")]
    labels = ["1b", "2-4b", "5-9b", "10-19b", "20-39b", "40b+"]
    out["hold_bin"] = pd.cut(out["hold_bars"], bins=bins, labels=labels, right=False)
    return out


def print_top(title: str, df: pd.DataFrame, cols: list[str], n: int = 8, ascending: bool = False) -> None:
    print(f"\n{'=' * 90}")
    print(title)
    print("=" * 90)
    if df.empty:
        print("(empty)")
        return
    view = df.sort_values("total_pnl", ascending=ascending).head(n)
    with pd.option_context(
        "display.max_columns",
        200,
        "display.width",
        200,
        "display.float_format",
        lambda x: f"{x:,.4f}",
    ):
        print(view[cols].to_string(index=False))


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.initial_equity = 10_000.0 * 0.70

    alpha_cfg = preset_balanced_alpha_sleeve_aggressive()
    alpha_cfg.initial_equity = 10_000.0 * 0.30

    trend_df = run_annotated_backtest(trend_cfg, "trend")
    alpha_df = run_annotated_backtest(alpha_cfg, "alpha")
    trades = pd.concat([trend_df, alpha_df], ignore_index=True)
    trades = add_hold_bin(trades)

    if trades.empty:
        raise SystemExit("No annotated closing trades produced.")

    trades.to_csv(OUTDIR / "annotated_closing_trades.csv", index=False)

    summaries = {
        "summary_by_sleeve": summarize(trades, ["sleeve"]),
        "summary_by_sleeve_adx_tier": summarize(trades, ["sleeve", "adx_tier"]),
        "summary_by_sleeve_regime": summarize(trades, ["sleeve", "entry_regime"]),
        "summary_by_sleeve_direction": summarize(trades, ["sleeve", "direction"]),
        "summary_by_sleeve_entry_family": summarize(trades, ["sleeve", "entry_family"]),
        "summary_by_sleeve_market_regime": summarize(trades, ["sleeve", "market_regime"]),
        "summary_by_sleeve_market_adx_tier": summarize(trades, ["sleeve", "market_adx_tier"]),
        "summary_by_sleeve_year": summarize(trades, ["sleeve", "entry_year"]),
        "summary_by_hold_bin": summarize(trades, ["sleeve", "hold_bin"]),
        "summary_overall_adx_tier": summarize(trades, ["adx_tier"]),
        "summary_overall_regime": summarize(trades, ["entry_regime"]),
        "summary_overall_entry_family": summarize(trades, ["entry_family"]),
    }

    for name, df in summaries.items():
        df.to_csv(OUTDIR / f"{name}.csv", index=False)

    print(f"Annotated trades saved to: {OUTDIR / 'annotated_closing_trades.csv'}")
    print_top(
        "Sleeve Summary",
        summaries["summary_by_sleeve"],
        ["sleeve", "trades", "win_rate", "total_pnl", "avg_pnl", "profit_factor", "avg_hold_bars"],
    )
    print_top(
        "Best/Worst ADX Tiers By Sleeve",
        summaries["summary_by_sleeve_adx_tier"],
        ["sleeve", "adx_tier", "trades", "win_rate", "total_pnl", "avg_pnl", "loss_share", "avg_hold_bars"],
        n=10,
    )
    print_top(
        "Worst ADX Tiers By Sleeve",
        summaries["summary_by_sleeve_adx_tier"],
        ["sleeve", "adx_tier", "trades", "win_rate", "total_pnl", "avg_pnl", "loss_share", "avg_hold_bars"],
        n=10,
        ascending=True,
    )
    print_top(
        "Worst Entry Families",
        summaries["summary_by_sleeve_entry_family"],
        [
            "sleeve",
            "entry_family",
            "trades",
            "win_rate",
            "total_pnl",
            "avg_pnl",
            "worst_pnl",
            "loss_share",
            "avg_hold_bars",
        ],
        n=12,
        ascending=True,
    )
    print_top(
        "Worst Market Regime Buckets",
        summaries["summary_by_sleeve_market_regime"],
        ["sleeve", "market_regime", "trades", "win_rate", "total_pnl", "avg_pnl", "loss_share"],
        n=10,
        ascending=True,
    )
    print_top(
        "Worst Hold Buckets",
        summaries["summary_by_hold_bin"],
        ["sleeve", "hold_bin", "trades", "win_rate", "total_pnl", "avg_pnl", "loss_share"],
        n=10,
        ascending=True,
    )


if __name__ == "__main__":
    main()
