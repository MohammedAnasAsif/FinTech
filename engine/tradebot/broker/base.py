"""Broker interfaces. Market data and order execution are separate so that paper trading
can use real Angel One prices with simulated fills."""
from __future__ import annotations

import itertools
from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

from ..config import CostSettings
from ..costs import slip
from ..models import Fill, OrderStatus, Side


class MarketData(ABC):
    @abstractmethod
    def candles(self, symbol: str, interval_minutes: int, start: datetime, end: datetime) -> pd.DataFrame:
        """OHLCV bars with an IST DatetimeIndex (bar start time), oldest first."""

    @abstractmethod
    def ltp(self, symbol: str) -> float | None:
        """Last traded price."""

    def has_symbol(self, symbol: str) -> bool:
        return True


class Executor(ABC):
    is_live: bool = False

    @abstractmethod
    def place(self, symbol: str, side: Side, qty: int, ref_price: float, now: datetime) -> Fill:
        """Place an order and wait for its outcome. Returns the filled quantity and price."""

    def available_cash(self) -> float | None:
        return None

    def open_quantities(self) -> dict[str, int]:
        return {}


class PaperExecutor(Executor):
    """Simulated fills at the reference price plus the configured slippage."""

    is_live = False
    _ids = itertools.count(1)

    def __init__(self, costs: CostSettings):
        self.costs = costs
        self.qty: dict[str, int] = {}

    def place(self, symbol: str, side: Side, qty: int, ref_price: float, now: datetime) -> Fill:
        px = round(slip(ref_price, side is Side.BUY, self.costs), 2)
        self.qty[symbol] = self.qty.get(symbol, 0) + (qty if side is Side.BUY else -qty)
        return Fill(symbol, side, qty, px, now, f"PAPER-{next(self._ids)}", OrderStatus.FILLED)

    def open_quantities(self) -> dict[str, int]:
        return {k: v for k, v in self.qty.items() if v}
