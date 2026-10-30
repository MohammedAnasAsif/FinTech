from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass
class Fill:
    symbol: str
    side: Side
    qty: int
    price: float
    ts: datetime
    order_id: str
    status: OrderStatus = OrderStatus.FILLED
    message: str = ""


@dataclass
class Position:
    symbol: str
    direction: int                 # +1 long, -1 short
    qty: int
    entry_price: float
    entry_ts: datetime
    stop: float
    target: float
    cycle: int
    entry_reason: str = ""
    entry_costs: float = 0.0
    ref_price: float = 0.0         # price the bot aimed for, to measure slippage

    def unrealized(self, price: float) -> float:
        return (price - self.entry_price) * self.qty * self.direction


@dataclass
class Trade:
    """One completed round trip (entry + exit)."""
    day: str
    symbol: str
    direction: int
    qty: int
    entry_ts: str
    entry_price: float
    exit_ts: str
    exit_price: float
    gross: float
    costs: float
    net: float
    entry_reason: str
    exit_reason: str
    cycle: int = 1
    mode: str = "paper"
    bars_held: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
