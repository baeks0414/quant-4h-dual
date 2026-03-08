#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QUANT_BT_PROGRESS_EVERY", "0")
os.environ.setdefault("QUANT_BT_SAVE_ARTIFACTS", "0")
os.environ.setdefault("QUANT_BT_USE_MEM_CACHE", "1")

from experiments.final.validate_adopted_generalization import (
    Scenario,
    buy_hold_curve,
    run_adopted_dual,
)
from quant.data.binance_fetch import fetch_klines


DATE_TAG = "20260307"
WINDOW_MONTHS = 12
STEP_MONTHS = 1
RANGE_START = pd.Timestamp("2019-01-01", tz="UTC")
RANGE_END = pd.Timestamp("2025-04-12", tz="UTC")
OUTDIR = ROOT / "results" / "final" / f"result_validate_adopted_rolling_windows_{DATE_TAG}"


@dataclass(frozen=True)
class WindowResult:
    start: str
    end: str
    strategy_total_return: float
    strategy_max_drawdown: float
    buy_hold_total_return: float
    buy_hold_max_drawdown: float
    excess_total_return: float
    beats_buy_hold: bool


def generate_windows() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    effective_start = detect_effective_start()
    starts = []
    cur = effective_start
    while (cur + pd.DateOffset(months=WINDOW_MONTHS)) <= RANGE_END:
        starts.append(cur)
        cur = cur + pd.DateOffset(months=STEP_MONTHS)
    return [(start, start + pd.DateOffset(months=WINDOW_MONTHS)) for start in starts]


def detect_effective_start() -> pd.Timestamp:
    first_ts: list[pd.Timestamp] = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        probe = RANGE_START
        found = None
        while probe < RANGE_END:
            probe_end = min(probe + pd.Timedelta(days=180), RANGE_END)
            df = fetch_klines(
                sym,
                "4h",
                int(probe.timestamp() * 1000),
                int(probe_end.timestamp() * 1000),
            )
            if not df.empty:
                found = pd.Timestamp(df.index.min())
                break
            probe = probe + pd.DateOffset(months=1)
        if found is None:
            raise RuntimeError(f"No data available for {sym} between {RANGE_START} and {RANGE_END}")
        first_ts.append(found)
    return max([RANGE_START, *first_ts])


