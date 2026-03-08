#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QUANT_BT_PROGRESS_EVERY", "0")
os.environ.setdefault("QUANT_BT_SAVE_ARTIFACTS", "0")
os.environ.setdefault("QUANT_BT_USE_MEM_CACHE", "1")

from quant.cli.backtest import run_backtest
from quant.config.presets import (
    preset_balanced_alpha_sleeve_aggressive,
    preset_dynamic_bear_state_trend,
)
from quant.core.metrics import compute_metrics
from quant.data.binance_fetch import fetch_klines


DATE_TAG = "20260307"
INITIAL_EQUITY = 10_000.0
TREND_WEIGHT = 0.70
SLEEVE_WEIGHT = 0.30
INTERVAL = "4h"
OUTDIR = ROOT / "results" / "final" / f"result_validate_adopted_generalization_{DATE_TAG}"


@dataclass(frozen=True)
class Scenario:
    name: str
    symbols: tuple[str, ...]
    market_symbol: str
    start: str
    end: str
    note: str


SCENARIOS = [
    Scenario(
        name="basket_2020",
        symbols=("BTCUSDT", "ETHUSDT"),
        market_symbol="BTCUSDT",
        start="2020-01-01",
        end="2021-01-01",
        note="Adopted basket on calendar year 2020 vs equal-weight buy-and-hold basket.",
    ),
    Scenario(
        name="basket_2021",
        symbols=("BTCUSDT", "ETHUSDT"),
        market_symbol="BTCUSDT",
        start="2021-01-01",
        end="2022-01-01",
        note="Adopted basket on calendar year 2021 vs equal-weight buy-and-hold basket.",
    ),
    Scenario(
        name="eth_single_2022_2025",
        symbols=("ETHUSDT",),
        market_symbol="ETHUSDT",
        start="2022-01-01",
        end="2025-04-12",
        note="Single-symbol transfer test on ETH; market gate uses ETH because the engine expects market_symbol inside symbols.",
    ),
    Scenario(
        name="sol_single_2022_2025",
        symbols=("SOLUSDT",),
        market_symbol="SOLUSDT",
        start="2022-01-01",
        end="2025-04-12",
        note="Single-symbol transfer test on SOL; market gate uses SOL because the engine expects market_symbol inside symbols.",
    ),
]


@contextlib.contextmanager
def silence_stdout():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield


def yearly_returns(ec: pd.DataFrame) -> dict[int, float]:
    view = ec.copy()
    view.index = pd.to_datetime(view.index, utc=True)
    out: dict[int, float] = {}
    for year in sorted(view.index.year.unique()):
        sample = view[view.index.year == year]
        if len(sample) >= 2:
            out[int(year)] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def min_yearly_return(yearly: dict[int, float]) -> float:
    if not yearly:
        return float("nan")
    return float(min(yearly.values()))


def build_dual_configs(
    *,
    symbols: tuple[str, ...],
    market_symbol: str,
    start: str,
    end: str,
) -> tuple[object, object]:
    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.symbols = symbols
    trend_cfg.market_symbol = market_symbol
    trend_cfg.interval = INTERVAL
    trend_cfg.start = start
    trend_cfg.end = end
    trend_cfg.initial_equity = INITIAL_EQUITY * TREND_WEIGHT

    sleeve_cfg = preset_balanced_alpha_sleeve_aggressive()
    sleeve_cfg.symbols = symbols
    sleeve_cfg.market_symbol = market_symbol
    sleeve_cfg.interval = INTERVAL
    sleeve_cfg.start = start
    sleeve_cfg.end = end
    sleeve_cfg.initial_equity = INITIAL_EQUITY * SLEEVE_WEIGHT

    return trend_cfg, sleeve_cfg


