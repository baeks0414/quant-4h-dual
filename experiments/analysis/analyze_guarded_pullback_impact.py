#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
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

from quant.cli.backtest import _FundingCursor, _build_price_funding, run_backtest
from quant.config.presets import (
    preset_balanced_alpha_sleeve_aggressive,
    preset_dynamic_bear_state_trend,
)
from quant.core.dynamic_params import adx_tier
from quant.core.engine import Engine
from quant.core.metrics import compute_metrics
from quant.core.portfolio import Portfolio
from quant.core.risk import RiskManager
from quant.core.risk_vol import VolScaledRiskManager
from quant.execution.paper_broker import PaperBroker
from quant.strategies.wrappers import MarketRegimeGate, MarketRegimeGateConfig
from quant.strategies.your_strategy import YourStrategy


OUTDIR = ROOT / "results" / "analysis" / "result_guarded_pullback_impact_20260308"
INITIAL_EQUITY = 10_000.0
TREND_WEIGHT = 0.70
ALPHA_WEIGHT = 0.30
INTERVAL_BARS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


@contextlib.contextmanager
def silence_stdout():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield


def classify_entry_family(note: str) -> str:
    n = str(note).lower()
    if "guarded trend pullback long" in n:
        return "GUARDED_PULLBACK_LONG"
    if "guarded trend long" in n:
        return "GUARDED_DIRECT_LONG"
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
                bear_short_gate_allowed_market_regimes=getattr(cfg, "bear_short_gate_allowed_market_regimes", ()),
                bear_short_gate_min_market_adx=float(getattr(cfg, "bear_short_gate_min_market_adx", 0.0)),
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


def apply_variant(cfg, variant: str) -> None:
    if variant == "prior_block":
        cfg.trend_long_guard_mode = "block"
        cfg.trend_long_guard_pullback_max_wait_bars = 0
        cfg.trend_long_guard_size_down_scale = 1.0
        return
    if variant == "current_guarded_pullback":
        cfg.trend_long_guard_mode = "pullback_only"
        cfg.trend_long_guard_pullback_max_wait_bars = 8
        cfg.trend_long_guard_size_down_scale = 0.5
        return
    raise ValueError(f"Unknown variant: {variant}")


def yearly_returns(ec: pd.DataFrame) -> dict[int, float]:
    view = ec.copy()
    view.index = pd.to_datetime(view.index, utc=True)
    out: dict[int, float] = {}
    for year in sorted(set(view.index.year)):
        sample = view[view.index.year == year]
        if not sample.empty:
            out[year] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def run_annotated_trend(cfg, variant: str) -> pd.DataFrame:
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
            symbol_spread_atr = (
                abs(float(row.ema_fast) - float(row.ema_slow)) / max(float(row.atr14), 1e-12)
                if row.atr14 is not None and float(row.atr14) > 0.0
                else np.nan
            )

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
                        "variant": variant,
                        "entry_time": trade["time"],
                        "entry_year": t_py.year,
                        "symbol": sym,
                        "direction": "LONG" if trade_type == "ENTRY_LONG" else "SHORT",
                        "entry_reason": str(trade.get("note", "")),
                        "entry_family": classify_entry_family(str(trade.get("note", ""))),
                        "entry_regime": str(row.regime),
                        "entry_adx": row_adx,
                        "symbol_spread_atr": symbol_spread_atr,
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
                        "variant": variant,
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
                        "symbol_spread_atr": ctx.get("symbol_spread_atr", np.nan),
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
                "avg_entry_adx": float(g["entry_adx"].mean()),
                "avg_symbol_spread_atr": float(g["symbol_spread_atr"].mean()),
                "avg_market_adx": float(g["market_adx"].mean()),
                "avg_market_spread_atr": float(g["market_ema_spread_atr"].mean()),
                "avg_market_regime_streak": float(g["market_regime_streak"].mean()),
                "gross_profit": gross_profit,
                "gross_loss": -gross_loss,
                "profit_factor": float(gross_profit / gross_loss) if gross_loss > 1e-12 else np.inf,
            }
        )
        rows.append(record)
    return pd.DataFrame(rows).sort_values("total_pnl", ascending=False).reset_index(drop=True)


