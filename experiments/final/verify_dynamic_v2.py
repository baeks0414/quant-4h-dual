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
from quant.config.presets import preset_dynamic_params_v2


OUTDIR = ROOT / "results" / "final" / "result_verify_dynamic_params_v2"


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
    cfg = preset_dynamic_params_v2()
    result = run_backtest(cfg, outdir=str(OUTDIR))
    metrics = result["metrics"]
    yearly = yearly_returns(result["equity_curve"])

    print("===== DYNAMIC PARAMS V2 =====")
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
        if year in yearly:
            print(f"return_{year}      : {yearly[year]:+.4%}")
    print(f"saved_to         : {OUTDIR}")


if __name__ == "__main__":
    main()
