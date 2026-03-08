"""
동적 파라미터 시스템 (DynamicParams)

시장 조건 분석 결과 (market_condition_param_analysis.py) 기반:

  ADX > 38 (강한 추세):
    trail=2.5, stop=1.5, confirm=1, pyramid_min=1.0
    → 추세가 명확할 때 공격적으로 수익 극대화

  ADX 30~38 (보통 추세):
    trail=2.5, stop=1.8, confirm=1, pyramid_min=1.2
    → 균형잡힌 설정

  ADX 20~30 (약한 추세):
    trail=2.0, stop=2.0, confirm=2, pyramid_min=1.5
    → 진입을 더 엄격히, 수익은 빠르게 확정

  ADX < 20 (매우 약한 / 횡보):
    trail=1.5, stop=2.0, confirm=3, pyramid_min=2.5
    → 거의 거래 안 함, 들어가도 빨리 빠져나옴

사용법:
  engine.on_bar() 에서 매 bar마다 호출하여
  cfg를 임시로 덮어쓴 뒤 복원하는 방식으로 적용
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from quant.data.models import FeatureRow


@dataclass
class DynamicOverride:
    """한 bar에 적용할 파라미터 오버라이드 값 묶음"""
    trail_atr_mult: float
    stop_atr_mult_trend: float
    entry_confirm_bars: int
    pyramid_min_profit_atr: float
    # 선택적 오버라이드
    flip_cooldown_bars: Optional[int] = None
    enable_pyramiding: Optional[bool] = None


def adx_tier(adx: float) -> str:
    """ADX 값을 4개 구간으로 분류"""
    if adx > 38:
        return "STRONG"       # 강한 추세
    elif adx > 30:
        return "MEDIUM"       # 보통 추세
    elif adx > 20:
        return "WEAK"         # 약한 추세
    else:
        return "VERY_WEAK"    # 횡보 / 매우 약한


# 분석 결과 기반 구간별 최적 파라미터 테이블
_TIER_PARAMS: dict[str, dict] = {
    "STRONG": {
        "trail_atr_mult": 2.7,
        "stop_atr_mult_trend": 1.5,
        "entry_confirm_bars": 1,
        "pyramid_min_profit_atr": 1.0,
        "enable_pyramiding": True,
    },
    "MEDIUM": {
        "trail_atr_mult": 2.5,
        "stop_atr_mult_trend": 1.8,
        "entry_confirm_bars": 1,
        "pyramid_min_profit_atr": 1.2,
        "enable_pyramiding": True,
    },
    "WEAK": {
        "trail_atr_mult": 2.0,
        "stop_atr_mult_trend": 2.0,
        "entry_confirm_bars": 2,
        "pyramid_min_profit_atr": 1.5,
        "enable_pyramiding": True,
    },
    "VERY_WEAK": {
        "trail_atr_mult": 1.5,
        "stop_atr_mult_trend": 2.0,
        "entry_confirm_bars": 3,
        "pyramid_min_profit_atr": 2.5,
        "enable_pyramiding": False,  # 횡보에서 피라미딩 없음
    },
}


def resolve(row: FeatureRow) -> DynamicOverride:
    """
    현재 bar의 FeatureRow를 보고 동적 파라미터 오버라이드를 반환.

    Args:
        row: 현재 bar의 feature 데이터 (ADX, ATR, regime 등 포함)

    Returns:
        DynamicOverride: 이 bar에 적용할 파라미터 값들
    """
    adx = float(row.adx14) if row.adx14 is not None else float("nan")

    # ADX가 없으면 보수적 기본값
    if np.isnan(adx):
        tier = "WEAK"
    else:
        tier = adx_tier(adx)

    p = _TIER_PARAMS[tier]
    return DynamicOverride(
        trail_atr_mult=p["trail_atr_mult"],
        stop_atr_mult_trend=p["stop_atr_mult_trend"],
        entry_confirm_bars=p["entry_confirm_bars"],
        pyramid_min_profit_atr=p["pyramid_min_profit_atr"],
        enable_pyramiding=p["enable_pyramiding"],
    )


class DynamicParamContext:
    """
    cfg를 임시로 오버라이드하고 복원하는 컨텍스트 매니저.

    사용 예:
        with DynamicParamContext(cfg, row):
            engine.strategy.on_bar(row, ...)
    """

    def __init__(self, cfg, row: FeatureRow):
        self._cfg = cfg
        self._override = resolve(row)
        self._saved: dict = {}

    def __enter__(self):
        override = self._override
        cfg = self._cfg
        fields = {
            "trail_atr_mult": override.trail_atr_mult,
            "stop_atr_mult_trend": override.stop_atr_mult_trend,
            "entry_confirm_bars": override.entry_confirm_bars,
            "pyramid_min_profit_atr": override.pyramid_min_profit_atr,
        }
        if override.enable_pyramiding is not None:
            fields["enable_pyramiding"] = override.enable_pyramiding
        if override.flip_cooldown_bars is not None:
            fields["flip_cooldown_bars"] = override.flip_cooldown_bars

        for k, v in fields.items():
            self._saved[k] = getattr(cfg, k, None)
            setattr(cfg, k, v)
        return self

    def __exit__(self, *_):
        for k, v in self._saved.items():
            setattr(self._cfg, k, v)


def apply_to_engine(engine, row: FeatureRow, funding_rate=None) -> None:
    """
    동적 파라미터를 적용한 상태로 engine.on_bar()를 실행하는 헬퍼.

    Engine을 수정하지 않고 외부에서 사용 가능.

    Args:
        engine: Engine 인스턴스
        row:    현재 bar FeatureRow
        funding_rate: 펀딩비 (옵션)
    """
    with DynamicParamContext(engine.cfg, row):
        engine.on_bar(row, funding_rate=funding_rate)