def run_variant(variant: str) -> dict[str, object]:
    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.initial_equity = INITIAL_EQUITY * TREND_WEIGHT
    apply_variant(trend_cfg, variant)

    alpha_cfg = preset_balanced_alpha_sleeve_aggressive()
    alpha_cfg.initial_equity = INITIAL_EQUITY * ALPHA_WEIGHT

    with silence_stdout():
        trend = run_backtest(trend_cfg, outdir=str(OUTDIR / f"tmp_trend_{variant}"))
    with silence_stdout():
        alpha = run_backtest(alpha_cfg, outdir=str(OUTDIR / f"tmp_alpha_{variant}"))

    trend_ec = trend["equity_curve"][["equity"]].copy()
    alpha_ec = alpha["equity_curve"][["equity"]].copy()
    trend_ec.index = pd.to_datetime(trend_ec.index, utc=True)
    alpha_ec.index = pd.to_datetime(alpha_ec.index, utc=True)
    idx = trend_ec.index.intersection(alpha_ec.index)

    combined = pd.DataFrame(index=idx)
    combined["equity"] = trend_ec.loc[idx, "equity"] + alpha_ec.loc[idx, "equity"]
    peak = combined["equity"].cummax()
    combined["drawdown"] = combined["equity"] / peak - 1.0

    trades = pd.concat([trend["trades"], alpha["trades"]], ignore_index=True)
    if not trades.empty and "time" in trades.columns:
        trades = trades.sort_values("time").reset_index(drop=True)

    benchmark_curve = trend["benchmark_equity_curve"][["equity"]].copy()
    benchmark_curve.index = pd.to_datetime(benchmark_curve.index, utc=True)
    benchmark_curve["equity"] = benchmark_curve["equity"] / trend_cfg.initial_equity * INITIAL_EQUITY
    benchmark_curve = benchmark_curve.loc[idx]
    peak_b = benchmark_curve["equity"].cummax()
    benchmark_curve["drawdown"] = benchmark_curve["equity"] / peak_b - 1.0

    combo_metrics = compute_metrics(combined, trades, INITIAL_EQUITY, "4h", benchmark_curve=benchmark_curve)
    combo_yearly = yearly_returns(combined)
    trend_annotated = run_annotated_trend(trend_cfg, variant)
    trend_yearly_pnl = (
        trend_annotated.groupby(["entry_year"], dropna=False)["pnl"].sum().rename("trend_total_pnl").reset_index()
        if not trend_annotated.empty
        else pd.DataFrame(columns=["entry_year", "trend_total_pnl"])
    )

    return {
        "variant": variant,
        "combo_metrics": combo_metrics,
        "combo_yearly": combo_yearly,
        "trend_trades": trend_annotated,
        "trend_yearly_pnl": trend_yearly_pnl,
    }


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    prior = run_variant("prior_block")
    current = run_variant("current_guarded_pullback")

    all_trend = pd.concat([prior["trend_trades"], current["trend_trades"]], ignore_index=True)
    all_trend.to_csv(OUTDIR / "trend_annotated_closing_trades.csv", index=False)

    combo_metrics_rows = []
    for result in (prior, current):
        metrics = result["combo_metrics"]
        combo_metrics_rows.append(
            {
                "variant": result["variant"],
                "total_return": float(metrics["total_return"]),
                "benchmark_total_return": float(metrics.get("benchmark_total_return", float("nan"))),
                "excess_return": float(metrics.get("excess_return", float("nan"))),
                "information_ratio": float(metrics.get("information_ratio", float("nan"))),
                "alpha_annualized": float(metrics.get("alpha_annualized", float("nan"))),
                "beta": float(metrics.get("beta", float("nan"))),
                "max_drawdown": float(metrics["max_drawdown"]),
                "sharpe": float(metrics["sharpe"]),
                "final_equity": float(metrics["final_equity"]),
            }
        )
    combo_metrics_df = pd.DataFrame(combo_metrics_rows)
    combo_metrics_df.to_csv(OUTDIR / "combo_metrics.csv", index=False)

    years = sorted(set(prior["combo_yearly"].keys()) | set(current["combo_yearly"].keys()))
    combo_yearly_rows = []
    for year in years:
        prior_ret = float(prior["combo_yearly"].get(year, np.nan))
        current_ret = float(current["combo_yearly"].get(year, np.nan))
        combo_yearly_rows.append(
            {
                "year": year,
                "prior_block_return": prior_ret,
                "current_guarded_pullback_return": current_ret,
                "delta_return": current_ret - prior_ret,
            }
        )
    combo_yearly_df = pd.DataFrame(combo_yearly_rows)
    combo_yearly_df.to_csv(OUTDIR / "combo_yearly_comparison.csv", index=False)

    family_year_symbol = summarize(all_trend, ["variant", "entry_year", "symbol", "entry_family"])
    family_year_symbol.to_csv(OUTDIR / "trend_family_year_symbol_summary.csv", index=False)

    trend_year_symbol = summarize(all_trend, ["variant", "entry_year", "symbol"])
    trend_year_symbol.to_csv(OUTDIR / "trend_year_symbol_summary.csv", index=False)

    pivot = trend_year_symbol.pivot_table(
        index=["entry_year", "symbol"],
        columns="variant",
        values="total_pnl",
        aggfunc="first",
    ).reset_index()
    for col in ("prior_block", "current_guarded_pullback"):
        if col not in pivot.columns:
            pivot[col] = 0.0
    pivot["delta_pnl"] = pivot["current_guarded_pullback"] - pivot["prior_block"]
    pivot = pivot.sort_values("delta_pnl", ascending=False).reset_index(drop=True)
    pivot.to_csv(OUTDIR / "trend_year_symbol_delta.csv", index=False)

    guarded = all_trend[all_trend["entry_family"] == "GUARDED_PULLBACK_LONG"].copy()
    guarded.to_csv(OUTDIR / "guarded_pullback_trades.csv", index=False)
    summarize(guarded, ["entry_year"]).to_csv(OUTDIR / "guarded_pullback_by_year.csv", index=False)
    summarize(guarded, ["symbol"]).to_csv(OUTDIR / "guarded_pullback_by_symbol.csv", index=False)
    summarize(guarded, ["market_regime"]).to_csv(OUTDIR / "guarded_pullback_by_market_regime.csv", index=False)
    summarize(guarded, ["market_adx_tier"]).to_csv(OUTDIR / "guarded_pullback_by_market_adx_tier.csv", index=False)
    summarize(guarded, ["entry_regime", "symbol"]).to_csv(
        OUTDIR / "guarded_pullback_by_entry_regime_symbol.csv", index=False
    )

    top_guarded = guarded.sort_values("pnl", ascending=False).head(15)
    worst_guarded = guarded.sort_values("pnl", ascending=True).head(15)
    top_guarded.to_csv(OUTDIR / "top_guarded_pullback_trades.csv", index=False)
    worst_guarded.to_csv(OUTDIR / "worst_guarded_pullback_trades.csv", index=False)

    print("Saved analysis to:", OUTDIR)
    with pd.option_context("display.max_columns", 200, "display.width", 220):
        print("\nCombo metrics")
        print(combo_metrics_df.to_string(index=False))
        print("\nCombo yearly comparison")
        print(combo_yearly_df.to_string(index=False))
        print("\nTrend year/symbol delta (top)")
        print(pivot.head(10).to_string(index=False))
        if not guarded.empty:
            print("\nGuarded pullback summary by year")
            print(pd.read_csv(OUTDIR / "guarded_pullback_by_year.csv").to_string(index=False))
            print("\nGuarded pullback summary by symbol")
            print(pd.read_csv(OUTDIR / "guarded_pullback_by_symbol.csv").to_string(index=False))


if __name__ == "__main__":
    main()
