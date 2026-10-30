"""Replay mode: run a whole trading day against stored (or synthetic) candles with a
fast simulated clock. Lets you test the engine and the app on a weekend, without an
Angel One account, and is what the end-to-end tests use."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

from .broker.base import MarketData
from .clock import IST, Clock
from .store import Store


class SimClock(Clock):
    """Simulated IST time that runs `speed` times faster than real time."""

    def __init__(self, start: datetime, speed: float = 60.0):
        import time as _t
        self._t = _t
        self.start = start
        self.speed = speed
        self.real0 = _t.monotonic()
        self.offset = timedelta(0)

    def now(self) -> datetime:
        return self.start + self.offset + timedelta(seconds=(self._t.monotonic() - self.real0) * self.speed)

    def jump(self, to: datetime) -> None:
        self.offset += to - self.now()


class ManualClock(Clock):
    """Clock that only moves when told to (unit tests)."""

    def __init__(self, start: datetime):
        self.t = start

    def now(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


class ReplayMarketData(MarketData):
    """Serves 1-minute candles from the store, never revealing bars after clock.now()."""

    def __init__(self, store: Store, clock: Clock):
        self.store = store
        self.clock = clock

    def has_symbol(self, symbol: str) -> bool:
        return symbol in self.store.symbols_with_candles(1)

    def candles(self, symbol: str, interval_minutes: int, start: datetime, end: datetime) -> pd.DataFrame:
        from .indicators import resample
        end = min(end, self.clock.now())
        df = self.store.load_candles(symbol, 1, start, end)
        # only bars that have fully closed
        df = df[df.index + timedelta(minutes=1) <= end]
        return df if interval_minutes == 1 else resample(df, interval_minutes)

    def ltp(self, symbol: str) -> float | None:
        now = self.clock.now()
        df = self.store.load_candles(symbol, 1, now - timedelta(days=5), now)
        return float(df["close"].iloc[-1]) if len(df) else None


def synthetic_day(symbol: str, day: date, start_price: float, seed: int, drift: float = 0.0,
                  vol: float = 0.0012) -> pd.DataFrame:
    """One NSE session of 1-minute bars (09:15-15:29) from a trending random walk."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(datetime.combine(day, time(9, 15), tzinfo=IST), periods=375, freq="1min")
    # regime switches make crossovers happen
    regimes = np.repeat(rng.normal(drift, vol * 0.6, 375 // 25 + 1), 25)[:375]
    rets = regimes + rng.normal(0, vol, 375)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    spread = np.abs(rng.normal(0, vol, 375)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.integers(20_000, 200_000, 375).astype(float)
    volume[:15] *= 3
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def seed_synthetic(store: Store, symbols: dict[str, float], days: list[date], seed: int = 7) -> None:
    """Fill the store with synthetic 1-minute history (demo/test only — not real prices)."""
    for k, (sym, price) in enumerate(symbols.items()):
        p = price
        for j, d in enumerate(days):
            df = synthetic_day(sym, d, p, seed + 1000 * k + j, drift=0.00004 * ((k % 3) - 1))
            store.save_candles(sym, 1, df)
            p = float(df["close"].iloc[-1])
