from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, List
from datetime import datetime
import numpy as np

from quant.core.types import Side
from quant.core.events import FillEvent


@dataclass
class Position:
    side: int = 0  # +1 long, -1 short, 0 flat
    qty: float = 0.0
    entry: float = 0.0
    stop: Optional[float] = None
    add_count: int = 0
    last_add_bar: int = 0
    entry_bar: int = 0
    entry_time: Optional[datetime] = None


class Portfolio:
    def __init__(self, symbols: List[str], initial_cash: float):
        self.symbols = list(symbols)
        self.cash = float(initial_cash)
        self.positions: Dict[str, Position] = {s: Position() for s in symbols}
        self.last_close: Dict[str, float] = {s: np.nan for s in symbols}
        self.trades: List[dict] = []
        self.bar_count: int = 0
        self.last_exit_time: Dict[str, Optional[datetime]] = {s: None for s in symbols}
        self.last_exit_side: Dict[str, int] = {s: 0 for s in symbols}

    def update_close(self, symbol: str, close_px: float) -> None:
        self.last_close[symbol] = float(close_px)

    def unrealized(self) -> float:
        u = 0.0
        for s, p in self.positions.items():
            if p.side == 0 or np.isnan(self.last_close[s]):
                continue
            c = self.last_close[s]
            u += (c - p.entry) * p.qty if p.side > 0 else (p.entry - c) * p.qty
        return u

    @property
    def equity(self) -> float:
        return self.cash + self.unrealized()

    def open_risk_usdt(self) -> float:
        r = 0.0
        for _, p in self.positions.items():
            if p.side == 0 or p.stop is None:
                continue
            r += abs(p.entry - p.stop) * p.qty
        return r

    def current_profit_atr(self, symbol: str, atr: float) -> float:
        p = self.positions[symbol]
        if p.side == 0 or np.isnan(self.last_close[symbol]) or atr <= 0:
            return 0.0
        c = self.last_close[symbol]
        if p.side > 0:
            return (c - p.entry) / atr
        return (p.entry - c) / atr

    def apply_fill(self, fill: FillEvent, stop_price: Optional[float], is_pyramid: bool = False) -> None:
        s = fill.symbol
        p = self.positions[s]

        self.cash -= float(fill.fee)

        side = 1 if fill.side == Side.BUY else -1
        px = float(fill.price)

        # New entry
        if p.side == 0:
            self.positions[s] = Position(
                side=side,
                qty=float(fill.qty),
                entry=px,
                stop=stop_price,
                add_count=0,
                last_add_bar=self.bar_count,
                entry_bar=self.bar_count,
                entry_time=fill.ts,
            )
            self.trades.append(
                {
                    "time": fill.ts,
                    "symbol": s,
                    "type": "ENTRY_LONG" if side > 0 else "ENTRY_SHORT",
                    "entry": px,
                    "exit": None,
                    "qty": float(fill.qty),
                    "pnl": 0.0,
                    "note": fill.reason,
                }
            )
            return

        # Pyramiding add
        if is_pyramid and p.side == side:
            new_qty = p.qty + float(fill.qty)
            new_entry = (p.entry * p.qty + px * float(fill.qty)) / new_qty
            self.positions[s] = Position(
                side=side,
                qty=new_qty,
                entry=new_entry,
                stop=stop_price if stop_price is not None else p.stop,
                add_count=p.add_count + 1,
                last_add_bar=self.bar_count,
            )
            self.trades.append(
                {
                    "time": fill.ts,
                    "symbol": s,
                    "type": "PYRAMID_LONG" if side > 0 else "PYRAMID_SHORT",
                    "entry": px,
                    "exit": None,
                    "qty": float(fill.qty),
                    "pnl": 0.0,
                    "note": fill.reason,
                }
            )
            return

        # Full close (flip/flat)
        pnl = (px - p.entry) * p.qty if p.side > 0 else (p.entry - px) * p.qty
        self.cash += float(pnl)
        self.trades.append(
            {
                "time": fill.ts,
                "symbol": s,
                "type": "EXIT",
                "entry": p.entry,
                "exit": px,
                "qty": p.qty,
                "pnl": float(pnl),
                "note": fill.reason,
            }
        )
        self.last_exit_time[s] = fill.ts
        self.last_exit_side[s] = p.side
        self.positions[s] = Position()

    def apply_funding(self, ts: datetime, symbol: str, rate: float) -> None:
        p = self.positions[symbol]
        if p.side == 0 or np.isnan(self.last_close[symbol]):
            return
        c = float(self.last_close[symbol])
        notional = abs(c * p.qty)
        funding_pnl = -(p.side) * notional * float(rate)
        self.cash += float(funding_pnl)
        self.trades.append(
            {
                "time": ts,
                "symbol": symbol,
                "type": "FUNDING",
                "entry": None,
                "exit": None,
                "qty": p.qty,
                "pnl": float(funding_pnl),
                "note": f"rate={rate:.6f}, notional~{notional:.2f}",
            }
        )
