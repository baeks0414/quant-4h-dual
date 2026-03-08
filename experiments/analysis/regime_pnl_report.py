# experiments/regime_pnl_report.py
from __future__ import annotations

import sys
import argparse
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

# --- 프로젝트 루트 경로 추가 ---
ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src"))

from quant.config.presets import preset_regime_only_live
from quant.data.binance_fetch import fetch_klines, interval_to_ms
from quant.data.features import add_features


# -----------------------------
# helpers: file pick / read
# -----------------------------
def _pick_result_files(result_dir: Path, tag_contains: Optional[str], prefer_backtest: bool) -> Tuple[Path, Path]:
    trades = sorted(result_dir.glob("trades_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    equity = sorted(result_dir.glob("equity_curve_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)

    if tag_contains:
        trades = [p for p in trades if tag_contains in p.name]
        equity = [p for p in equity if tag_contains in p.name]

    if prefer_backtest:
        trades_bt = [p for p in trades if "LIVE" not in p.name.upper()]
        equity_bt = [p for p in equity if "LIVE" not in p.name.upper()]
        if trades_bt and equity_bt:
            trades, equity = trades_bt, equity_bt

    if not trades:
        raise FileNotFoundError(f"No matching trades_*.csv found in {result_dir} (tag={tag_contains})")
    if not equity:
        raise FileNotFoundError(f"No matching equity_curve_*.csv found in {result_dir} (tag={tag_contains})")

    return trades[0], equity[0]


def _read_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return df

    if "time" not in df.columns:
        raise ValueError(f"'time' column not found in trades file: {path}")

    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time")

    if "pnl" not in df.columns:
        df["pnl"] = 0.0
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    return df


def _read_equity_curve(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return df

    # case A: 'time' 컬럼이 있는 경우
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        df = df.dropna(subset=["time"]).set_index("time").sort_index()
        return df

    # case B: 첫 컬럼이 time index로 저장된 경우
    first_col = df.columns[0]
    df[first_col] = pd.to_datetime(df[first_col], utc=True, errors="coerce")
    df = df.dropna(subset=[first_col]).set_index(first_col).sort_index()
    df.index.name = "time"
    return df


def _bars_per_year(interval: str) -> float:
    if interval.endswith("h"):
        h = int(interval[:-1])
        return (24 / h) * 365
    if interval.endswith("m"):
        m = int(interval[:-1])
        return (60 / m) * 24 * 365
    if interval.endswith("d"):
        d = int(interval[:-1])
        return (365 / d)
    return 365.0


# -----------------------------
# warmup fetch
# -----------------------------
def _compute_warmup_bars(cfg) -> int:
    windows = [
        int(getattr(cfg, "ema_slow", 45)) * 3,
        int(getattr(cfg, "donchian_window", 30)) + 50,
        30 * 6,
        300,
    ]
    return max(windows)


def _fetch_regime_series(
    cfg,
    symbol: str,
    interval: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.Series:
    warmup_bars = _compute_warmup_bars(cfg)
    start_warm = start - pd.Timedelta(milliseconds=interval_to_ms(interval) * warmup_bars)

    df = fetch_klines(
        symbol,
        interval,
        int(start_warm.timestamp() * 1000),
        int(end.timestamp() * 1000),
    )
    df_feat = add_features(df, cfg)
    if df_feat.empty:
        return pd.Series(dtype=str)

    # regime series (UTC index)
    reg = df_feat["regime"].astype(str)
    return reg


def _align_regime_to_index(regime: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    """
    equity_curve index에 regime을 붙입니다.
    보통 backtest는 정확히 같은 timestamp라 바로 매칭되지만,
    혹시 오차가 있으면 nearest로 붙입니다.
    """
    if regime.empty or idx.empty:
        return pd.Series(index=idx, dtype=str)

    # exact join 우선
    out = regime.reindex(idx)
    if out.notna().sum() >= max(1, int(len(idx) * 0.8)):
        return out

    # fallback: nearest
    r = regime.sort_index()
    pos = r.index.get_indexer(idx, method="nearest")
    pos = np.clip(pos, 0, len(r.index) - 1)
    out2 = pd.Series(r.values[pos], index=idx)
    return out2


# -----------------------------
# stats
# -----------------------------
def _bar_regime_stats(ec: pd.DataFrame, interval: str) -> pd.DataFrame:
    """
    ec columns: equity, regime (required)
    """
    df = ec.copy()
    df["equity"] = pd.to_numeric(df["equity"], errors="coerce")
    df = df.dropna(subset=["equity"])
    df["ret"] = df["equity"].pct_change().fillna(0.0)
    df["pnl_bar"] = df["equity"].diff().fillna(0.0)

    bpy = _bars_per_year(interval)

    def agg(g: pd.DataFrame) -> pd.Series:
        bars = len(g)
        total_pnl = float(g["pnl_bar"].sum())
        avg_pnl = float(g["pnl_bar"].mean())
        avg_ret = float(g["ret"].mean())
        vol_ret = float(g["ret"].std(ddof=0))
        sharpe = float((avg_ret / (vol_ret + 1e-12)) * np.sqrt(bpy)) if bars > 2 else 0.0
        win_bar = float((g["pnl_bar"] > 0).mean()) if bars else 0.0
        return pd.Series(
            {
                "bars": bars,
                "pct_bars": bars / max(1, len(df)),
                "total_pnl": total_pnl,
                "avg_pnl_per_bar": avg_pnl,
                "avg_ret_per_bar": avg_ret,
                "vol_ret_per_bar": vol_ret,
                "sharpe_like": sharpe,
                "winrate_bar": win_bar,
            }
        )

    out = df.groupby(df["regime"].astype(str), dropna=False).apply(agg)
    out = out.sort_values("total_pnl", ascending=False)
    return out


def _trade_regime_stats(trades: pd.DataFrame, regime_on_time: pd.Series) -> pd.DataFrame:
    """
    trades: 전체 trades csv
    regime_on_time: index=time, value=regime (equity index aligned 권장)
    기준: 실현손익(거래 pnl != 0) 이벤트에 대해, 그 이벤트 time에 해당하는 regime로 그룹
    """
    if trades is None or trades.empty:
        return pd.DataFrame()

    realized_types = {"EXIT", "STOP_LONG", "STOP_SHORT", "CLOSE_BY_SIGNAL", "FLIP_CLOSE", "EXIT_BY_SIGNAL"}
    r = trades[trades["type"].astype(str).isin(realized_types)].copy()
    if r.empty:
        return pd.DataFrame()

    # regime 매핑 (nearest)
    idx = regime_on_time.index
    if idx.empty:
        r["regime"] = "UNKNOWN"
    else:
        # nearest mapping via indexer
        pos = idx.get_indexer(r["time"], method="nearest")
        pos = np.clip(pos, 0, len(idx) - 1)
        r["regime"] = regime_on_time.values[pos]

    r["pnl"] = pd.to_numeric(r["pnl"], errors="coerce").fillna(0.0)

    def agg(g: pd.DataFrame) -> pd.Series:
        n = len(g)
        total = float(g["pnl"].sum())
        wins = int((g["pnl"] > 0).sum())
        losses = int((g["pnl"] <= 0).sum())
        winrate = wins / max(1, (wins + losses))
        avg = float(g["pnl"].mean()) if n else 0.0

        gross_profit = float(g.loc[g["pnl"] > 0, "pnl"].sum())
        gross_loss = float(-g.loc[g["pnl"] < 0, "pnl"].sum())
        pf = (gross_profit / gross_loss) if gross_loss > 1e-12 else np.inf if gross_profit > 0 else 0.0

        return pd.Series(
            {
                "num_trades": n,
                "total_pnl": total,
                "avg_pnl": avg,
                "winrate": float(winrate),
                "gross_profit": gross_profit,
                "gross_loss": -gross_loss,
                "profit_factor": float(pf),
            }
        )

    out = r.groupby(r["regime"].astype(str), dropna=False).apply(agg)
    out = out.sort_values("total_pnl", ascending=False)
    return out


def _pretty_print_df(title: str, df: pd.DataFrame, float_cols: Optional[list[str]] = None) -> None:
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)
    if df is None or df.empty:
        print("(empty)")
        return

    d = df.copy()
    float_cols = float_cols or []
    for c in float_cols:
        if c in d.columns:
            d[c] = d[c].astype(float)

    # 보기 좋게 포맷
    with pd.option_context(
        "display.max_rows", 200,
        "display.max_columns", 200,
        "display.width", 140,
        "display.float_format", lambda x: f"{x:,.6f}",
    ):
        print(d)


def main():
    p = argparse.ArgumentParser("regime-pnl-report")
    p.add_argument("--result_dir", default="results/final/result_verify_dynamic_params_v2")
    p.add_argument("--tag", default=None, help="특정 tag 포함 파일만 선택")
    p.add_argument("--include_live", action="store_true", help="LIVE 파일도 선택 대상으로 포함")

    p.add_argument("--interval", default="4h")
    p.add_argument("--market_symbol", default="BTCUSDT")

    # 기간 지정(원하면 강제)
    p.add_argument("--start", default=None, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", default=None, help="YYYY-MM-DD (UTC)")

    p.add_argument("--save_csv", action="store_true", help="result_dir에 regime 통계 csv 저장")
    args = p.parse_args()

    result_path = ROOT / args.result_dir
    trades_path, equity_path = _pick_result_files(
        result_dir=result_path,
        tag_contains=args.tag,
        prefer_backtest=(not args.include_live),
    )

    print(f"[INFO] Using trades: {trades_path.name}")
    print(f"[INFO] Using equity:  {equity_path.name}")

    trades = _read_trades(trades_path)
    equity = _read_equity_curve(equity_path)

    if equity.empty or "equity" not in equity.columns:
        raise ValueError("equity_curve must have 'equity' column.")

    # 기간 결정
    if args.start and args.end:
        start = pd.Timestamp(args.start, tz="UTC")
        end = pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    else:
        start = equity.index.min()
        end = equity.index.max()

    # 레짐 시계열 계산/정렬
    cfg = preset_regime_only_live()
    cfg.interval = args.interval

    print(f"[INFO] Regime source: {args.market_symbol} interval={args.interval}")
    print(f"[INFO] Window: {start} .. {end}")

    regime_raw = _fetch_regime_series(cfg, args.market_symbol, args.interval, start, end)
    regime_aligned = _align_regime_to_index(regime_raw, equity.loc[(equity.index >= start) & (equity.index <= end)].index)

    ec = equity.loc[(equity.index >= start) & (equity.index <= end)].copy()
    ec["regime"] = regime_aligned.astype(str).fillna("UNKNOWN")

    # 1) Bar-based stats
    bar_stats = _bar_regime_stats(ec, args.interval)

    # 2) Trade-based stats (realized pnl)
    trade_stats = _trade_regime_stats(trades, ec["regime"])

    _pretty_print_df(
        "BAR-BASED REGIME PnL STATS (equity diff attributed to regime)",
        bar_stats,
        float_cols=["pct_bars", "total_pnl", "avg_pnl_per_bar", "avg_ret_per_bar", "vol_ret_per_bar", "sharpe_like", "winrate_bar"],
    )

    _pretty_print_df(
        "TRADE-BASED REGIME STATS (realized trades grouped by regime-at-exit)",
        trade_stats,
        float_cols=["total_pnl", "avg_pnl", "winrate", "gross_profit", "gross_loss", "profit_factor"],
    )

    # 저장 옵션
    if args.save_csv:
        tag = args.tag or "LATEST"
        out1 = result_path / f"regime_bar_stats_{tag}.csv"
        out2 = result_path / f"regime_trade_stats_{tag}.csv"
        bar_stats.to_csv(out1)
        trade_stats.to_csv(out2)
        print("\n[INFO] saved:")
        print(" -", out1)
        print(" -", out2)


if __name__ == "__main__":
    main()
