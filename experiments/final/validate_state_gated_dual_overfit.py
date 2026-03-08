#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Iterable

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


DATE_TAG = "20260307"
OUTDIR = ROOT / "results" / "final" / f"result_validate_state_gated_dual_overfit_{DATE_TAG}"
OUT_JSON = ROOT / "research" / "data" / f"state_gated_dual_overfit_{DATE_TAG}.json"
OUT_MD = ROOT / "research" / "archive" / f"STATE_GATED_DUAL_OVERFIT_{DATE_TAG}.md"

INITIAL_EQUITY = 10_000.0
FINAL_WEIGHT = 0.30

TARGETS = {
    "final_equity": 90_000.0,
    "max_drawdown": -0.20,
    "y2022": 0.05,
    "y2024": 1.00,
    "y2025": 0.10,
}


@dataclass(frozen=True)
class DualSpec:
    trend_risk: float = 1.50
    sleeve_risk: float = 0.023
    sleeve_weight: float = 0.30
    adx_min: float = 30.0
    adx_max: float = 35.0
    spread_min: float = 0.30
    streak_min: int = 4
    streak_max: int = 7

    def label(self) -> str:
        return (
            f"tr{self.trend_risk:.2f}_sr{self.sleeve_risk:.3f}_w{self.sleeve_weight:.2f}"
            f"_adx{self.adx_min:.0f}-{self.adx_max:.0f}_sp{self.spread_min:.2f}"
            f"_st{self.streak_min}-{self.streak_max}"
        )


def yearly_returns(ec: pd.DataFrame) -> dict[int, float]:
    view = ec.copy()
    view.index = pd.to_datetime(view.index, utc=True)
    out: dict[int, float] = {}
    for year in (2022, 2023, 2024, 2025):
        sample = view[view.index.year == year]
        if not sample.empty:
            out[year] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def meets_targets(metrics: dict[str, float], yearly: dict[int, float]) -> bool:
    return (
        float(metrics["final_equity"]) > TARGETS["final_equity"]
        and float(metrics["max_drawdown"]) > TARGETS["max_drawdown"]
        and float(yearly.get(2022, -1.0)) > TARGETS["y2022"]
        and float(yearly.get(2024, -1.0)) > TARGETS["y2024"]
        and float(yearly.get(2025, -1.0)) > TARGETS["y2025"]
    )


def train_score(metrics: dict[str, float]) -> float:
    excess = float(metrics.get("excess_return", metrics["total_return"]))
    info = float(metrics.get("information_ratio", 0.0))
    alpha = float(metrics.get("alpha_annualized", 0.0))
    mdd = float(metrics["max_drawdown"])
    penalty = 12.0 * max(0.0, abs(mdd) - 0.20)
    # Market-relative selection:
    # 1) excess return vs BTC buy-and-hold
    # 2) consistency of active returns (information ratio)
    # 3) annualized alpha
    return math.log1p(max(excess, -0.99)) + 0.35 * info + 0.15 * alpha - penalty


@contextlib.contextmanager
def silence_stdout() -> Iterable[None]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield


def run_dual_spec(
    spec: DualSpec,
    *,
    start: str = "2022-01-01",
    end: str = "2025-04-12",
    fee_mult: float = 1.0,
    slippage_mult: float = 1.0,
) -> dict[str, object]:
    trend_weight = 1.0 - spec.sleeve_weight

    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.start = start
    trend_cfg.end = end
    trend_cfg.initial_equity = INITIAL_EQUITY * trend_weight
    trend_cfg.risk_scale_bear_trend = spec.trend_risk
    trend_cfg.state_gate_min_market_adx = spec.adx_min
    trend_cfg.state_gate_max_market_adx = spec.adx_max
    trend_cfg.state_gate_min_market_ema_spread_atr = spec.spread_min
    trend_cfg.state_gate_min_market_regime_streak = spec.streak_min
    trend_cfg.state_gate_max_market_regime_streak = spec.streak_max
    trend_cfg.fee_rate *= fee_mult
    trend_cfg.slippage *= slippage_mult

    sleeve_cfg = preset_balanced_alpha_sleeve_aggressive()
    sleeve_cfg.start = start
    sleeve_cfg.end = end
    sleeve_cfg.initial_equity = INITIAL_EQUITY * spec.sleeve_weight
    sleeve_cfg.risk_per_trade = spec.sleeve_risk
    sleeve_cfg.portfolio_risk_cap = max(0.08, spec.sleeve_risk * 4.0)
    sleeve_cfg.fee_rate *= fee_mult
    sleeve_cfg.slippage *= slippage_mult

    with silence_stdout():
        trend = run_backtest(trend_cfg, outdir=str(OUTDIR / "tmp_trend"))
    with silence_stdout():
        sleeve = run_backtest(sleeve_cfg, outdir=str(OUTDIR / "tmp_sleeve"))

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

    benchmark_curve = trend["benchmark_equity_curve"][["equity"]].copy()
    benchmark_curve.index = pd.to_datetime(benchmark_curve.index, utc=True)
    benchmark_curve["equity"] = benchmark_curve["equity"] / trend_cfg.initial_equity * INITIAL_EQUITY
    benchmark_curve = benchmark_curve.loc[idx]
    benchmark_peak = benchmark_curve["equity"].cummax()
    benchmark_curve["drawdown"] = benchmark_curve["equity"] / benchmark_peak - 1.0

    metrics = compute_metrics(combined, trades, INITIAL_EQUITY, "4h", benchmark_curve=benchmark_curve)
    yearly = yearly_returns(combined)

    return {
        "spec": spec,
        "metrics": metrics,
        "yearly": yearly,
    }


