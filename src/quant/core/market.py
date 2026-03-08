# src/quant/core/market.py
from __future__ import annotations

import pandas as pd
from quant.data.loaders import to_feature_rows
from quant.data.models import FeatureRow


def update_market_regime_gate(
    strategy,
    market_symbol: str,
    feat_df: pd.DataFrame,
    t: pd.Timestamp,
    equity: float | None = None,
) -> FeatureRow:
    """
    MarketRegimeGate.update_market() 호출을 표준화.
    (누락/실수 방지 + backtest/live 공통)
    """
    row = to_feature_rows(market_symbol, feat_df.loc[[t]])[0]
    # wrappers.py의 MarketRegimeGate 기준
    strategy.update_market(row, equity=equity)
    return row
