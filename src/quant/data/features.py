from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from quant.config.presets import PortfolioBTConfig
from quant.data.models import FeatureRow


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr = pd.concat([(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr_n = tr.rolling(n).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(n).sum() / atr_n
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(n).sum() / atr_n
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).replace([np.inf, -np.inf], np.nan)
    return dx.rolling(n).mean()


def add_features(df: pd.DataFrame, cfg: PortfolioBTConfig) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = ema(df["close"], cfg.ema_fast)
    df["ema_slow"] = ema(df["close"], cfg.ema_slow)
    df["atr14"] = atr(df, 14)
    df["atr30"] = atr(df, 30)
    df["adx14"] = adx(df, 14)
    df["ema_fast_slope_3"] = (df["ema_fast"] - df["ema_fast"].shift(3)) / df["atr14"].replace(0.0, np.nan)
    df["adx_slope_3"] = df["adx14"] - df["adx14"].shift(3)

    w = cfg.donchian_window
    df["donchian_hh"] = df["high"].shift(1).rolling(w).max()
    df["donchian_ll"] = df["low"].shift(1).rolling(w).min()

    # Mean-Reversion features
    mr_w = int(getattr(cfg, "mr_window", 50))
    df["mr_mean"] = df["close"].rolling(mr_w).mean()
    df["mr_std"] = df["close"].rolling(mr_w).std(ddof=0)

    # BB-based MR features
    bb_w = int(getattr(cfg, "mr_bb_window", 14))
    df["bb_mean"] = df["close"].rolling(bb_w).mean()
    df["bb_std"] = df["close"].rolling(bb_w).std(ddof=0)

    # regime: vectorized
    adx14 = df["adx14"].values
    atr14 = df["atr14"].values
    atr30 = df["atr30"].values
    ema_f = df["ema_fast"].values
    ema_s = df["ema_slow"].values

    no_data = np.isnan(adx14) | np.isnan(atr14) | np.isnan(atr30)
    strong_trend_bull = (~no_data) & (adx14 >= cfg.adx_trend) & (ema_f > ema_s)
    strong_trend_bear = (~no_data) & (adx14 >= cfg.adx_trend) & (ema_f <= ema_s)
    strong_trend = strong_trend_bull | strong_trend_bear
    vol_expand = (~no_data) & ~strong_trend & ((atr14 / np.where(atr30 == 0, np.nan, atr30)) >= cfg.atr_expand_ratio)

    use_bear = bool(getattr(cfg, "enable_bear_regime", False))
    if use_bear:
        regime_arr = np.where(
            no_data,
            "NO_DATA",
            np.where(
                strong_trend_bull,
                "STRONG_TREND",
                np.where(strong_trend_bear, "STRONG_TREND_BEAR", np.where(vol_expand, "VOL_EXPAND", "CHOP")),
            ),
        )
    else:
        vol_expand_orig = (~no_data) & ~strong_trend_bull & ((atr14 / np.where(atr30 == 0, np.nan, atr30)) >= cfg.atr_expand_ratio)
        regime_arr = np.where(no_data, "NO_DATA", np.where(strong_trend_bull, "STRONG_TREND", np.where(vol_expand_orig, "VOL_EXPAND", "CHOP")))
    df["regime"] = regime_arr
    return df


def _nan_to_none(v: float) -> Optional[float]:
    return None if np.isnan(v) else float(v)


def df_to_feature_dict(symbol: str, df: pd.DataFrame) -> Dict[object, FeatureRow]:
    has_mr = "mr_mean" in df.columns
    has_bb = "bb_mean" in df.columns

    ts_vals = df.index
    opens = df["open"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    closes = df["close"].values.astype(float)
    volumes = df["volume"].values.astype(float)
    ema_fast_arr = df["ema_fast"].values.astype(float)
    ema_slow_arr = df["ema_slow"].values.astype(float)
    atr14_arr = df["atr14"].values.astype(float)
    atr30_arr = df["atr30"].values.astype(float)
    adx14_arr = df["adx14"].values.astype(float)
    ema_fast_slope_arr = df["ema_fast_slope_3"].values.astype(float) if "ema_fast_slope_3" in df.columns else None
    adx_slope_arr = df["adx_slope_3"].values.astype(float) if "adx_slope_3" in df.columns else None
    regime_arr = df["regime"].values
    don_hh_arr = df["donchian_hh"].values.astype(float)
    don_ll_arr = df["donchian_ll"].values.astype(float)
    mr_mean_arr = df["mr_mean"].values.astype(float) if has_mr else None
    mr_std_arr = df["mr_std"].values.astype(float) if has_mr else None
    bb_mean_arr = df["bb_mean"].values.astype(float) if has_bb else None
    bb_std_arr = df["bb_std"].values.astype(float) if has_bb else None

    result: Dict[object, FeatureRow] = {}
    for i, ts in enumerate(ts_vals):
        ts_py = ts.to_pydatetime()
        result[ts] = FeatureRow(
            symbol=symbol,
            ts=ts_py,
            open=opens[i],
            high=highs[i],
            low=lows[i],
            close=closes[i],
            volume=volumes[i],
            ema_fast=ema_fast_arr[i],
            ema_slow=ema_slow_arr[i],
            atr14=atr14_arr[i],
            atr30=atr30_arr[i],
            adx14=adx14_arr[i],
            regime=str(regime_arr[i]),
            donchian_hh=_nan_to_none(don_hh_arr[i]),
            donchian_ll=_nan_to_none(don_ll_arr[i]),
            mr_mean=_nan_to_none(mr_mean_arr[i]) if mr_mean_arr is not None else None,
            mr_std=_nan_to_none(mr_std_arr[i]) if mr_std_arr is not None else None,
            bb_mean=_nan_to_none(bb_mean_arr[i]) if bb_mean_arr is not None else None,
            bb_std=_nan_to_none(bb_std_arr[i]) if bb_std_arr is not None else None,
            ema_fast_slope_3=_nan_to_none(ema_fast_slope_arr[i]) if ema_fast_slope_arr is not None else None,
            adx_slope_3=_nan_to_none(adx_slope_arr[i]) if adx_slope_arr is not None else None,
        )
    return result


def to_feature_rows(symbol: str, df: pd.DataFrame) -> List[FeatureRow]:
    return list(df_to_feature_dict(symbol, df).values())


def intersect_timeline(feature_dfs: Dict[str, pd.DataFrame], symbols: Tuple[str, ...]) -> pd.DatetimeIndex:
    idx = feature_dfs[symbols[0]].index
    for s in symbols[1:]:
        idx = idx.intersection(feature_dfs[s].index)
    return idx.sort_values()
