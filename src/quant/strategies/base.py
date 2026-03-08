from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from quant.data.models import FeatureRow
from quant.core.events import SignalEvent


class Strategy(ABC):
    @abstractmethod
    def on_bar(self, row: FeatureRow, funding_rate: Optional[float]) -> SignalEvent:
        ...
