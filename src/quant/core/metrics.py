from __future__ import annotations

import math
import numpy as np
import pandas as pd


def bars_per_year(interval: str) -> float:
    if interval.endswith("h"):
        h = int(interval[:-1])
        return (24 / h) * 365
    if interval.endswith("m"):
        m = int(interval[:-1])
        return (60 / m) * 24 * 365
    return 365.0


def build_benchmark_equity_curve(
    index,
    benchmark_close: pd.Series,
    initial_equity: float,
) -> pd.DataFrame:
    if benchmark_close is None:
        return pd.DataFrame(columns=["equity", "drawdown"])

    idx = pd.DatetimeIndex(pd.to_datetime(index, utc=True))
    if len(idx) == 0:
        return pd.DataFrame(columns=["equity", "drawdown"])

    close = pd.Series(benchmark_close).copy()
    close.index = pd.to_datetime(close.index, utc=True)
    close = pd.to_numeric(close, errors="coerce")
    aligned = close.reindex(idx).ffill().bfill()
    aligned = aligned.dropna()
    if aligned.empty:
        return pd.DataFrame(columns=["equity", "drawdown"])

    first = float(aligned.iloc[0])
    if not np.isfinite(first) or abs(first) <= 1e-12:
        return pd.DataFrame(columns=["equity", "drawdown"])

    equity = float(initial_equity) * aligned / first
    out = pd.DataFrame(index=aligned.index)
    out["equity"] = equity.astype(float)
    peak = out["equity"].cummax()
    out["drawdown"] = out["equity"] / peak - 1.0
    return out


def compute_metrics(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    initial_equity: float,
    interval: str,
    benchmark_curve: pd.DataFrame | None = None,
) -> dict:
    if equity_curve is None or equity_curve.empty:
        return {
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "num_round_trades": 0,
            "winrate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "funding_pnl": 0.0,
            "final_equity": float(initial_equity),
        }

    ret = equity_curve["equity"].pct_change().fillna(0.0)
    total_return = float(equity_curve["equity"].iloc[-1] / float(initial_equity) - 1.0)
    max_dd = float(equity_curve["drawdown"].min()) if "drawdown" in equity_curve.columns else 0.0

    bpy = bars_per_year(interval)
    sharpe = float((ret.mean() / (ret.std() + 1e-12)) * math.sqrt(bpy))

    if trades is None or trades.empty:
        realized = pd.DataFrame()
    else:
        realized = trades[
            (trades["type"].isin(["STOP_LONG", "STOP_SHORT", "CLOSE_BY_SIGNAL", "FLIP_CLOSE", "EXIT"]))
            & trades["exit"].notna()
        ].copy()

    wins = int((realized["pnl"] > 0).sum()) if not realized.empty else 0
    losses = int((realized["pnl"] <= 0).sum()) if not realized.empty else 0
    winrate = wins / max(1, (wins + losses))
    avg_win = float(realized.loc[realized["pnl"] > 0, "pnl"].mean()) if wins else 0.0
    avg_loss = float(realized.loc[realized["pnl"] <= 0, "pnl"].mean()) if losses else 0.0

    funding_pnl = float(trades.loc[trades["type"] == "FUNDING", "pnl"].sum()) if trades is not None and not trades.empty else 0.0

    metrics = {
        "total_return": total_return,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "num_round_trades": int(wins + losses),
        "winrate": float(winrate),
        "avg_win": float(avg_win) if not np.isnan(avg_win) else 0.0,
        "avg_loss": float(avg_loss) if not np.isnan(avg_loss) else 0.0,
        "funding_pnl": float(funding_pnl),
        "final_equity": float(equity_curve["equity"].iloc[-1]),
    }

    if benchmark_curve is not None and not benchmark_curve.empty and "equity" in benchmark_curve.columns:
        strat_eq = equity_curve[["equity"]].copy()
        bench_eq = benchmark_curve[["equity"]].copy()
        strat_eq.index = pd.to_datetime(strat_eq.index, utc=True)
        bench_eq.index = pd.to_datetime(bench_eq.index, utc=True)

        idx = strat_eq.index.intersection(bench_eq.index)
        if len(idx) >= 2:
            strat_aligned = strat_eq.loc[idx, "equity"].astype(float)
            bench_aligned = bench_eq.loc[idx, "equity"].astype(float)
            benchmark_total_return = float(bench_aligned.iloc[-1] / max(float(bench_aligned.iloc[0]), 1e-12) - 1.0)
            bench_peak = bench_aligned.cummax()
            benchmark_max_drawdown = float((bench_aligned / bench_peak - 1.0).min())
            strat_ret = strat_aligned.pct_change().fillna(0.0)
            bench_ret = bench_aligned.pct_change().fillna(0.0)
            active_ret = strat_ret - bench_ret

            info_ratio = float((active_ret.mean() / (active_ret.std() + 1e-12)) * math.sqrt(bpy))
            bench_var = float(bench_ret.var())
            if bench_var > 1e-12:
                beta = float(strat_ret.cov(bench_ret) / bench_var)
                alpha_per_bar = float(strat_ret.mean() - beta * bench_ret.mean())
                alpha_annualized = float(alpha_per_bar * bpy)
            else:
                beta = 0.0
                alpha_annualized = 0.0

            metrics.update(
                {
                    "benchmark_total_return": benchmark_total_return,
                    "benchmark_max_drawdown": benchmark_max_drawdown,
                    "benchmark_final_equity": float(bench_aligned.iloc[-1]),
                    "excess_return": float(total_return - benchmark_total_return),
                    "excess_final_equity": float(metrics["final_equity"] - bench_aligned.iloc[-1]),
                    "information_ratio": info_ratio,
                    "beta": beta,
                    "alpha_annualized": alpha_annualized,
                }
            )

    return metrics
