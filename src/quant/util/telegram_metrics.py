from __future__ import annotations

from typing import Any

import pandas as pd

ENTRY_TYPES = {"ENTRY_LONG", "ENTRY_SHORT", "PYRAMID_LONG", "PYRAMID_SHORT"}
EXIT_TYPES = {"EXIT", "STOP_LONG", "STOP_SHORT", "CLOSE_BY_SIGNAL", "FLIP_CLOSE"}
IGNORED_TYPES = {"FUNDING"}


def parse_utc_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        try:
            return ts.tz_localize("UTC")
        except Exception:
            return None
    try:
        return ts.tz_convert("UTC")
    except Exception:
        return None


def format_duration(delta: pd.Timedelta) -> str | None:
    if delta is None or pd.isna(delta):
        return None
    total_seconds = max(int(delta.total_seconds()), 0)
    days, rem = divmod(total_seconds, 86_400)
    hours, rem = divmod(rem, 3_600)
    minutes, _ = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def format_duration_between(start: Any, end: Any) -> str | None:
    start_ts = parse_utc_timestamp(start)
    end_ts = parse_utc_timestamp(end)
    if start_ts is None or end_ts is None:
        return None
    return format_duration(end_ts - start_ts)


def _normalize_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()
    if "time" not in trades.columns or "type" not in trades.columns:
        return pd.DataFrame()

    df = trades.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    if "symbol" not in df.columns:
        df["symbol"] = ""
    if "strategy" not in df.columns:
        df["strategy"] = ""
    df = df.dropna(subset=["time"])
    if df.empty:
        return pd.DataFrame()
    return df.sort_values("time").reset_index(drop=True)


def find_trade_hold_duration(
    trade_row: pd.Series | dict[str, Any],
    trades: pd.DataFrame,
    reference_time: Any | None = None,
) -> str | None:
    trade_type = str(trade_row.get("type", ""))
    trade_time = parse_utc_timestamp(trade_row.get("time"))
    if trade_time is None:
        return None

    if trade_type in ENTRY_TYPES:
        end_ts = parse_utc_timestamp(reference_time) or trade_time
        return format_duration(end_ts - trade_time)

    if trade_type not in EXIT_TYPES:
        return None

    symbol = str(trade_row.get("symbol", ""))
    strategy = str(trade_row.get("strategy", ""))
    if not symbol:
        return None

    history = _normalize_trades(trades)
    if history.empty:
        return None

    scoped = history[history["time"].le(trade_time) & history["symbol"].eq(symbol)]
    if strategy:
        scoped = scoped[scoped["strategy"].eq(strategy)]
    if scoped.empty:
        return None

    entry_time: pd.Timestamp | None = None
    for _, row in scoped.iterrows():
        row_type = str(row.get("type", ""))
        if row_type in ENTRY_TYPES:
            if entry_time is None or row_type.startswith("ENTRY_"):
                entry_time = row["time"]
        elif row_type in EXIT_TYPES:
            if row["time"] == trade_time and entry_time is not None:
                return format_duration(trade_time - entry_time)
            entry_time = None
    return None


def build_recent_trade_hold_text(trades: pd.DataFrame, reference_time: Any) -> str | None:
    history = _normalize_trades(trades)
    if history.empty:
        return None

    recent = history[~history["type"].isin(IGNORED_TYPES)]
    if recent.empty:
        return None

    row = recent.iloc[-1]
    duration = find_trade_hold_duration(row, history, reference_time=reference_time)
    if not duration:
        return None

    symbol = str(row.get("symbol", "")).replace("USDT", "") or "?"
    trade_type = str(row.get("type", ""))
    if trade_type in ENTRY_TYPES:
        return f"{symbol} {trade_type} {duration} 진행중"
    return f"{symbol} {trade_type} {duration}"
