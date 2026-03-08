from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def _apply_hold(signal: pd.DataFrame, hold_bars: int) -> pd.DataFrame:
    """Keep last non-zero signal for N bars (causal, no look-ahead)."""
    if hold_bars <= 0:
        return signal.fillna(0.0)

    out = signal.copy().fillna(0.0)
    for col in out.columns:
        last = 0.0
        ttl = 0
        vals = []
        for v in out[col].values:
            cur = float(v)
            if cur != 0.0:
                last = cur
                ttl = hold_bars
            elif ttl > 0:
                cur = last
                ttl -= 1
            else:
                cur = 0.0
            vals.append(cur)
        out[col] = vals
    return out


@dataclass(frozen=True)
class Year2025MomentumStrategy:
    """
    2025 dedicated long/short momentum strategy.
    - Signal: sign of lookback momentum against threshold
    - Position: long(+1), short(-1), or cash(0)
    """

    lookback_bars: int = 1
    threshold: float = 0.02
    hold_bars: int = 0

    def positions(self, prices: pd.DataFrame) -> pd.DataFrame:
        mom = prices.pct_change(self.lookback_bars)
        raw = (mom > self.threshold).astype(float) - (mom < -self.threshold).astype(float)
        return _apply_hold(raw.fillna(0.0), self.hold_bars)
