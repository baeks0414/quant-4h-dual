#!/usr/bin/env python3
"""
가상 라이브 백테스트 (out-of-sample)
학습 구간 이후(2025-04-12 ~ 2026-03-08)에서 채택된 전략이 통하는지 검증.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QUANT_BT_PROGRESS_EVERY", "0")
os.environ.setdefault("QUANT_BT_USE_MEM_CACHE", "1")

from quant.cli.backtest import run_backtest
from quant.config.presets import (
    preset_balanced_alpha_sleeve_aggressive,
    preset_dynamic_bear_state_trend,
)
from quant.core.metrics import compute_metrics
from quant.reporting.artifacts import save_csvs


LIVE_START = "2025-04-12"
LIVE_END   = "2026-03-08"
INITIAL_EQUITY = 10_000.0
TREND_WEIGHT   = 0.70
SLEEVE_WEIGHT  = 0.30
OUTDIR = ROOT / "results" / "final" / "result_verify_virtual_live_20260308"


def yearly_returns(ec: pd.DataFrame) -> dict[int, float]:
    view = ec.copy()
    view.index = pd.to_datetime(view.index, utc=True)
    out: dict[int, float] = {}
    for year in sorted(set(view.index.year)):
        sample = view[view.index.year == year]
        if not sample.empty:
            out[year] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def main() -> None:
    print("=" * 60)
    print("  가상 라이브 백테스트 (Out-of-Sample)")
    print(f"  기간: {LIVE_START} ~ {LIVE_END}")
    print(f"  구성: Trend {TREND_WEIGHT:.0%} + Alpha Sleeve {SLEEVE_WEIGHT:.0%}")
    print("=" * 60)

    # Trend 엔진
    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.start = LIVE_START
    trend_cfg.end = LIVE_END
    trend_cfg.initial_equity = INITIAL_EQUITY * TREND_WEIGHT

    # Alpha Sleeve 엔진
    sleeve_cfg = preset_balanced_alpha_sleeve_aggressive()
    sleeve_cfg.start = LIVE_START
    sleeve_cfg.end = LIVE_END
    sleeve_cfg.initial_equity = INITIAL_EQUITY * SLEEVE_WEIGHT

    print("\n[Trend 엔진 실행]")
    trend = run_backtest(trend_cfg, outdir=str(OUTDIR / "trend"))

    print("\n[Alpha Sleeve 엔진 실행]")
    sleeve = run_backtest(sleeve_cfg, outdir=str(OUTDIR / "sleeve"))

    # 합산 equity curve
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

    # 벤치마크 (BTC buy-and-hold)
    benchmark_curve = trend["benchmark_equity_curve"][["equity"]].copy()
    benchmark_curve.index = pd.to_datetime(benchmark_curve.index, utc=True)
    benchmark_curve["equity"] = benchmark_curve["equity"] / trend_cfg.initial_equity * INITIAL_EQUITY
    benchmark_curve = benchmark_curve.loc[idx]
    peak_b = benchmark_curve["equity"].cummax()
    benchmark_curve["drawdown"] = benchmark_curve["equity"] / peak_b - 1.0

    metrics = compute_metrics(combined, trades, INITIAL_EQUITY, "4h", benchmark_curve=benchmark_curve)
    yearly = yearly_returns(combined)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    eq_path, tr_path = save_csvs(combined, trades, str(OUTDIR), "virtual_live_dual_combo")

    print("\n" + "=" * 60)
    print("  [COMBINED] 가상 라이브 결과")
    print("=" * 60)
    keys = [
        "total_return", "benchmark_total_return", "excess_return",
        "information_ratio", "alpha_annualized", "beta",
        "max_drawdown", "sharpe", "num_round_trades", "final_equity",
        "winrate", "avg_win", "avg_loss", "funding_pnl",
    ]
    for k in keys:
        v = metrics.get(k)
        if isinstance(v, float):
            print(f"  {k:24s}: {v:.6f}")
        elif v is not None:
            print(f"  {k:24s}: {v}")

    print("\n  연도별 수익률:")
    for yr, ret in yearly.items():
        print(f"    {yr}: {ret:+.2%}")

    print(f"\n  [개별]")
    t_m = trend["metrics"]
    s_m = sleeve["metrics"]
    print(f"  Trend  ({TREND_WEIGHT:.0%}): return={t_m['total_return']:.4f}x  MDD={t_m['max_drawdown']:.4f}  Sharpe={t_m['sharpe']:.4f}  final=${trend_ec.iloc[-1]['equity']:,.0f}")
    print(f"  Sleeve ({SLEEVE_WEIGHT:.0%}): return={s_m['total_return']:.4f}x  MDD={s_m['max_drawdown']:.4f}  Sharpe={s_m['sharpe']:.4f}  final=${sleeve_ec.iloc[-1]['equity']:,.0f}")
    print(f"\n  CSV 저장: {eq_path}")


if __name__ == "__main__":
    main()
