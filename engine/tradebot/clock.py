"""Market calendar and the bot's daily timetable (all in IST)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .config import MarketSettings

IST = ZoneInfo("Asia/Kolkata")


class Phase(str, Enum):
    CLOSED = "CLOSED"                 # weekend, holiday or night
    PRE_TRADE = "PRE_TRADE"           # before trade_start on a trading day
    ENTRY_WINDOW = "ENTRY_WINDOW"     # new trades allowed
    EXIT_ONLY = "EXIT_ONLY"           # last_entry .. square_off: manage open trades only
    AFTER_SQUARE_OFF = "AFTER_SQUARE_OFF"


class Clock:
    """Real time in IST. The replay clock in replay.py swaps this for simulated time."""

    def now(self) -> datetime:
        return datetime.now(IST)


def load_holidays(path: str | Path) -> set[date]:
    p = Path(path)
    if not p.exists():
        return set()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: set[date] = set()
    for _year, items in raw.items():
        for item in items or []:
            d = item["date"] if isinstance(item, dict) else item
            out.add(d if isinstance(d, date) else date.fromisoformat(str(d)))
    return out


class MarketCalendar:
    def __init__(self, m: MarketSettings, holidays: set[date] | None = None):
        self.m = m
        self.holidays = holidays or set()

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def next_trading_day(self, d: date) -> date:
        n = d + timedelta(days=1)
        while not self.is_trading_day(n):
            n += timedelta(days=1)
        return n

    def previous_trading_days(self, d: date, count: int) -> list[date]:
        out, n = [], d
        while len(out) < count:
            n -= timedelta(days=1)
            if self.is_trading_day(n):
                out.append(n)
        return list(reversed(out))

    def phase(self, now: datetime) -> Phase:
        if not self.is_trading_day(now.date()):
            return Phase.CLOSED
        t = now.timetz().replace(tzinfo=None)
        if t < self.m.market_open or t >= self.m.market_close:
            return Phase.CLOSED if t < self.m.market_open else Phase.AFTER_SQUARE_OFF
        if t < self.m.trade_start:
            return Phase.PRE_TRADE
        if t < self.m.last_entry:
            return Phase.ENTRY_WINDOW
        if t < self.m.square_off:
            return Phase.EXIT_ONLY
        return Phase.AFTER_SQUARE_OFF

    def at(self, d: date, t: time) -> datetime:
        return datetime.combine(d, t, tzinfo=IST)
