from __future__ import annotations

import os
import time

import pandas as pd
import requests

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT_VISION = "https://data-api.binance.vision"

# Disk cache directory (override with QUANT_CACHE_DIR)
_CACHE_DIR = os.environ.get("QUANT_CACHE_DIR", os.path.expanduser("~/.quant_cache"))

# Process-level memory cache for repeated parameter sweeps.
_MEM_CACHE_ON = os.environ.get("QUANT_MEM_CACHE", "1").strip() != "0"
_KLINES_MEM_CACHE: dict[str, pd.DataFrame] = {}
_FUNDING_MEM_CACHE: dict[str, pd.DataFrame] = {}

# Throttle per REST call (tunable): set QUANT_BINANCE_SLEEP_S=0.02, for example.
_BINANCE_SLEEP_S = float(os.environ.get("QUANT_BINANCE_SLEEP_S", "0.05"))


def _cache_path(key: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{key}.parquet")


def interval_to_ms(interval: str) -> int:
    unit_ms = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    num = int(interval[:-1])
    unit = interval[-1]
    return num * unit_ms[unit]


def _get_json(url: str, params: dict, session: requests.Session, sleep_s: float = _BINANCE_SLEEP_S):
    r = session.get(url, params=params, timeout=15)
    r.raise_for_status()
    time.sleep(sleep_s)
    return r.json()


def fetch_klines(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    limit: int = 1000,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch Binance kline history.
    Cache key is (symbol, interval, start_ms, end_ms).
    """
    cache_key = f"klines_{symbol}_{interval}_{start_ms}_{end_ms}"
    if _MEM_CACHE_ON and cache_key in _KLINES_MEM_CACHE:
        return _KLINES_MEM_CACHE[cache_key]

    cpath = _cache_path(cache_key)
    if use_cache and os.path.exists(cpath):
        try:
            df = pd.read_parquet(cpath)
            if _MEM_CACHE_ON:
                _KLINES_MEM_CACHE[cache_key] = df
            return df
        except Exception:
            pass

    out = []
    cur = start_ms
    step = interval_to_ms(interval) * limit
    sess = requests.Session()

    def _try_fetch(cur_: int, end_: int):
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cur_,
            "endTime": min(end_, cur_ + step),
            "limit": limit,
        }
        try:
            r = sess.get(f"{BINANCE_FAPI}/fapi/v1/klines", params=params, timeout=15)
            if r.status_code == 200:
                time.sleep(_BINANCE_SLEEP_S)
                return r.json()
        except Exception:
            pass

        r2 = sess.get(f"{BINANCE_SPOT_VISION}/api/v3/klines", params=params, timeout=15)
        r2.raise_for_status()
        time.sleep(_BINANCE_SLEEP_S)
        return r2.json()

    while cur < end_ms:
        data = _try_fetch(cur, end_ms)
        if not data:
            break
        out.extend(data)
        last_open = int(data[-1][0])
        cur = last_open + interval_to_ms(interval)

    cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "qav",
        "num_trades",
        "tbbav",
        "tbqav",
        "ignore",
    ]
    df = pd.DataFrame(out, columns=cols)
    if df.empty:
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"]).set_index(
            pd.DatetimeIndex([], tz="UTC")
        )
        if _MEM_CACHE_ON:
            _KLINES_MEM_CACHE[cache_key] = df
        return df

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")

    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)

    df = df[["open", "high", "low", "close", "volume"]].sort_index().drop_duplicates()

    if use_cache:
        try:
            df.to_parquet(cpath)
        except Exception:
            pass
    if _MEM_CACHE_ON:
        _KLINES_MEM_CACHE[cache_key] = df
    return df


def fetch_funding_rates(
    symbol: str,
    start_ms: int,
    end_ms: int,
    limit: int = 1000,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch funding rate history."""
    cache_key = f"funding_{symbol}_{start_ms}_{end_ms}"
    if _MEM_CACHE_ON and cache_key in _FUNDING_MEM_CACHE:
        return _FUNDING_MEM_CACHE[cache_key]

    cpath = _cache_path(cache_key)
    if use_cache and os.path.exists(cpath):
        try:
            df = pd.read_parquet(cpath)
            if _MEM_CACHE_ON:
                _FUNDING_MEM_CACHE[cache_key] = df
            return df
        except Exception:
            pass

    sess = requests.Session()
    out = []
    cur = start_ms
    try:
        while True:
            params = {"symbol": symbol, "startTime": cur, "endTime": end_ms, "limit": limit}
            data = _get_json(f"{BINANCE_FAPI}/fapi/v1/fundingRate", params, sess, sleep_s=_BINANCE_SLEEP_S)
            if not data:
                break
            out.extend(data)
            last_t = int(data[-1]["fundingTime"])
            cur = last_t + 1
            if cur >= end_ms:
                break
    except Exception:
        pass

    df = pd.DataFrame(out)
    if df.empty:
        df = pd.DataFrame(columns=["fundingTime", "fundingRate"]).set_index(pd.DatetimeIndex([], tz="UTC"))
        if _MEM_CACHE_ON:
            _FUNDING_MEM_CACHE[cache_key] = df
        return df

    df["fundingTime"] = pd.to_datetime(df["fundingTime"].astype(int), unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df.set_index("fundingTime")[["fundingRate"]].sort_index().drop_duplicates()

    if use_cache:
        try:
            df.to_parquet(cpath)
        except Exception:
            pass
    if _MEM_CACHE_ON:
        _FUNDING_MEM_CACHE[cache_key] = df
    return df
