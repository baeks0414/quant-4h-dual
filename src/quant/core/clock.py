# src/quant/core/clock.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Sequence, Dict

import pandas as pd

from quant.data.binance_fetch import interval_to_ms, fetch_klines


def _parse_interval(interval: str) -> timedelta:
    if interval.endswith("m"):
        n = int(interval[:-1])
        return timedelta(minutes=n)
    if interval.endswith("h"):
        n = int(interval[:-1])
        return timedelta(hours=n)
    if interval.endswith("d"):
        n = int(interval[:-1])
        return timedelta(days=n)
    raise ValueError(f"Unsupported interval: {interval}")


def _floor_time(t: pd.Timestamp, interval: str) -> pd.Timestamp:
    # t: UTC-aware
    td = _parse_interval(interval)
    epoch = pd.Timestamp(0, tz="UTC")
    delta = t - epoch
    floored = epoch + (delta // pd.Timedelta(td)) * pd.Timedelta(td)
    return floored


@dataclass(frozen=True)
class BarClock:
    interval: str
    symbols: Sequence[str]
    # 안전 여유: 바이낸스 kline 갱신 지연 대비
    settle_lag_seconds: int = 3

    def now_utc(self) -> pd.Timestamp:
        return pd.Timestamp.now("UTC")

    def last_closed_bar_time_estimate(self, now: Optional[pd.Timestamp] = None) -> pd.Timestamp:
        """
        시간만으로 마지막 종가봉 시각을 추정.
        확정 검증은 confirm_closed_bar_time에서 수행.
        """
        now = self.now_utc() if now is None else now
        if now.tzinfo is None:
            now = now.tz_localize("UTC")
        # 봉 단위로 내림 후, lag를 고려해 '확정된' 봉으로 한 칸 전을 반환
        floored = _floor_time(now, self.interval)
        # floored는 현재 진행 중 봉의 open_time일 수 있으므로 직전 봉을 closed로 간주
        last_closed = floored - pd.Timedelta(_parse_interval(self.interval))
        return last_closed

    def confirm_closed_bar_time(self) -> Optional[pd.Timestamp]:
        """
        실제 최근 klines 2개로 '확정된' 마지막 봉 시간을 검증하여 반환.
        (심볼이 여러 개면, 모두 공통으로 확정된 min을 반환)
        """
        end = self.now_utc()
        end_ms = int(end.timestamp() * 1000)

        # 최근 3개 정도면 충분 (limit=3)
        lookback_ms = interval_to_ms(self.interval) * 3
        start_ms = end_ms - lookback_ms

        last_closed_times = []
        for s in self.symbols:
            df = fetch_klines(s, self.interval, start_ms, end_ms, limit=3)
            if df is None or df.empty:
                continue
            # 바이낸스는 마지막 row가 진행중일 수 있으므로 -2를 closed로 간주
            if len(df) >= 2:
                last_closed_times.append(df.index[-2])
            else:
                # 데이터가 1개면 확정 불가
                continue

        if not last_closed_times:
            return None

        # 심볼별로 미세하게 차이나면 min으로 동기화
        t = min(last_closed_times)
        return t
