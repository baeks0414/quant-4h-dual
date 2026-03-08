#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


DATE_TAG = "20260307_bc"
OUTDIR = ROOT / "results" / "final" / f"result_iterate_adopted_improvements_{DATE_TAG}"
YEARS = (2022, 2023, 2024, 2025)
INITIAL_EQUITY = 10_000.0
TREND_WEIGHT = 0.70
ALPHA_WEIGHT = 0.30


@dataclass(frozen=True)
class Candidate:
    stage: str
    name: str
    note: str
    trend_changes: dict[str, float | int | bool]
    alpha_changes: dict[str, float | int | bool]


def yearly_returns(ec: pd.DataFrame) -> dict[int, float]:
    view = ec.copy()
    view.index = pd.to_datetime(view.index, utc=True)
    out: dict[int, float] = {}
    for year in YEARS:
        sample = view[view.index.year == year]
        if not sample.empty:
            out[year] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def market_score(metrics: dict[str, float]) -> float:
    excess = float(metrics.get("excess_return", metrics["total_return"]))
    info = float(metrics.get("information_ratio", 0.0))
    alpha = float(metrics.get("alpha_annualized", 0.0))
    mdd = float(metrics["max_drawdown"])
    penalty = 12.0 * max(0.0, abs(mdd) - 0.20)
    return math.log1p(max(excess, -0.99)) + 0.35 * info + 0.15 * alpha - penalty


@contextlib.contextmanager
def silence_stdout():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield


def apply_changes(cfg, changes: dict[str, float | int | bool]) -> None:
    for key, value in changes.items():
        setattr(cfg, key, value)


def run_combo(
    trend_changes: dict[str, float | int | bool],
    alpha_changes: dict[str, float | int | bool],
) -> dict[str, object]:
    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.initial_equity = INITIAL_EQUITY * TREND_WEIGHT
    apply_changes(trend_cfg, trend_changes)

    alpha_cfg = preset_balanced_alpha_sleeve_aggressive()
    alpha_cfg.initial_equity = INITIAL_EQUITY * ALPHA_WEIGHT
    apply_changes(alpha_cfg, alpha_changes)

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
    yearly = yearly_returns(combined)
    worst_year = min(float(yearly.get(year, -1.0)) for year in YEARS)
    return {
        "metrics": metrics,
        "yearly": yearly,
        "worst_year_return": worst_year,
        "market_score": market_score(metrics),
    }


def summarize(
    label: str,
    stage: str,
    note: str,
    trend_changes: dict[str, float | int | bool],
    alpha_changes: dict[str, float | int | bool],
    result: dict[str, object],
) -> dict[str, object]:
    metrics = result["metrics"]
    yearly = result["yearly"]
    return {
        "stage": stage,
        "candidate": label,
        "note": note,
        "trend_changes": json.dumps(trend_changes, sort_keys=True),
        "alpha_changes": json.dumps(alpha_changes, sort_keys=True),
        "market_score": float(result["market_score"]),
        "total_return": float(metrics["total_return"]),
        "excess_return": float(metrics.get("excess_return", float("nan"))),
        "information_ratio": float(metrics.get("information_ratio", float("nan"))),
        "alpha_annualized": float(metrics.get("alpha_annualized", float("nan"))),
        "max_drawdown": float(metrics["max_drawdown"]),
        "final_equity": float(metrics["final_equity"]),
        "sharpe": float(metrics["sharpe"]),
        "worst_year_return": float(result["worst_year_return"]),
        "y2022": float(yearly.get(2022, float("nan"))),
        "y2023": float(yearly.get(2023, float("nan"))),
        "y2024": float(yearly.get(2024, float("nan"))),
        "y2025": float(yearly.get(2025, float("nan"))),
    }


def all_years_positive(summary: dict[str, object]) -> bool:
    return all(float(summary[f"y{year}"]) > 0.0 for year in YEARS)


def accepts(current: dict[str, object], candidate: dict[str, object]) -> tuple[bool, str]:
    if not all_years_positive(candidate):
        return False, "reject: yearly return turned negative"
    if float(candidate["worst_year_return"]) < float(current["worst_year_return"]) - 0.02:
        return False, "reject: worst-year return degraded by more than 2%p"
    if float(candidate["max_drawdown"]) < float(current["max_drawdown"]) - 0.01:
        return False, "reject: drawdown worsened by more than 1%p"

    score_delta = float(candidate["market_score"]) - float(current["market_score"])
    worst_delta = float(candidate["worst_year_return"]) - float(current["worst_year_return"])
    equity_delta = float(candidate["final_equity"]) / float(current["final_equity"]) - 1.0

    if score_delta >= 0.02:
        return True, "accept: market score improved by >= 0.02 within guardrails"
    if score_delta >= 0.0 and worst_delta >= 0.01 and equity_delta >= -0.02:
        return True, "accept: stability improved without meaningful capital loss"
    return False, "reject: improvement too small after guardrails"