def tabulate_result(name: str, result: dict[str, object]) -> dict[str, object]:
    metrics = result["metrics"]
    yearly = result["yearly"]
    spec = result["spec"]
    return {
        "name": name,
        "label": spec.label(),
        "trend_risk": spec.trend_risk,
        "sleeve_risk": spec.sleeve_risk,
        "sleeve_weight": spec.sleeve_weight,
        "adx_min": spec.adx_min,
        "adx_max": spec.adx_max,
        "spread_min": spec.spread_min,
        "streak_min": spec.streak_min,
        "streak_max": spec.streak_max,
        "total_return": float(metrics["total_return"]),
        "benchmark_total_return": float(metrics.get("benchmark_total_return", float("nan"))),
        "excess_return": float(metrics.get("excess_return", float("nan"))),
        "information_ratio": float(metrics.get("information_ratio", float("nan"))),
        "alpha_annualized": float(metrics.get("alpha_annualized", float("nan"))),
        "beta": float(metrics.get("beta", float("nan"))),
        "max_drawdown": float(metrics["max_drawdown"]),
        "sharpe": float(metrics["sharpe"]),
        "final_equity": float(metrics["final_equity"]),
        "market_score": float(train_score(metrics)),
        "y2022": float(yearly.get(2022, float("nan"))),
        "y2023": float(yearly.get(2023, float("nan"))),
        "y2024": float(yearly.get(2024, float("nan"))),
        "y2025": float(yearly.get(2025, float("nan"))),
        "target_hit": meets_targets(metrics, yearly),
    }


def run_local_surface() -> pd.DataFrame:
    rows = []
    for trend_risk, sleeve_risk, sleeve_weight in product(
        (1.25, 1.50, 1.75),
        (0.017, 0.020, 0.023),
        (0.25, 0.27, 0.30),
    ):
        spec = DualSpec(
            trend_risk=trend_risk,
            sleeve_risk=sleeve_risk,
            sleeve_weight=sleeve_weight,
        )
        rows.append(tabulate_result("local_surface", run_dual_spec(spec)))
    return pd.DataFrame(rows)


def run_gate_surface() -> pd.DataFrame:
    rows = []
    for adx_min, spread_min, streak_min in product(
        (29.0, 30.0, 31.0),
        (0.25, 0.30, 0.35),
        (3, 4, 5),
    ):
        spec = DualSpec(
            adx_min=adx_min,
            spread_min=spread_min,
            streak_min=streak_min,
            streak_max=7,
        )
        rows.append(tabulate_result("gate_surface", run_dual_spec(spec)))
    return pd.DataFrame(rows)


def run_cost_stress(final_spec: DualSpec) -> pd.DataFrame:
    rows = []
    for fee_mult, slip_mult in ((1.0, 1.0), (1.25, 1.25), (1.50, 1.50), (2.0, 2.0)):
        rec = tabulate_result(
            f"cost_f{fee_mult:.2f}_s{slip_mult:.2f}",
            run_dual_spec(final_spec, fee_mult=fee_mult, slippage_mult=slip_mult),
        )
        rec["fee_mult"] = fee_mult
        rec["slippage_mult"] = slip_mult
        rows.append(rec)
    return pd.DataFrame(rows)


def candidate_family() -> list[DualSpec]:
    out = []
    for trend_risk, sleeve_risk, sleeve_weight, spread_min, streak_min, adx_min in product(
        (1.25, 1.50),
        (0.017, 0.020),
        (0.27, 0.30),
        (0.25, 0.30),
        (3, 4),
        (29.0, 30.0),
    ):
        out.append(
            DualSpec(
                trend_risk=trend_risk,
                sleeve_risk=sleeve_risk,
                sleeve_weight=sleeve_weight,
                adx_min=adx_min,
                adx_max=35.0,
                spread_min=spread_min,
                streak_min=streak_min,
                streak_max=7,
            )
        )
    return out


