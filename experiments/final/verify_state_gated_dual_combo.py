#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QUANT_BT_PROGRESS_EVERY", "0")

from quant.cli.backtest import run_backtest
from quant.config.presets import (
    preset_balanced_alpha_sleeve_aggressive,
    preset_dynamic_bear_state_trend,
)
from quant.core.metrics import compute_metrics
from quant.reporting.artifacts import save_csvs


TREND_WEIGHT = 0.70
SLEEVE_WEIGHT = 0.30
OUTDIR = ROOT / "results" / "final" / "result_verify_state_gated_dual_combo_robust_20260307"


def yearly_returns(ec: pd.DataFrame) -> dict[int, float]:
    view = ec.copy()
    view.index = pd.to_datetime(view.index, utc=True)
    out: dict[int, float] = {}
    for year in (2022, 2023, 2024, 2025):
        sample = view[view.index.year == year]
        if not sample.empty:
            out[year] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def main() -> None:
    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.initial_equity = 10_000.0 * TREND_WEIGHT

    sleeve_cfg = preset_balanced_alpha_sleeve_aggressive()
    sleeve_cfg.initial_equity = 10_000.0 * SLEEVE_WEIGHT

    trend = run_backtest(trend_cfg, outdir=str(OUTDIR / "trend"))
    sleeve = run_backtest(sleeve_cfg, outdir=str(OUTDIR / "sleeve"))

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

    metrics = compute_metrics(combined, trades, 10_000.0, "4h")
    benchmark_curve = trend["benchmark_equity_curve"][["equity"]].copy()
    benchmark_curve.index = pd.to_datetime(benchmark_curve.index, utc=True)
    benchmark_curve["equity"] = benchmark_curve["equity"] / trend_cfg.initial_equity * 10_000.0
    benchmark_curve = benchmark_curve.loc[idx]
    peak_b = benchmark_curve["equity"].cummax()
    benchmark_curve["drawdown"] = benchmark_curve["equity"] / peak_b - 1.0
    metrics = compute_metrics(combined, trades, 10_000.0, "4h", benchmark_curve=benchmark_curve)
    yearly = yearly_returns(combined)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    eq_path, tr_path = save_csvs(combined, trades, str(OUTDIR), "state_gated_dual_combo")

    print("===== STATE-GATED DUAL COMBO =====")
    print(f"trend_weight   : {TREND_WEIGHT:.2%}")
    print(f"sleeve_weight  : {SLEEVE_WEIGHT:.2%}")
    for key in (
        "total_return",
        "benchmark_total_return",
        "excess_return",
        "information_ratio",
        "alpha_annualized",
        "beta",
        "max_drawdown",
        "sharpe",
        "num_round_trades",
        "final_equity",
    ):
        value = metrics.get(key)
        if isinstance(value, float):
            print(f"{key:16s}: {value:.6f}")
        else:
            print(f"{key:16s}: {value}")
    for year in (2022, 2023, 2024, 2025):
        print(f"return_{year:4d}    : {yearly.get(year, 0.0):.6f}")
    print("saved_equity    :", eq_path)
    print("saved_trades    :", tr_path)


if __name__ == "__main__":
    main()