def run_window(start: pd.Timestamp, end: pd.Timestamp) -> WindowResult:
    scenario = Scenario(
        name=f"rolling_{start.date()}_{end.date()}",
        symbols=("BTCUSDT", "ETHUSDT"),
        market_symbol="BTCUSDT",
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        note="Rolling 12-month basket validation against equal-weight buy-and-hold.",
    )

    strategy_ec, _, strategy_metrics = run_adopted_dual(scenario)
    bh_ec = buy_hold_curve(scenario)

    strategy_total_return = float(strategy_metrics["total_return"])
    strategy_max_drawdown = float(strategy_metrics["max_drawdown"])
    buy_hold_total_return = float(bh_ec["equity"].iloc[-1] / bh_ec["equity"].iloc[0] - 1.0)
    buy_hold_max_drawdown = float(bh_ec["drawdown"].min())
    excess = strategy_total_return - buy_hold_total_return

    return WindowResult(
        start=scenario.start,
        end=scenario.end,
        strategy_total_return=strategy_total_return,
        strategy_max_drawdown=strategy_max_drawdown,
        buy_hold_total_return=buy_hold_total_return,
        buy_hold_max_drawdown=buy_hold_max_drawdown,
        excess_total_return=excess,
        beats_buy_hold=(strategy_total_return > buy_hold_total_return),
    )


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    windows = generate_windows()
    rows = [run_window(start, end) for start, end in windows]
    df = pd.DataFrame([row.__dict__ for row in rows])
    csv_path = OUTDIR / "rolling_windows.csv"
    df.to_csv(csv_path, index=False)

    worst = df.sort_values("strategy_total_return", ascending=True).iloc[0].to_dict()
    best = df.sort_values("strategy_total_return", ascending=False).iloc[0].to_dict()
    worst_excess = df.sort_values("excess_total_return", ascending=True).iloc[0].to_dict()
    best_excess = df.sort_values("excess_total_return", ascending=False).iloc[0].to_dict()

    summary = {
        "window_months": WINDOW_MONTHS,
        "step_months": STEP_MONTHS,
        "num_windows": int(len(df)),
        "worst_strategy_return": {
            "start": worst["start"],
            "end": worst["end"],
            "strategy_total_return": float(worst["strategy_total_return"]),
            "strategy_max_drawdown": float(worst["strategy_max_drawdown"]),
            "buy_hold_total_return": float(worst["buy_hold_total_return"]),
            "excess_total_return": float(worst["excess_total_return"]),
        },
        "best_strategy_return": {
            "start": best["start"],
            "end": best["end"],
            "strategy_total_return": float(best["strategy_total_return"]),
            "strategy_max_drawdown": float(best["strategy_max_drawdown"]),
            "buy_hold_total_return": float(best["buy_hold_total_return"]),
            "excess_total_return": float(best["excess_total_return"]),
        },
        "worst_excess_return": {
            "start": worst_excess["start"],
            "end": worst_excess["end"],
            "strategy_total_return": float(worst_excess["strategy_total_return"]),
            "buy_hold_total_return": float(worst_excess["buy_hold_total_return"]),
            "excess_total_return": float(worst_excess["excess_total_return"]),
        },
        "best_excess_return": {
            "start": best_excess["start"],
            "end": best_excess["end"],
            "strategy_total_return": float(best_excess["strategy_total_return"]),
            "buy_hold_total_return": float(best_excess["buy_hold_total_return"]),
            "excess_total_return": float(best_excess["excess_total_return"]),
        },
        "median_strategy_return": float(df["strategy_total_return"].median()),
        "median_buy_hold_return": float(df["buy_hold_total_return"].median()),
        "median_excess_return": float(df["excess_total_return"].median()),
        "mean_excess_return": float(df["excess_total_return"].mean()),
        "beat_buy_hold_ratio": float(df["beats_buy_hold"].mean()),
    }
    json_path = OUTDIR / "summary.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    print("===== ADOPTED BASELINE ROLLING WINDOWS =====")
    print(f"window_months      : {WINDOW_MONTHS}")
    print(f"step_months        : {STEP_MONTHS}")
    print(f"requested_start    : {RANGE_START.date()}")
    print(f"effective_start    : {pd.Timestamp(df['start'].min()).date()}")
    print(f"range_end          : {RANGE_END.date()}")
    print(f"num_windows        : {summary['num_windows']}")
    print(f"worst_strategy_ret : {summary['worst_strategy_return']}")
    print(f"best_strategy_ret  : {summary['best_strategy_return']}")
    print(f"worst_excess_ret   : {summary['worst_excess_return']}")
    print(f"best_excess_ret    : {summary['best_excess_return']}")
    print(f"median_strategy_ret: {summary['median_strategy_return']:.6f}")
    print(f"median_buyhold_ret : {summary['median_buy_hold_return']:.6f}")
    print(f"median_excess_ret  : {summary['median_excess_return']:.6f}")
    print(f"mean_excess_ret    : {summary['mean_excess_return']:.6f}")
    print(f"beat_buyhold_ratio : {summary['beat_buy_hold_ratio']:.2%}")
    print()
    print("Lowest 5 windows:")
    print(
        df.sort_values("strategy_total_return", ascending=True)
        .head(5)[
            [
                "start",
                "end",
                "strategy_total_return",
                "strategy_max_drawdown",
                "buy_hold_total_return",
                "excess_total_return",
                "beats_buy_hold",
            ]
        ]
        .to_string(index=False)
    )
    print()
    print("Highest 5 excess windows:")
    print(
        df.sort_values("excess_total_return", ascending=False)
        .head(5)[
            [
                "start",
                "end",
                "strategy_total_return",
                "buy_hold_total_return",
                "excess_total_return",
                "beats_buy_hold",
            ]
        ]
        .to_string(index=False)
    )
    print()
    print("saved_csv   :", csv_path)
    print("saved_json  :", json_path)


if __name__ == "__main__":
    main()