def stage_candidates() -> list[list[Candidate]]:
    return [
        [
            Candidate(
                stage="trend_filter_b",
                name="b_mild",
                note="Slightly tighten trend-sleeve EMA spread/buffer and require two-bar entry confirmation.",
                trend_changes={
                    "trend_min_ema_spread_atr": 0.12,
                    "trend_entry_buffer_atr": 0.01,
                    "entry_confirm_bars": 2,
                },
                alpha_changes={},
            ),
            Candidate(
                stage="trend_filter_b",
                name="b_balanced",
                note="Moderately tighten trend-sleeve EMA spread/buffer with two-bar confirmation.",
                trend_changes={
                    "trend_min_ema_spread_atr": 0.14,
                    "trend_entry_buffer_atr": 0.02,
                    "entry_confirm_bars": 2,
                },
                alpha_changes={},
            ),
            Candidate(
                stage="trend_filter_b",
                name="b_strict",
                note="Strict trend-sleeve filter: larger spread, more extension, and two-bar confirmation.",
                trend_changes={
                    "trend_min_ema_spread_atr": 0.16,
                    "trend_entry_buffer_atr": 0.03,
                    "entry_confirm_bars": 2,
                },
                alpha_changes={},
            ),
        ],
        [
            Candidate(
                stage="trend_filter_b_refine",
                name="b_refine_spread_013",
                note="Refine the trend filter around a mild spread increase with a slightly larger buffer.",
                trend_changes={
                    "trend_min_ema_spread_atr": 0.13,
                    "trend_entry_buffer_atr": 0.02,
                    "entry_confirm_bars": 2,
                },
                alpha_changes={},
            ),
            Candidate(
                stage="trend_filter_b_refine",
                name="b_refine_low_buffer",
                note="Keep two-bar confirmation but test less price extension with slightly tighter spread.",
                trend_changes={
                    "trend_min_ema_spread_atr": 0.14,
                    "trend_entry_buffer_atr": 0.01,
                    "entry_confirm_bars": 2,
                },
                alpha_changes={},
            ),
            Candidate(
                stage="trend_filter_b_refine",
                name="b_refine_high_spread",
                note="Push spread quality slightly higher while keeping the buffer moderate.",
                trend_changes={
                    "trend_min_ema_spread_atr": 0.15,
                    "trend_entry_buffer_atr": 0.02,
                    "entry_confirm_bars": 2,
                },
                alpha_changes={},
            ),
        ],
        [
            Candidate(
                stage="pyramiding_c",
                name="c_mild",
                note="Require more unrealized profit and ADX strength before adds, with smaller add-on risk.",
                trend_changes={
                    "pyramid_min_profit_atr": 1.4,
                    "pyramid_risk_scale": 0.35,
                    "pyramid_min_adx": 18.0,
                },
                alpha_changes={},
            ),
            Candidate(
                stage="pyramiding_c",
                name="c_balanced",
                note="More selective trend-sleeve pyramiding with lower add-on risk.",
                trend_changes={
                    "pyramid_min_profit_atr": 1.5,
                    "pyramid_risk_scale": 0.30,
                    "pyramid_min_adx": 20.0,
                },
                alpha_changes={},
            ),
            Candidate(
                stage="pyramiding_c",
                name="c_strict",
                note="Only add in stronger trends after larger profit cushion and smaller add size.",
                trend_changes={
                    "pyramid_min_profit_atr": 1.6,
                    "pyramid_risk_scale": 0.25,
                    "pyramid_min_adx": 22.0,
                },
                alpha_changes={},
            ),
        ],
        [
            Candidate(
                stage="pyramiding_c_refine",
                name="c_refine_adx15",
                note="Refine pyramiding with a moderate ADX floor and slightly smaller add risk.",
                trend_changes={
                    "pyramid_min_profit_atr": 1.35,
                    "pyramid_risk_scale": 0.34,
                    "pyramid_min_adx": 15.0,
                },
                alpha_changes={},
            ),
            Candidate(
                stage="pyramiding_c_refine",
                name="c_refine_profit145",
                note="Test a mid-point between mild and balanced pyramiding strictness.",
                trend_changes={
                    "pyramid_min_profit_atr": 1.45,
                    "pyramid_risk_scale": 0.30,
                    "pyramid_min_adx": 18.0,
                },
                alpha_changes={},
            ),
            Candidate(
                stage="pyramiding_c_refine",
                name="c_refine_profit150",
                note="Keep larger profit gating but ease ADX and add-risk slightly versus the strict candidate.",
                trend_changes={
                    "pyramid_min_profit_atr": 1.5,
                    "pyramid_risk_scale": 0.28,
                    "pyramid_min_adx": 18.0,
                },
                alpha_changes={},
            ),
        ],
        [
            Candidate(
                stage="combined_bc",
                name="bc_moderate",
                note="Combine a moderate trend-entry filter with more selective pyramiding on the trend sleeve.",
                trend_changes={
                    "trend_min_ema_spread_atr": 0.13,
                    "trend_entry_buffer_atr": 0.02,
                    "entry_confirm_bars": 2,
                    "pyramid_min_profit_atr": 1.4,
                    "pyramid_risk_scale": 0.34,
                    "pyramid_min_adx": 18.0,
                },
                alpha_changes={},
            ),
            Candidate(
                stage="combined_bc",
                name="bc_strict",
                note="Combine the stricter trend filter with strict pyramiding limits on the trend sleeve.",
                trend_changes={
                    "trend_min_ema_spread_atr": 0.15,
                    "trend_entry_buffer_atr": 0.02,
                    "entry_confirm_bars": 2,
                    "pyramid_min_profit_atr": 1.5,
                    "pyramid_risk_scale": 0.28,
                    "pyramid_min_adx": 18.0,
                },
                alpha_changes={},
            ),
        ],
    ]


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    current_trend_changes: dict[str, float | int | bool] = {}
    current_alpha_changes: dict[str, float | int | bool] = {}
    rows: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []

    baseline_result = run_combo(current_trend_changes, current_alpha_changes)
    current_summary = summarize(
        label="baseline",
        stage="baseline",
        note="Current adopted combo.",
        trend_changes=current_trend_changes,
        alpha_changes=current_alpha_changes,
        result=baseline_result,
    )
    rows.append(current_summary)

    for candidates in stage_candidates():
        stage_name = candidates[0].stage
        stage_best: dict[str, object] | None = None

        for candidate in candidates:
            trend_changes = dict(current_trend_changes)
            alpha_changes = dict(current_alpha_changes)
            trend_changes.update(candidate.trend_changes)
            alpha_changes.update(candidate.alpha_changes)

            result = run_combo(trend_changes, alpha_changes)
            summary = summarize(
                label=candidate.name,
                stage=candidate.stage,
                note=candidate.note,
                trend_changes=trend_changes,
                alpha_changes=alpha_changes,
                result=result,
            )
            rows.append(summary)
            accepted, reason = accepts(current_summary, summary)
            summary["accepted_vs_current"] = accepted
            summary["decision_reason"] = reason
            if accepted and (stage_best is None or float(summary["market_score"]) > float(stage_best["market_score"])):
                stage_best = summary

        if stage_best is None:
            decisions.append(
                {
                    "stage": stage_name,
                    "accepted": False,
                    "candidate": None,
                    "reason": "no candidate cleared acceptance guardrails",
                }
            )
            continue

        current_trend_changes = json.loads(str(stage_best["trend_changes"]))
        current_alpha_changes = json.loads(str(stage_best["alpha_changes"]))
        current_summary = dict(stage_best)
        decisions.append(
            {
                "stage": stage_name,
                "accepted": True,
                "candidate": stage_best["candidate"],
                "reason": stage_best["decision_reason"],
            }
        )

    rows_df = pd.DataFrame(rows)
    rows_df.to_csv(OUTDIR / "stage_candidates.csv", index=False)

    payload = {
        "baseline": current_summary if current_summary["stage"] == "baseline" else rows[0],
        "final_accepted": current_summary,
        "decisions": decisions,
        "rows": rows,
    }
    (OUTDIR / "decision.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("===== ITERATE ADOPTED IMPROVEMENTS =====")
    print("candidate_rows :", len(rows))
    print("results_csv    :", OUTDIR / "stage_candidates.csv")
    print("decision_json  :", OUTDIR / "decision.json")
    print("baseline_score :", f"{rows[0]['market_score']:.6f}")
    print("final_score    :", f"{current_summary['market_score']:.6f}")
    print("final_candidate:", current_summary["candidate"])
    print("final_equity   :", f"{current_summary['final_equity']:.2f}")
    print("max_drawdown   :", f"{current_summary['max_drawdown']:.6f}")
    for year in YEARS:
        print(f"return_{year}    : {current_summary[f'y{year}']:.6f}")
    print("trend_changes  :", current_summary["trend_changes"])
    print("alpha_changes  :", current_summary["alpha_changes"])
    print("decisions      :", json.dumps(decisions, ensure_ascii=True))


if __name__ == "__main__":
    main()