def run_walk_forward() -> pd.DataFrame:
    splits = [
        ("wf_2024", "2022-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
        ("wf_2025", "2022-01-01", "2024-12-31", "2025-01-01", "2025-04-12"),
    ]
    rows = []
    family = candidate_family()
    for split_name, train_start, train_end, test_start, test_end in splits:
        best_score = None
        best_spec = None
        best_train = None
        for spec in family:
            train = run_dual_spec(spec, start=train_start, end=train_end)
            score = train_score(train["metrics"])
            if best_score is None or score > best_score:
                best_score = score
                best_spec = spec
                best_train = train
        assert best_spec is not None and best_train is not None
        test = run_dual_spec(best_spec, start=test_start, end=test_end)
        train_row = tabulate_result(f"{split_name}_train", best_train)
        train_row["selection_score"] = float(best_score)
        train_row["selected"] = True
        rows.append(train_row)
        test_row = tabulate_result(f"{split_name}_test", test)
        test_row["selection_score"] = float(best_score)
        test_row["selected"] = True
        rows.append(test_row)
    return pd.DataFrame(rows)


def summarize_surface(df: pd.DataFrame) -> dict[str, float]:
    return {
        "count": int(len(df)),
        "target_hit_ratio": float(df["target_hit"].mean()),
        "median_return": float(df["total_return"].median()),
        "median_excess_return": float(df["excess_return"].median()),
        "median_information_ratio": float(df["information_ratio"].median()),
        "median_mdd": float(df["max_drawdown"].median()),
        "best_return": float(df["total_return"].max()),
        "best_excess_return": float(df["excess_return"].max()),
        "best_information_ratio": float(df["information_ratio"].max()),
        "best_market_score": float(df["market_score"].max()),
        "worst_return": float(df["total_return"].min()),
        "worst_excess_return": float(df["excess_return"].min()),
        "best_y2022": float(df["y2022"].max()),
        "worst_y2022": float(df["y2022"].min()),
        "best_y2025": float(df["y2025"].max()),
        "worst_y2025": float(df["y2025"].min()),
    }


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    final_spec = DualSpec()
    final_result = run_dual_spec(final_spec)
    final_row = tabulate_result("final_candidate", final_result)

    local_df = run_local_surface()
    gate_df = run_gate_surface()
    cost_df = run_cost_stress(final_spec)
    wf_df = run_walk_forward()

    payload = {
        "selection_objective": "market_relative_v1",
        "final_candidate": final_row,
        "local_surface_summary": summarize_surface(local_df),
        "gate_surface_summary": summarize_surface(gate_df),
        "cost_stress": cost_df.to_dict(orient="records"),
        "walk_forward": wf_df.to_dict(orient="records"),
        "local_surface_rows": local_df.to_dict(orient="records"),
        "gate_surface_rows": gate_df.to_dict(orient="records"),
        "final_spec": asdict(final_spec),
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    lines = []
    lines.append(f"# State-Gated Dual Overfit Validation ({DATE_TAG})")
    lines.append("")
    lines.append("Selection objective: market_relative_v1")
    lines.append("- score = log1p(excess_return) + 0.35 * information_ratio + 0.15 * alpha_annualized - drawdown_penalty")
    lines.append("- benchmark = BTC buy-and-hold")
    lines.append("")
    lines.append("## Final Candidate")
    for key in (
        "total_return",
        "benchmark_total_return",
        "excess_return",
        "information_ratio",
        "alpha_annualized",
        "beta",
        "market_score",
        "max_drawdown",
        "sharpe",
        "final_equity",
        "y2022",
        "y2024",
        "y2025",
    ):
        lines.append(f"- {key}: {final_row[key]:.6f}")
    lines.append(f"- target_hit: {final_row['target_hit']}")
    lines.append("")
    lines.append("## Local Surface Summary")
    for k, v in summarize_surface(local_df).items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Gate Surface Summary")
    for k, v in summarize_surface(gate_df).items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Cost Stress")
    lines.append("```text")
    lines.append(cost_df.to_string(index=False))
    lines.append("```")
    lines.append("")
    lines.append("## Walk Forward")
    lines.append("```text")
    lines.append(wf_df.to_string(index=False))
    lines.append("```")
    lines.append("")
    lines.append("## Local Surface Top 10")
    lines.append("```text")
    lines.append(
        local_df.sort_values(["target_hit", "market_score", "excess_return"], ascending=[False, False, False])
        .head(10)
        .to_string(index=False)
    )
    lines.append("```")
    lines.append("")
    lines.append("## Gate Surface Top 10")
    lines.append("```text")
    lines.append(
        gate_df.sort_values(["target_hit", "market_score", "excess_return"], ascending=[False, False, False])
        .head(10)
        .to_string(index=False)
    )
    lines.append("```")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({
        "final_candidate": final_row,
        "local_surface_summary": summarize_surface(local_df),
        "gate_surface_summary": summarize_surface(gate_df),
    }, ensure_ascii=True))
    print(f"saved: {OUT_JSON}")
    print(f"saved: {OUT_MD}")


if __name__ == "__main__":
    main()
