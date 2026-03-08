"""
레짐별 PnL 분석 - 전체 기간 vs 2025년
ENTRY note를 EXIT PnL에 매칭해서 레짐별 수익 귀속
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ["QUANT_BT_SAVE_ARTIFACTS"] = "0"

import pandas as pd
from collections import defaultdict
from quant.config.presets import preset_regime_only_live
from quant.cli.backtest import run_backtest


def entry_note_to_regime(note: str) -> str:
    if not isinstance(note, str):
        return "unknown"
    n = note.lower()
    if "funding" in n:
        return "FUNDING"
    if "trend pullback" in n:
        return "TREND_PULLBACK"
    if "micro trend" in n:
        return "MICRO_TREND"
    if "trend" in n:
        return "STRONG_TREND"
    if "vol break" in n or "vol_break" in n:
        return "VOL_EXPAND"
    if "chop" in n:
        return "CHOP"
    if "alpha2025 vol" in n or "alpha vol" in n or "vol revert" in n:
        return "VOL_REVERT"
    return "other"


def match_entries_to_exits(trades: pd.DataFrame) -> pd.DataFrame:
    """
    ENTRY_LONG/ENTRY_SHORT note를 EXIT/STOP PnL에 매칭.
    심볼별로 순서대로 매칭한다.
    """
    if trades.empty:
        return pd.DataFrame()

    results = []
    # 심볼별로 분리
    for sym in trades["symbol"].unique():
        sym_trades = trades[trades["symbol"] == sym].copy().reset_index(drop=True)
        entry_stack = []  # (time, regime) 스택
        for _, row in sym_trades.iterrows():
            t = row["type"]
            if t in ("ENTRY_LONG", "ENTRY_SHORT"):
                direction = "LONG" if t == "ENTRY_LONG" else "SHORT"
                regime = entry_note_to_regime(str(row.get("note", "")))
                entry_stack.append((row["time"], regime, direction))
            elif t in ("EXIT", "STOP_LONG", "STOP_SHORT"):
                pnl = float(row["pnl"])
                if entry_stack:
                    entry_time, regime, direction = entry_stack.pop(0)
                else:
                    regime = "unknown"
                    direction = "?"
                    entry_time = row["time"]
                results.append({
                    "symbol": sym,
                    "entry_time": entry_time,
                    "exit_time": row["time"],
                    "regime": regime,
                    "direction": direction,
                    "pnl": pnl,
                    "exit_type": t,
                })
            elif t == "FUNDING":
                results.append({
                    "symbol": sym,
                    "entry_time": row["time"],
                    "exit_time": row["time"],
                    "regime": "FUNDING",
                    "direction": "FUNDING",
                    "pnl": float(row["pnl"]),
                    "exit_type": "FUNDING",
                })

    return pd.DataFrame(results)


def print_regime_table(matched: pd.DataFrame, label: str):
    print(f"\n{'='*62}")
    print(f"  {label}")
    print(f"{'='*62}")

    if matched.empty:
        print("  데이터 없음")
        return

    real = matched[matched["regime"] != "FUNDING"]
    total_pnl = real["pnl"].sum()
    n = len(real)
    wins = (real["pnl"] > 0).sum()
    print(f"  라운드트립: {n}건  승률: {wins/n:.1%}  총PnL: ${total_pnl:,.0f}")

    print(f"\n  {'레짐':<18} {'거래':>5} {'승':>4} {'승률':>6} {'총PnL':>10} {'평PnL':>8} {'최대손':>9}")
    print(f"  {'-'*63}")

    rows_out = []
    for reg, grp in real.groupby("regime"):
        n_ = len(grp)
        w_ = (grp["pnl"] > 0).sum()
        s_ = grp["pnl"].sum()
        avg_ = grp["pnl"].mean()
        worst_ = grp["pnl"].min()
        rows_out.append((s_, reg, n_, w_, s_, avg_, worst_))

    rows_out.sort(key=lambda x: -x[0])
    for _, reg, n_, w_, s_, avg_, worst_ in rows_out:
        wr = w_ / n_ if n_ else 0
        print(f"  {reg:<18} {n_:>5} {w_:>4} {wr:>6.1%} {s_:>10,.0f} {avg_:>8,.0f} {worst_:>9,.0f}")

    # 방향별
    print(f"\n  방향별:")
    for dir_, grp in real.groupby("direction"):
        n_ = len(grp)
        w_ = (grp["pnl"] > 0).sum()
        s_ = grp["pnl"].sum()
        wr = w_ / n_ if n_ else 0
        print(f"    {dir_:<8} {n_:>4}건  승률 {wr:.1%}  PnL ${s_:,.0f}")

    # 펀딩 합계
    fund = matched[matched["regime"] == "FUNDING"]
    if not fund.empty:
        print(f"\n  펀딩 PnL: ${fund['pnl'].sum():,.0f}")


def run_and_analyze(label: str, start: str, end: str):
    cfg = preset_regime_only_live()
    cfg.start = start
    cfg.end = end
    print(f"\n[{label}] 백테스트 실행 ({start} ~ {end})...")
    outdir = ROOT / "results" / "analysis" / f"result_analysis_{start[:4]}"
    outdir.mkdir(parents=True, exist_ok=True)
    res = run_backtest(cfg, outdir=str(outdir))
    m = res["metrics"]
    print(f"  ret={m.get('total_return',0):.4f}  sharpe={m.get('sharpe',0):.3f}  "
          f"mdd={m.get('max_drawdown',0):.3f}  wr={m.get('win_rate',0):.2%}  "
          f"trades={m.get('num_round_trades',0)}")

    matched = match_entries_to_exits(res["trades"])
    print_regime_table(matched, label)
    return res, matched


def main():
    # 전체
    r_full, m_full = run_and_analyze("전체 기간", "2022-01-01", "2025-04-12")

    # 2025년
    r_2025, m_2025 = run_and_analyze("2025년", "2025-01-01", "2025-04-12")

    # 2024년 (비교)
    r_2024, m_2024 = run_and_analyze("2024년", "2024-01-01", "2024-12-31")

    # 최종 요약
    print(f"\n\n{'='*62}")
    print("  최종 요약")
    print(f"{'='*62}")
    for label, res in [("전체", r_full), ("2024", r_2024), ("2025", r_2025)]:
        m = res["metrics"]
        print(f"  {label:<6}: ret={m.get('total_return',0):>7.4f}  "
              f"sharpe={m.get('sharpe',0):.3f}  "
              f"mdd={m.get('max_drawdown',0):.3f}  "
              f"wr={m.get('win_rate',0):.2%}")

    # 2025 vs 2024 상세 레짐 비교
    if not m_2025.empty and not m_2024.empty:
        print(f"\n  2024 vs 2025 레짐별 PnL 차이:")
        real_2024 = m_2024[m_2024["regime"] != "FUNDING"]
        real_2025 = m_2025[m_2025["regime"] != "FUNDING"]
        reg_2024 = real_2024.groupby("regime")["pnl"].sum().to_dict()
        reg_2025 = real_2025.groupby("regime")["pnl"].sum().to_dict()
        all_regs = sorted(set(list(reg_2024.keys()) + list(reg_2025.keys())))
        print(f"  {'레짐':<18} {'2024 PnL':>10} {'2025 PnL':>10}")
        print(f"  {'-'*40}")
        for reg in all_regs:
            p24 = reg_2024.get(reg, 0)
            p25 = reg_2025.get(reg, 0)
            print(f"  {reg:<18} {p24:>10,.0f} {p25:>10,.0f}")


if __name__ == "__main__":
    main()
