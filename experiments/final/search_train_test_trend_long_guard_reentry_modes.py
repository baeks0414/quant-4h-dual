#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
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


OUTDIR = ROOT / "results" / "final" / "result_search_train_test_trend_long_guard_reentry_modes_20260308"
INITIAL_EQUITY = 10_000.0
TREND_WEIGHT = 0.70
ALPHA_WEIGHT = 0.30
TRAIN_START = "2022-01-01"
TRAIN_END = "2026-01-01"
TEST_START = "2026-01-01"
TEST_END = "2026-03-08"


@dataclass(frozen=True)
class Candidate:
    family: str
    name: str
    mode: str
    size_down_scale: float = 1.0
    pullback_wait_bars: int = 0


@contextlib.contextmanager
def silence_stdout():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield


def apply_candidate(cfg, candidate: Candidate) -> None:
    cfg.trend_long_guard_mode = candidate.mode
    cfg.trend_long_guard_size_down_scale = float(candidate.size_down_scale)
    cfg.trend_long_guard_pullback_max_wait_bars = int(candidate.pullback_wait_bars)


def yearly_returns(ec: pd.DataFrame) -> dict[int, float]:
    view = ec.copy()
    view.index = pd.to_datetime(view.index, utc=True)
    out: dict[int, float] = {}
    for year in sorted(set(view.index.year)):
        sample = view[view.index.year == year]
        if not sample.empty:
            out[year] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def count_guarded_entries(trades: pd.DataFrame) -> tuple[int, int]:
    if trades.empty:
        return 0, 0
    entry_mask = trades["type"].astype(str).isin(("ENTRY_LONG", "PYRAMID_LONG"))
    notes = trades.loc[entry_mask, "note"].astype(str)
    direct = int(notes.str.contains("guarded trend long", regex=False).sum())
    pullback = int(notes.str.contains("guarded trend pullback long", regex=False).sum())
    return direct, pullback


def run_combo(candidate: Candidate, start: str, end: str) -> dict[str, object]:
    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.start = start
    trend_cfg.end = end
    trend_cfg.initial_equity = INITIAL_EQUITY * TREND_WEIGHT
    apply_candidate(trend_cfg, candidate)

    alpha_cfg = preset_balanced_alpha_sleeve_aggressive()
    alpha_cfg.start = start
    alpha_cfg.end = end
    alpha_cfg.initial_equity = INITIAL_EQUITY * ALPHA_WEIGHT

    with silence_stdout():
        trend = run_backtest(trend_cfg, outdir=str(OUTDIR / "tmp_trend"))
    with silence_stdout():
        alpha = run_backtest(alpha_cfg, outdir=str(OUTDIR / "tmp_alpha"))

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

    metrics = compute_metrics(combined, trades, INITIAL_EQUITY, "4h", benchmark_curve=benchmark_curve)
    direct_count, pullback_count = count_guarded_entries(trend["trades"])
    return {
        "metrics": metrics,
        "yearly": yearly_returns(combined),
        "guarded_direct_entries": direct_count,
        "guarded_pullback_entries": pullback_count,
    }


def build_candidates() -> list[Candidate]:
    candidates = [Candidate("baseline", "baseline", "block")]
    for scale in (0.50, 0.65, 0.80):
        tag = str(scale).replace(".", "p")
        candidates.append(Candidate("size_down_direct", f"size_{tag}", "size_down", size_down_scale=scale))
    for wait_bars in (4, 6, 8):
        candidates.append(Candidate("pullback_only", f"pullback_w{wait_bars}", "pullback_only", pullback_wait_bars=wait_bars))
    for wait_bars in (4, 6, 8):
        for scale in (0.50, 0.65, 0.80):
            tag = str(scale).replace(".", "p")
            candidates.append(
                Candidate(
                    "pullback_plus_size_down",
                    f"pullback_w{wait_bars}_size_{tag}",
                    "pullback_only",
                    size_down_scale=scale,
                    pullback_wait_bars=wait_bars,
                )
            )
    return candidates


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    baseline_train: dict[str, object] | None = None
    baseline_test: dict[str, object] | None = None

    for candidate in build_candidates():
        train = run_combo(candidate, TRAIN_START, TRAIN_END)
        test = run_combo(candidate, TEST_START, TEST_END)

        if candidate.family == "baseline":
            baseline_train = train
            baseline_test = test

        assert baseline_train is not None
        assert baseline_test is not None

        train_metrics = train["metrics"]
        test_metrics = test["metrics"]

        rows.append(
            {
                "family": candidate.family,
                "candidate": candidate.name,
                "mode": candidate.mode,
                "size_down_scale": candidate.size_down_scale,
                "pullback_wait_bars": candidate.pullback_wait_bars,
                "train_total_return": float(train_metrics["total_return"]),
                "train_max_drawdown": float(train_metrics["max_drawdown"]),
                "train_sharpe": float(train_metrics["sharpe"]),
                "train_excess_return": float(train_metrics.get("excess_return", float("nan"))),
                "train_information_ratio": float(train_metrics.get("information_ratio", float("nan"))),
                "train_y2022": float(train["yearly"].get(2022, float("nan"))),
                "train_y2023": float(train["yearly"].get(2023, float("nan"))),
                "train_y2024": float(train["yearly"].get(2024, float("nan"))),
                "train_y2025": float(train["yearly"].get(2025, float("nan"))),
                "train_guarded_direct_entries": int(train["guarded_direct_entries"]),
                "train_guarded_pullback_entries": int(train["guarded_pullback_entries"]),
                "test_total_return": float(test_metrics["total_return"]),
                "test_max_drawdown": float(test_metrics["max_drawdown"]),
                "test_sharpe": float(test_metrics["sharpe"]),
                "test_excess_return": float(test_metrics.get("excess_return", float("nan"))),
                "test_information_ratio": float(test_metrics.get("information_ratio", float("nan"))),
                "test_y2026": float(test["yearly"].get(2026, float("nan"))),
                "test_guarded_direct_entries": int(test["guarded_direct_entries"]),
                "test_guarded_pullback_entries": int(test["guarded_pullback_entries"]),
                "delta_train_total_return": float(train_metrics["total_return"]) - float(baseline_train["metrics"]["total_return"]),
                "delta_train_max_drawdown": float(train_metrics["max_drawdown"]) - float(baseline_train["metrics"]["max_drawdown"]),
                "delta_train_sharpe": float(train_metrics["sharpe"]) - float(baseline_train["metrics"]["sharpe"]),
                "delta_test_total_return": float(test_metrics["total_return"]) - float(baseline_test["metrics"]["total_return"]),
                "delta_test_max_drawdown": float(test_metrics["max_drawdown"]) - float(baseline_test["metrics"]["max_drawdown"]),
                "delta_test_sharpe": float(test_metrics["sharpe"]) - float(baseline_test["metrics"]["sharpe"]),
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values(
        by=["family", "delta_train_sharpe", "delta_train_total_return", "delta_test_sharpe"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)
    df.to_csv(OUTDIR / "candidate_summary.csv", index=False)

    best_by_family = (
        df.sort_values(
            by=["delta_train_sharpe", "delta_train_total_return", "delta_test_sharpe"],
            ascending=[False, False, False],
        )
        .groupby("family", as_index=False)
        .head(1)
        .reset_index(drop=True)
    )
    best_by_family.to_csv(OUTDIR / "best_by_family.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
