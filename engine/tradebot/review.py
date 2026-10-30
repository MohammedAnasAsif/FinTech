"""Post-market self-review (runs after the 3 PM square-off).

Looks at what happened today, names the mistakes with evidence, and turns each one into
a small, bounded rule change for tomorrow. Every change is written down in the journal so
you can see exactly what the bot learned and why. Nothing here can raise risk limits,
switch to live mode, or increase position size — learning only ever makes the bot pickier.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from .backtest import summarize
from .config import Settings
from .store import Store

BLOCK_DAYS = 5
MAX_REWARD_TO_COST = 6.0
MAX_VOLUME_RATIO = 2.0
MAX_SLIPPAGE_PCT = 0.3


def overrides(store: Store) -> dict:
    return store.get("overrides", {}) or {}


def effective_settings(s: Settings, store: Store, symbol: str | None = None) -> Settings:
    """Base settings plus what the reviews have learned (global and per-stock)."""
    o = overrides(store)
    strat_upd, cost_upd = {}, {}
    if "min_reward_to_cost" in o:
        strat_upd["min_reward_to_cost"] = max(s.strategy.min_reward_to_cost, o["min_reward_to_cost"])
    if "slippage_pct" in o:
        cost_upd["slippage_pct"] = max(s.costs.slippage_pct, o["slippage_pct"])
    if symbol:
        sym = (o.get("symbols") or {}).get(symbol, {})
        if "min_volume_ratio" in sym:
            strat_upd["min_volume_ratio"] = max(s.strategy.min_volume_ratio, sym["min_volume_ratio"])
    return s.model_copy(update={
        "strategy": s.strategy.model_copy(update=strat_upd),
        "costs": s.costs.model_copy(update=cost_upd),
    })


def trend_filter_on(store: Store, symbol: str) -> bool:
    return bool(((overrides(store).get("symbols") or {}).get(symbol) or {}).get("trend_filter"))


def review_day(store: Store, s: Settings, day: date, mode: str, capital: float,
               risk_history: list[str] | None = None, watchlist: dict | None = None) -> dict:
    trades = [t for t in store.trades(day=day.isoformat(), mode=mode) if t["mode"] == mode]
    trades.sort(key=lambda t: t["entry_ts"])
    from .models import Trade
    m = summarize([Trade(**t) for t in trades]) if trades else summarize([])
    o = overrides(store)
    o.setdefault("symbols", {})
    findings: list[dict] = []
    ctx = {p["symbol"]: p.get("context", {}) for p in (watchlist or {}).get("picks", [])}

    def add(title, evidence, lesson, action):
        findings.append({"mistake": title, "evidence": evidence, "lesson": lesson, "change": action})

    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t["symbol"]].append(t)

    # 1. stopped out almost immediately -> entries were chasing
    for sym, ts in by_sym.items():
        quick = [t for t in ts if t["exit_reason"] == "stop" and t.get("bars_held", 99) <= 2]
        if len(quick) >= 2:
            cur = o["symbols"].get(sym, {}).get("min_volume_ratio", s.strategy.min_volume_ratio)
            new = round(min(MAX_VOLUME_RATIO, cur + 0.2), 2)
            o["symbols"].setdefault(sym, {})["min_volume_ratio"] = new
            add(f"{sym}: stopped out within 2 bars {len(quick)} times",
                [f"{t['entry_ts'][11:16]} → {t['exit_ts'][11:16]} net ₹{t['net']}" for t in quick],
                "Entries came on weak breakouts that reversed straight away.",
                f"{sym} now needs {new}x average volume to enter (was {cur}x).")

    # 2. charges ate the profit
    if m["trades"] and m["costs"] > 0 and m["costs"] >= 0.5 * max(abs(m["gross"]), 1):
        cur = o.get("min_reward_to_cost", s.strategy.min_reward_to_cost)
        new = round(min(MAX_REWARD_TO_COST, cur + 0.5), 2)
        o["min_reward_to_cost"] = new
        add("Charges were at least half of the gross result",
            [f"gross ₹{m['gross']}, charges ₹{m['costs']}, net ₹{m['net']}"],
            "Trades were too small or too frequent for the brokerage and taxes.",
            f"A trade now needs a target worth {new}x its charges (was {cur}x).")

    # 3. traded against the daily trend and lost
    for sym, ts in by_sym.items():
        trend = ctx.get(sym, {}).get("trend")
        against = [t for t in ts if t["net"] < 0 and ((trend == "down" and t["direction"] > 0)
                                                      or (trend == "up" and t["direction"] < 0))]
        if against:
            o["symbols"].setdefault(sym, {})["trend_filter"] = True
            add(f"{sym}: lost while trading against its daily trend ({trend})",
                [f"{'long' if t['direction'] > 0 else 'short'} {t['entry_ts'][11:16]} net ₹{t['net']}" for t in against],
                "Short-term signals against the bigger trend failed.",
                f"{sym} will only be traded in the direction of its daily trend.")

    # 4. fills worse than the assumed slippage (live only)
    slips = [t["extra"]["slippage_pct"] for t in trades if t.get("extra", {}).get("slippage_pct") is not None]
    if slips and sum(slips) / len(slips) > 2 * s.costs.slippage_pct:
        avg = sum(slips) / len(slips)
        new = round(min(MAX_SLIPPAGE_PCT, avg), 3)
        o["slippage_pct"] = max(o.get("slippage_pct", 0), new)
        add("Real fills were worse than the backtests assume",
            [f"average slippage {avg:.3f}% vs assumed {s.costs.slippage_pct}%"],
            "Backtests were too optimistic about execution.",
            f"Research and backtests now assume {o['slippage_pct']}% slippage.")

    # 5. a stock that keeps losing gets a rest
    block = {k: v for k, v in (store.get("blocklist", {}) or {}).items() if v >= day.isoformat()}
    recent_days = [r for r in store.reviews(limit=3)]
    for sym, ts in by_sym.items():
        if sum(t["net"] for t in ts) >= 0:
            continue
        losing_before = sum(1 for r in recent_days if r.get("day") != day.isoformat()
                            and r.get("per_symbol", {}).get(sym, 0) < 0)
        if losing_before >= 1:
            until = (day + timedelta(days=BLOCK_DAYS + 2)).isoformat()
            block[sym] = until
            add(f"{sym}: lost money again", [f"today ₹{sum(t['net'] for t in ts):.2f}, also lost on a recent day"],
                "Repeated losses on one stock suggest the strategy doesn't suit it right now.",
                f"{sym} is benched until {until}.")

    # 6. went well — say so, and don't change anything
    if m["trades"] and m["net"] > 0 and not findings:
        findings.append({"mistake": None, "evidence": [f"net ₹{m['net']} over {m['trades']} trades"],
                         "lesson": "The plan worked; no rule changes.", "change": None})
    if not trades:
        findings.append({"mistake": None, "evidence": ["no trades"],
                         "lesson": "No setups met every rule today. Sitting out is allowed.", "change": None})

    store.put("overrides", o)
    store.put("blocklist", block)
    review = {
        "mode": mode,
        "capital": capital,
        "summary": m,
        "per_symbol": {k: round(sum(t["net"] for t in v), 2) for k, v in by_sym.items()},
        "findings": findings,
        "risk_events": risk_history or [],
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
    }
    store.save_review(day.isoformat(), review)
    store.save_day(day.isoformat(), mode, capital, m["net"], m["trades"])
    return review


def live_gate_status(store: Store, s: Settings) -> dict:
    """Live trading unlocks only after enough profitable paper days (net of costs)."""
    paper = store.days(mode="paper")
    traded = [d for d in paper if d["trades"] > 0]
    net = round(sum(d["net"] for d in paper), 2)
    ok_days = len(traded) >= s.live_gate.min_paper_days
    ok_net = net > 0 or not s.live_gate.require_positive_net
    unlocked = (ok_days and ok_net) or s.live_gate.i_accept_the_risk
    return {
        "unlocked": unlocked,
        "paper_days_traded": len(traded),
        "paper_days_needed": s.live_gate.min_paper_days,
        "paper_net": net,
        "message": ("Live trading unlocked." if unlocked else
                    f"Paper-trade first: {len(traded)}/{s.live_gate.min_paper_days} days with trades, "
                    f"net ₹{net} (needs to be positive)."),
    }
