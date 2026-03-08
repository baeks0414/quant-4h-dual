#!/usr/bin/env python3
"""
가상 라이브 페이퍼 트레이딩 - 원샷 실행 스크립트
GitHub Actions에서 4시간마다 자동 실행됨.

실행:
    python scripts/paper_live_run.py

- 학습 구간 이후(2025-04-12 ~ 오늘)를 매번 재계산
- 결과를 results/paper_live/ 에 저장 (GitHub에 커밋됨)
"""
from __future__ import annotations

import os
import sys
from datetime import date, timezone, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 캐시 사용 안 함 (GitHub Actions 환경에서는 항상 최신 데이터)
os.environ["QUANT_BT_PROGRESS_EVERY"] = "0"
os.environ["QUANT_BT_SAVE_ARTIFACTS"] = "0"
os.environ["QUANT_MEM_CACHE"] = "0"

import pandas as pd

from quant.cli.backtest import run_backtest
from quant.config.presets import (
    preset_balanced_alpha_sleeve_aggressive,
    preset_dynamic_bear_state_trend,
)
from quant.core.metrics import compute_metrics
from quant.reporting.artifacts import save_csvs

LIVE_START     = "2025-04-12"        # 학습 구간 종료 이후
LIVE_END       = date.today().isoformat()
INITIAL_EQUITY = 10_000.0
TREND_WEIGHT   = 0.70
SLEEVE_WEIGHT  = 0.30
OUTDIR         = ROOT / "results" / "paper_live"


def yearly_monthly_returns(ec: pd.DataFrame) -> dict:
    ec = ec.copy()
    ec.index = pd.to_datetime(ec.index, utc=True)
    out = {}
    for year in sorted(set(ec.index.year)):
        sample = ec[ec.index.year == year]
        if not sample.empty:
            out[year] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def main() -> None:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print("=" * 60)
    print(f"  [PAPER LIVE] {now_utc}")
    print(f"  기간: {LIVE_START} ~ {LIVE_END}")
    print(f"  Trend {TREND_WEIGHT:.0%} + Sleeve {SLEEVE_WEIGHT:.0%}")
    print("=" * 60)

    OUTDIR.mkdir(parents=True, exist_ok=True)

    # ── Trend 엔진 ────────────────────────────────────
    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.start = LIVE_START
    trend_cfg.end   = LIVE_END
    trend_cfg.initial_equity = INITIAL_EQUITY * TREND_WEIGHT

    print("\n[Trend 엔진 실행 중...]")
    trend = run_backtest(trend_cfg, outdir=str(OUTDIR / "trend"))

    # ── Sleeve 엔진 ───────────────────────────────────
    sleeve_cfg = preset_balanced_alpha_sleeve_aggressive()
    sleeve_cfg.start = LIVE_START
    sleeve_cfg.end   = LIVE_END
    sleeve_cfg.initial_equity = INITIAL_EQUITY * SLEEVE_WEIGHT

    print("\n[Sleeve 엔진 실행 중...]")
    sleeve = run_backtest(sleeve_cfg, outdir=str(OUTDIR / "sleeve"))

    # ── 합산 ─────────────────────────────────────────
    trend_ec  = trend["equity_curve"][["equity"]].copy()
    sleeve_ec = sleeve["equity_curve"][["equity"]].copy()
    trend_ec.index  = pd.to_datetime(trend_ec.index,  utc=True)
    sleeve_ec.index = pd.to_datetime(sleeve_ec.index, utc=True)

    idx = trend_ec.index.intersection(sleeve_ec.index)
    combined = pd.DataFrame(index=idx)
    combined["equity"] = trend_ec.loc[idx, "equity"] + sleeve_ec.loc[idx, "equity"]
    peak = combined["equity"].cummax()
    combined["drawdown"] = combined["equity"] / peak - 1.0

    trades = pd.concat([trend["trades"], sleeve["trades"]], ignore_index=True)
    if not trades.empty and "time" in trades.columns:
        trades = trades.sort_values("time").reset_index(drop=True)

    benchmark_curve = trend["benchmark_equity_curve"][["equity"]].copy()
    benchmark_curve.index = pd.to_datetime(benchmark_curve.index, utc=True)
    benchmark_curve["equity"] = (
        benchmark_curve["equity"] / trend_cfg.initial_equity * INITIAL_EQUITY
    )
    benchmark_curve = benchmark_curve.loc[idx]
    peak_b = benchmark_curve["equity"].cummax()
    benchmark_curve["drawdown"] = benchmark_curve["equity"] / peak_b - 1.0

    metrics = compute_metrics(combined, trades, INITIAL_EQUITY, "4h", benchmark_curve=benchmark_curve)
    yearly  = yearly_monthly_returns(combined)

    # ── CSV 저장 ──────────────────────────────────────
    eq_path, tr_path = save_csvs(combined, trades, str(OUTDIR), "dual_combo_live")

    # ── 요약 로그 (누적 append) ───────────────────────
    log_path = OUTDIR / "run_log.csv"
    log_row = {
        "run_time":           now_utc,
        "live_start":         LIVE_START,
        "live_end":           LIVE_END,
        "total_return":       round(metrics.get("total_return", float("nan")), 6),
        "benchmark_return":   round(metrics.get("benchmark_total_return", float("nan")), 6),
        "excess_return":      round(metrics.get("excess_return", float("nan")), 6),
        "max_drawdown":       round(metrics.get("max_drawdown", float("nan")), 6),
        "sharpe":             round(metrics.get("sharpe", float("nan")), 6),
        "information_ratio":  round(metrics.get("information_ratio", float("nan")), 6),
        "num_trades":         metrics.get("num_round_trades", 0),
        "final_equity":       round(metrics.get("final_equity", float("nan")), 2),
    }
    for yr, ret in yearly.items():
        log_row[f"y{yr}"] = round(ret, 6)

    log_df = pd.DataFrame([log_row])
    if log_path.exists():
        old = pd.read_csv(log_path)
        log_df = pd.concat([old, log_df], ignore_index=True)
    log_df.to_csv(log_path, index=False)

    # ── 출력 ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  [COMBINED 결과]")
    print("=" * 60)
    final_eq = metrics.get("final_equity", 0.0)
    pnl      = final_eq - INITIAL_EQUITY
    ret_pct  = metrics.get("total_return", 0.0) * 100
    print(f"  초기자본  : ${INITIAL_EQUITY:>10,.2f}")
    print(f"  최종자산  : ${final_eq:>10,.2f}  ({pnl:+,.2f})")
    print(f"  총수익률  : {ret_pct:+.2f}%")
    print(f"  BTC벤치마크: {metrics.get('benchmark_total_return', 0)*100:+.2f}%")
    print(f"  초과수익  : {metrics.get('excess_return', 0)*100:+.2f}%p")
    print(f"  MDD       : {metrics.get('max_drawdown', 0)*100:.2f}%")
    print(f"  Sharpe    : {metrics.get('sharpe', 0):.4f}")
    print(f"  정보비율  : {metrics.get('information_ratio', 0):.4f}")
    print(f"  거래 수   : {metrics.get('num_round_trades', 0)}건")
    print()
    print("  연도별 수익률:")
    for yr, ret in yearly.items():
        print(f"    {yr}: {ret*100:+.2f}%")
    print(f"\n  equity_curve : {eq_path}")
    print(f"  trades       : {tr_path}")
    print(f"  run_log      : {log_path}")


if __name__ == "__main__":
    main()
