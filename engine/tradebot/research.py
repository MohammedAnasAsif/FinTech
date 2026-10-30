"""Overnight research: decide which stocks (if any) to trade tomorrow, and with which settings.

For every stock in the universe:
  1. drop it if it's too expensive for today's capital, too illiquid, or on the block list
     written by the post-market review;
  2. tune the strategy on the older part of its recent 5-minute history;
  3. test the tuned settings on the newest part it has never seen (walk-forward);
  4. keep it only if it made money *after costs* in both parts.
The best few become tomorrow's watchlist. An empty watchlist is a valid answer:
on those days the bot doesn't trade.
"""
from __future__ import annotations

import itertools
import logging
from datetime import datetime, timedelta

import pandas as pd

from .backtest import run_backtest
from .broker.base import MarketData
from .config import Settings
from .store import Store

log = logging.getLogger(__name__)

GRID = {
    "fast_ema": [5, 9, 13],
    "slow_ema": [21, 34],
    "stop_atr": [1.0, 1.5, 2.0],
    "target_atr": [2.0, 3.0],
}


class History:
    """Candle history with a local cache, so the broker is only asked for what's new."""

    def __init__(self, md: MarketData, store: Store, cache: bool = True):
        self.md, self.store, self.cache = md, store, cache

    def get(self, symbol: str, interval: int, start: datetime, end: datetime) -> pd.DataFrame:
        if not self.cache:
            return self.md.candles(symbol, interval, start, end)
        have = self.store.load_candles(symbol, interval, start, end)
        fetch_from = start
        if len(have):
            fetch_from = max(start, have.index[-1].to_pydatetime() - timedelta(days=1))
        new = self.md.candles(symbol, interval, fetch_from, end)
        if len(new):
            self.store.save_candles(symbol, interval, new)
        return self.store.load_candles(symbol, interval, start, end)


def split_days(bars: pd.DataFrame, validation_fraction: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    days = sorted(set(bars.index.date))
    if len(days) < 4:
        return bars.iloc[0:0], bars.iloc[0:0]
    cut = min(len(days) - 1, max(1, int(round(len(days) * (1 - validation_fraction)))))
    cut_day = days[cut]
    mask = bars.index.date < cut_day
    return bars[mask], bars[~mask]


def tune(train: pd.DataFrame, symbol: str, s: Settings, capital: float) -> tuple[dict, dict] | None:
    best = None
    keys = list(GRID)
    for combo in itertools.product(*(GRID[k] for k in keys)):
        params = dict(zip(keys, combo))
        if params["fast_ema"] >= params["slow_ema"]:
            continue
        strat = s.strategy.model_copy(update=params)
        m = run_backtest(train, symbol, s, capital, strat).metrics
        if m["trades"] < s.research.min_trades:
            continue
        key = (m["net"], m["profit_factor"])
        if best is None or key > best[0]:
            best = (key, params, m)
    return (best[1], best[2]) if best else None


def context(bars: pd.DataFrame) -> dict:
    daily = bars.groupby(bars.index.date).agg(
        close=("close", "last"), high=("high", "max"), low=("low", "min"), volume=("volume", "sum"))
    daily["turnover"] = daily["close"] * daily["volume"]
    last = float(daily["close"].iloc[-1])
    sma = float(daily["close"].tail(20).mean())
    rng = float(((daily["high"] - daily["low"]) / daily["close"]).tail(10).mean() * 100)
    return {
        "last_price": round(last, 2),
        "trend": "up" if last > sma * 1.01 else ("down" if last < sma * 0.99 else "sideways"),
        "vs_20d_avg_pct": round((last / sma - 1) * 100, 2),
        "avg_day_range_pct": round(rng, 2),
        "avg_turnover_cr": round(float(daily["turnover"].tail(10).mean()) / 1e7, 1),
    }


def research(history: History, store: Store, s: Settings, now: datetime, capital: float | None = None,
             symbols: list[str] | None = None, exclude: set[str] | None = None, label: str = "nightly") -> dict:
    capital = capital or s.research.assumed_capital
    interval = s.strategy.interval_minutes
    start = now - timedelta(days=s.research.lookback_days)
    blocked = {k: v for k, v in (store.get("blocklist", {}) or {}).items() if v >= now.date().isoformat()}
    exclude = set(exclude or ()) | set(blocked)
    picks, rejected = [], []

    for sym in symbols or s.research.universe:
        if sym in exclude:
            reason = f"blocked by review until {blocked[sym]}" if sym in blocked else "excluded today"
            rejected.append({"symbol": sym, "reason": reason})
            continue
        try:
            bars = history.get(sym, interval, start, now)
        except Exception as e:  # noqa: BLE001 — one bad symbol shouldn't stop research
            rejected.append({"symbol": sym, "reason": f"data error: {e}"})
            continue
        if len(bars) < 200:
            rejected.append({"symbol": sym, "reason": "not enough history"})
            continue
        ctx = context(bars)
        if ctx["last_price"] > capital * s.research.max_price_fraction:
            rejected.append({"symbol": sym, "reason": f"price {ctx['last_price']} too high for capital {capital:.0f}"})
            continue
        if ctx["avg_turnover_cr"] < s.research.min_avg_turnover_cr:
            rejected.append({"symbol": sym, "reason": f"illiquid ({ctx['avg_turnover_cr']} cr/day)"})
            continue
        train, test = split_days(bars, s.research.validation_fraction)
        tuned = tune(train, sym, s, capital) if len(train) else None
        if not tuned:
            rejected.append({"symbol": sym, "reason": "no profitable settings in the tuning window"})
            continue
        params, train_m = tuned
        strat = s.strategy.model_copy(update=params)
        test_m = run_backtest(test, sym, s, capital, strat).metrics
        if train_m["net"] <= 0:
            rejected.append({"symbol": sym, "reason": "lost money after costs while tuning"})
            continue
        if test_m["trades"] < max(1, s.research.min_trades // 2) or test_m["net"] <= 0:
            rejected.append({"symbol": sym, "reason": f"failed the unseen-data test (net {test_m['net']})"})
            continue
        reasons = [
            f"made ₹{train_m['net']} after costs over {train_m['trades']} trades while tuning",
            f"then ₹{test_m['net']} over {test_m['trades']} trades on newer days it had not seen",
            f"daily trend {ctx['trend']} ({ctx['vs_20d_avg_pct']:+}% vs 20-day average)",
            f"costs ate {int(test_m['cost_share_of_gross'] * 100)}% of gross profit in the test",
        ]
        picks.append({
            "symbol": sym, "params": params, "score": round(test_m["net_per_day"], 2),
            "train": train_m, "test": test_m, "context": ctx, "reasons": reasons,
        })

    picks.sort(key=lambda p: p["score"], reverse=True)
    picks = picks[: s.research.top_k]
    result = {
        "kind": label,
        "generated_at": now.isoformat(timespec="seconds"),
        "capital": capital,
        "picks": picks,
        "rejected": rejected,
        "note": ("No stock passed both tests — the bot will sit out rather than force trades."
                 if not picks else f"{len(picks)} stock(s) passed tuning and the unseen-data test."),
    }
    store.put("watchlist", result)
    log.info("research (%s): %d picks, %d rejected", label, len(picks), len(rejected))
    return result
