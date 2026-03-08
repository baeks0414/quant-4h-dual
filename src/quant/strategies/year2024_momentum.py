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
class Year2024MomentumStrategy:
    """
    2024 dedicated long-only momentum strategy.
    - Signal: lookback momentum > threshold
    - Position: long(1) or cash(0)
    """

    lookback_bars: int = 16
    threshold: float = 0.05
    hold_bars: int = 8

    def positions(self, prices: pd.DataFrame) -> pd.DataFrame:
        mom = prices.pct_change(self.lookback_bars)
        raw = (mom > self.threshold).astype(float).fillna(0.0)
        return _apply_hold(raw, self.hold_bars)