def combine_dual_results(trend: dict, sleeve: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if trend["equity_curve"] is None or trend["equity_curve"].empty or "equity" not in trend["equity_curve"].columns:
        raise RuntimeError("Trend sleeve returned no aligned equity curve.")
    if sleeve["equity_curve"] is None or sleeve["equity_curve"].empty or "equity" not in sleeve["equity_curve"].columns:
        raise RuntimeError("Alpha sleeve returned no aligned equity curve.")

    trend_ec = trend["equity_curve"][["equity"]].copy()
    sleeve_ec = sleeve["equity_curve"][["equity"]].copy()
    trend_ec.index = pd.to_datetime(trend_ec.index, utc=True)
    sleeve_ec.index = pd.to_datetime(sleeve_ec.index, utc=True)

    idx = trend_ec.index.intersection(sleeve_ec.index)
    combined = pd.DataFrame(index=idx)
    combined["equity"] = trend_ec.loc[idx, "equity"] + sleeve_ec.loc[idx, "equity"]
    peak = combined["equity"].cummax()
    combined["drawdown"] = combined["equity"] / peak - 1.0

    trades = pd.concat([trend["trades"], sleeve["trades"]], ignore_index=True)
    if not trades.empty and "time" in trades.columns:
        trades = trades.sort_values("time").reset_index(drop=True)

    metrics = compute_metrics(combined, trades, INITIAL_EQUITY, INTERVAL)
    return combined, trades, metrics


def run_adopted_dual(scenario: Scenario) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    trend_cfg, sleeve_cfg = build_dual_configs(
        symbols=scenario.symbols,
        market_symbol=scenario.market_symbol,
        start=scenario.start,
        end=scenario.end,
    )
    with silence_stdout():
        trend = run_backtest(trend_cfg, outdir=str(OUTDIR / scenario.name / "trend"))
    with silence_stdout():
        sleeve = run_backtest(sleeve_cfg, outdir=str(OUTDIR / scenario.name / "sleeve"))
    return combine_dual_results(trend, sleeve)


def buy_hold_curve(scenario: Scenario) -> pd.DataFrame:
    start_ms = int(pd.Timestamp(scenario.start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(scenario.end, tz="UTC").timestamp() * 1000)

    close_map: dict[str, pd.Series] = {}
    for sym in scenario.symbols:
        df = fetch_klines(sym, INTERVAL, start_ms, end_ms)
        if df.empty:
            raise RuntimeError(f"No price data for {sym} in {scenario.name}")
        close_map[sym] = df["close"].rename(sym)

    idx = None
    for series in close_map.values():
        idx = series.index if idx is None else idx.intersection(series.index)
    assert idx is not None
    idx = idx.sort_values()
    if len(idx) < 2:
        raise RuntimeError(f"Not enough aligned buy-and-hold data in {scenario.name}")

    close_df = pd.concat([close_map[sym].loc[idx] for sym in scenario.symbols], axis=1)
    normalized = close_df / close_df.iloc[0]
    equity = INITIAL_EQUITY * normalized.mean(axis=1)

    out = pd.DataFrame(index=idx)
    out["equity"] = equity
    peak = out["equity"].cummax()
    out["drawdown"] = out["equity"] / peak - 1.0
    return out


def scenario_row(scenario: Scenario) -> dict[str, object]:
    strategy_ec, _, strategy_metrics = run_adopted_dual(scenario)
    bh_ec = buy_hold_curve(scenario)
    bh_metrics = compute_metrics(bh_ec, pd.DataFrame(), INITIAL_EQUITY, INTERVAL)

    strategy_yearly = yearly_returns(strategy_ec)
    bh_yearly = yearly_returns(bh_ec)

    return {
        "scenario": scenario.name,
        "symbols": ",".join(scenario.symbols),
        "market_symbol": scenario.market_symbol,
        "start": scenario.start,
        "end": scenario.end,
        "note": scenario.note,
        "strategy_final_equity": float(strategy_metrics["final_equity"]),
        "strategy_total_return": float(strategy_metrics["total_return"]),
        "strategy_max_drawdown": float(strategy_metrics["max_drawdown"]),
        "strategy_sharpe": float(strategy_metrics["sharpe"]),
        "strategy_num_round_trades": int(strategy_metrics["num_round_trades"]),
        "buy_hold_final_equity": float(bh_metrics["final_equity"]),
        "buy_hold_total_return": float(bh_metrics["total_return"]),
        "buy_hold_max_drawdown": float(bh_metrics["max_drawdown"]),
        "buy_hold_sharpe": float(bh_metrics["sharpe"]),
        "excess_total_return": float(strategy_metrics["total_return"] - bh_metrics["total_return"]),
        "beats_buy_hold": bool(strategy_metrics["final_equity"] > bh_metrics["final_equity"]),
        "strategy_min_year_return": min_yearly_return(strategy_yearly),
        "buy_hold_min_year_return": min_yearly_return(bh_yearly),
        "strategy_yearly": json.dumps(strategy_yearly, ensure_ascii=True, sort_keys=True),
        "buy_hold_yearly": json.dumps(bh_yearly, ensure_ascii=True, sort_keys=True),
    }


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    rows = [scenario_row(scenario) for scenario in SCENARIOS]
    df = pd.DataFrame(rows)
    summary_path = OUTDIR / "summary.csv"
    df.to_csv(summary_path, index=False)

    display_cols = [
        "scenario",
        "symbols",
        "strategy_final_equity",
        "strategy_total_return",
        "strategy_max_drawdown",
        "buy_hold_final_equity",
        "buy_hold_total_return",
        "buy_hold_max_drawdown",
        "excess_total_return",
        "beats_buy_hold",
    ]
    print("===== ADOPTED BASELINE GENERALIZATION =====")
    print(df[display_cols].to_string(index=False))
    print()
    for row in rows:
        print(f"[{row['scenario']}]")
        print("  strategy_yearly :", row["strategy_yearly"])
        print("  buy_hold_yearly :", row["buy_hold_yearly"])
        print("  note            :", row["note"])
    print()
    print("saved_summary :", summary_path)


if __name__ == "__main__":
    main()
