"""Bar-by-bar intraday backtester.

Uses the same strategy, risk rules and cost model as live trading, so a strategy has to
beat brokerage, taxes and slippage here before it is ever allowed near real money.
Conservative assumptions: fills at the next bar's open plus slippage, and when a bar
touches both the stop and the target, the stop is assumed to have hit first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from .config import Settings, StrategySettings
from .costs import round_trip_costs, slip
from .models import Trade
from .risk import DayRisk, LimitAction
from .strategy import compute_signals, describe_entry


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)

    @property
    def metrics(self) -> dict:
        return summarize(self.trades)


def summarize(trades: list[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "net": 0.0, "gross": 0.0, "costs": 0.0, "win_rate": 0.0,
                "avg_net": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0, "days": 0,
                "net_per_day": 0.0, "cost_share_of_gross": 0.0}
    nets = [t.net for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [-x for x in nets if x < 0]
    eq, peak, mdd = 0.0, 0.0, 0.0
    for x in nets:
        eq += x
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    gross = sum(t.gross for t in trades)
    costs = sum(t.costs for t in trades)
    days = len({t.day for t in trades})
    return {
        "trades": n,
        "net": round(sum(nets), 2),
        "gross": round(gross, 2),
        "costs": round(costs, 2),
        "win_rate": round(len(wins) / n, 3),
        "avg_net": round(sum(nets) / n, 2),
        "profit_factor": round(sum(wins) / sum(losses), 2) if losses else (99.0 if wins else 0.0),
        "max_drawdown": round(mdd, 2),
        "days": days,
        "net_per_day": round(sum(nets) / days, 2) if days else 0.0,
        "cost_share_of_gross": round(costs / abs(gross), 2) if gross else 0.0,
    }


def run_backtest(bars: pd.DataFrame, symbol: str, s: Settings, capital: float,
                 strat: StrategySettings | None = None) -> BacktestResult:
    p = strat or s.strategy
    m, c = s.market, s.costs
    res = BacktestResult()
    if bars is None or len(bars) < p.slow_ema + 5:
        return res
    df = compute_signals(bars, p)
    step = timedelta(minutes=p.interval_minutes)

    for day, g in df.groupby(df.index.date):
        risk = DayRisk(capital=capital, cfg=s.risk)
        pos = None              # dict while a position is open
        pending_entry = None    # (direction, reason) to execute at next open
        pending_exit = None
        rows = list(g.itertuples())
        for i, r in enumerate(rows):
            ts: datetime = r.Index
            bar_end = (ts + step).timetz().replace(tzinfo=None)

            # 1) orders decided at the previous close fill at this open
            if pos and pending_exit:
                res.trades.append(_close(pos, r.open, ts, pending_exit, symbol, day, s, i))
                risk.on_trade_closed(res.trades[-1], ts)
                pos, pending_exit = None, None
            if pending_entry and not pos:
                direction, reason, stop_dist, target_dist = pending_entry
                px = slip(r.open, direction > 0, c)
                stop = px - direction * stop_dist
                target = px + direction * target_dist
                qty = risk.position_size(px, stop)
                if qty > 0 and not worth_it(px, qty, target_dist, p, c):
                    qty = 0
                if qty > 0:
                    pos = {"dir": direction, "qty": qty, "px": px, "ts": ts, "stop": stop,
                           "target": target, "reason": reason, "i": i}
            pending_entry = None

            # 2) stop / target inside this bar
            if pos:
                hit_stop = r.low <= pos["stop"] if pos["dir"] > 0 else r.high >= pos["stop"]
                hit_tgt = r.high >= pos["target"] if pos["dir"] > 0 else r.low <= pos["target"]
                if hit_stop or hit_tgt:
                    level = pos["stop"] if hit_stop else pos["target"]
                    res.trades.append(_close(pos, level, ts, "stop" if hit_stop else "target", symbol, day, s, i))
                    risk.on_trade_closed(res.trades[-1], ts)
                    pos = None

            # 3) limits (realized only here; intrabar unrealized is approximated by the stop)
            if risk.check_limits(0.0) is not LimitAction.NONE and not risk.day_over:
                risk.end_day("loss limit")

            # 4) forced square-off
            if bar_end >= m.square_off:
                if pos:
                    res.trades.append(_close(pos, r.close, ts + step, "square-off", symbol, day, s, i))
                    risk.on_trade_closed(res.trades[-1], ts)
                    pos = None
                break

            # 5) decide at this bar's close
            if pos:
                if (pos["dir"] > 0 and r.exit_long) or (pos["dir"] < 0 and r.exit_short):
                    pending_exit = "signal reversed"
            elif m.trade_start <= bar_end < m.last_entry and i + 1 < len(rows):
                ok, _ = risk.can_enter(ts + step, 0)
                direction = 1 if r.enter_long else (-1 if r.enter_short else 0)
                if ok and direction and r.atr > 0:
                    row = pd.Series(r._asdict())
                    pending_entry = (direction, describe_entry(row, direction, p),
                                     p.stop_atr * r.atr, p.target_atr * r.atr)
        if pos:  # data ended early
            last = rows[-1]
            res.trades.append(_close(pos, last.close, last.Index, "end of data", symbol, day, s, len(rows) - 1))
    return res


def worth_it(price: float, qty: int, target_dist: float, p: StrategySettings, c) -> bool:
    """Is the profit at the target big enough compared with the round-trip charges?"""
    charges = round_trip_costs(price * qty, price * qty, c).total
    return target_dist * qty >= p.min_reward_to_cost * charges


def _close(pos: dict, price: float, ts: datetime, reason: str, symbol: str, day, s: Settings, i: int) -> Trade:
    c = s.costs
    exit_px = slip(price, pos["dir"] < 0, c)
    qty, d = pos["qty"], pos["dir"]
    buy_v = (pos["px"] if d > 0 else exit_px) * qty
    sell_v = (exit_px if d > 0 else pos["px"]) * qty
    gross = (exit_px - pos["px"]) * qty * d
    costs = round_trip_costs(buy_v, sell_v, c).total
    return Trade(
        day=str(day), symbol=symbol, direction=d, qty=qty,
        entry_ts=pos["ts"].isoformat(), entry_price=round(pos["px"], 2),
        exit_ts=ts.isoformat(), exit_price=round(exit_px, 2),
        gross=round(gross, 2), costs=round(costs, 2), net=round(gross - costs, 2),
        entry_reason=pos["reason"], exit_reason=reason, mode="backtest", bars_held=i - pos["i"],
    )
