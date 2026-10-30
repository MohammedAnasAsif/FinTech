"""EMA crossover with a VWAP and volume filter, ATR-based stop and target.

Deliberately simple and readable: the edge (if any) is proven or disproven by the
backtester and paper trading, not assumed. Signals are computed on *closed* bars only,
and the same function runs in backtests, research and live trading.
"""
from __future__ import annotations

import pandas as pd

from ..config import StrategySettings
from ..indicators import atr, ema, session_vwap


def compute_signals(bars: pd.DataFrame, p: StrategySettings) -> pd.DataFrame:
    df = bars.copy()
    df["ema_fast"] = ema(df["close"], p.fast_ema)
    df["ema_slow"] = ema(df["close"], p.slow_ema)
    df["atr"] = atr(df, p.atr_period)
    df["vwap"] = session_vwap(df)
    df["vol_avg"] = df["volume"].rolling(20, min_periods=5).mean()

    above = df["ema_fast"] > df["ema_slow"]
    cross_up = above & ~above.shift(1, fill_value=False)
    cross_dn = ~above & above.shift(1, fill_value=False)
    vol_ok = df["volume"] >= p.min_volume_ratio * df["vol_avg"].fillna(df["volume"])
    warm = pd.Series(range(len(df)), index=df.index) >= max(p.slow_ema, p.atr_period)

    long_ok = cross_up & vol_ok & warm
    short_ok = cross_dn & vol_ok & warm
    if p.use_vwap_filter:
        long_ok &= df["close"] > df["vwap"]
        short_ok &= df["close"] < df["vwap"]

    df["enter_long"] = long_ok
    df["enter_short"] = short_ok & p.allow_short
    df["exit_long"] = cross_dn
    df["exit_short"] = cross_up
    return df


def describe_entry(row: pd.Series, direction: int, p: StrategySettings) -> str:
    side = "long" if direction > 0 else "short"
    return (
        f"{side}: EMA{p.fast_ema} crossed {'above' if direction > 0 else 'below'} EMA{p.slow_ema}, "
        f"close {row['close']:.2f} {'>' if direction > 0 else '<'} VWAP {row['vwap']:.2f}, "
        f"volume {row['volume'] / max(row['vol_avg'], 1):.1f}x average"
    )
