# src/quant/strategies/mr_strategy.py
# ============================================================
# CHOP 구간 전용 BB Z-score Mean Reversion 전략
# Dual Portfolio 방식에서 MR 엔진 전용으로 사용
#
# 전략 로직:
#   - CHOP 레짐에서만 신호 생성 (추세 레짐은 FLAT)
#   - BB(14) Z-score < -mr_entry_z → LONG MR 진입
#   - BB(14) Z-score > +mr_entry_z → SHORT MR 진입
#   - |BB Z-score| < mr_exit_z → FLAT (중심 회귀)
#   - max_hold_bars 관리: engine의 별도 hold-bar 카운터 사용
# ============================================================

from __future__ import annotations

from typing import Optional
import numpy as np

from quant.config.presets import PortfolioBTConfig
from quant.data.models import FeatureRow
from quant.core.events import SignalEvent

MR_NOTE_PREFIX = "mr_"


class MRStrategy:
    """
    CHOP 구간 전용 BB Z-score Mean Reversion 전략.
    Dual Portfolio에서 MR 전용 엔진에 사용.
    """
    def __init__(self, cfg: PortfolioBTConfig):
        self.cfg = cfg

    def on_bar(self, row: FeatureRow, funding_rate: Optional[float] = None) -> SignalEvent:
        cfg = self.cfg
        px = float(row.close)
        a = float(row.atr14)
        regime = str(row.regime)

        if np.isnan(a):
            return SignalEvent(row.symbol, "HOLD", None, "atr nan")

        # 추세/변동성 구간 → MR 포지션 즉시 청산 신호
        if regime in ("STRONG_TREND", "VOL_EXPAND"):
            return SignalEvent(row.symbol, "FLAT", None, f"mr_flat_trend({regime})")

        # CHOP 구간에서만 BB Z-score MR
        use_bb = getattr(cfg, "mr_use_bb", True)
        if use_bb:
            bb_center = row.bb_mean
            bb_spread = row.bb_std
        else:
            bb_center = row.mr_mean
            bb_spread = row.mr_std

        if bb_center is None or bb_spread is None or bb_spread <= 0:
            return SignalEvent(row.symbol, "HOLD", None, "mr_bb_not_ready")

        bb_z = (px - bb_center) / bb_spread
        mr_entry_z = float(cfg.mr_entry_z)
        mr_exit_z = float(cfg.mr_exit_z)
        mr_stop_mult = float(cfg.mr_stop_atr_mult)

        # 진입
        if bb_z < -mr_entry_z:
            stop = px - mr_stop_mult * a
            return SignalEvent(row.symbol, "LONG", stop,
                               f"{MR_NOTE_PREFIX}long_entry z={bb_z:.2f}")

        if bb_z > mr_entry_z:
            stop = px + mr_stop_mult * a
            return SignalEvent(row.symbol, "SHORT", stop,
                               f"{MR_NOTE_PREFIX}short_entry z={bb_z:.2f}")

        # 청산: 중심 복귀
        if abs(bb_z) < mr_exit_z:
            return SignalEvent(row.symbol, "FLAT", None,
                               f"{MR_NOTE_PREFIX}exit z={bb_z:.2f}")

        return SignalEvent(row.symbol, "HOLD", None, f"mr_hold z={bb_z:.2f}")
