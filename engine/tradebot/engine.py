"""The trading engine: one loop that follows the daily timetable.

  night (20:00)      research -> tomorrow's watchlist
  morning            you set today's capital from the app (Start)
  10:00 - 14:45      trade the watchlist; manage stops/targets
  any time           lose ₹500 today (open losses included) -> close everything, bench the losers,
                     analyse past + today's data for tomorrow, NO more trades today
  any time           Pause (a break), Stop for today, or Kill switch from the app
  14:45 - 15:00      no new trades, manage exits
  15:00              square off everything
  15:10              self-review: what went wrong, what changes tomorrow
"""
from __future__ import annotations

import logging
import threading
import traceback
from datetime import date, datetime, timedelta
from enum import Enum

import pandas as pd

from .backtest import worth_it
from .broker.base import Executor, MarketData
from .clock import Clock, MarketCalendar, Phase
from .config import Settings
from .costs import side_costs
from .models import OrderStatus, Position, Side, Trade
from .research import History, research
from .review import effective_settings, live_gate_status, review_day, trend_filter_on
from .risk import DayRisk, LimitAction
from .store import Store
from .strategy import compute_signals, describe_entry

log = logging.getLogger(__name__)


class State(str, Enum):
    IDLE = "IDLE"                # waiting for you to set today's capital
    WAITING = "WAITING"          # capital set, waiting for trade_start
    TRADING = "TRADING"
    PAUSED = "PAUSED"            # your break: no new trades, open trades still protected
    COOLDOWN = "COOLDOWN"        # automatic break after a losing streak
    RESEARCHING = "RESEARCHING"  # cycle stop hit: re-studying before coming back
    DONE = "DONE"                # finished for the day
    KILLED = "KILLED"            # kill switch: flat and locked until tomorrow


class Engine:
    def __init__(self, settings: Settings, store: Store, clock: Clock, calendar: MarketCalendar,
                 md: MarketData, executor: Executor, cache_history: bool = True):
        self.s = settings
        self.store = store
        self.clock = clock
        self.cal = calendar
        self.md = md
        self.ex = executor
        self.history = History(md, store, cache=cache_history)
        self.lock = threading.RLock()
        self.state = State.IDLE
        self.day: date | None = None
        self.risk: DayRisk | None = None
        self.positions: dict[str, Position] = {}
        self.last_bar: dict[str, pd.Timestamp] = {}
        self.ltp: dict[str, float] = {}
        self.exit_failures: dict[str, int] = {}
        self.busy: str | None = None
        self.last_error: str | None = None
        self.reviewed: str | None = store.get("reviewed_day")
        self.researched: str | None = store.get("researched_day")
        self._stop = threading.Event()

    # ================= public controls (called from the API) =================
    def start_day(self, capital: float) -> dict:
        with self.lock:
            now = self.clock.now()
            if not self.cal.is_trading_day(now.date()):
                return self._err("Market is closed today.")
            if self.state is State.KILLED:
                return self._err("Kill switch is on for today. It resets tomorrow.")
            if self.risk is not None:
                return self._err("Today's capital is already set.")
            if now.timetz().replace(tzinfo=None) >= self.s.market.last_entry:
                return self._err("Too late to start today.")
            if capital <= 0:
                return self._err("Capital must be positive.")
            if self.ex.is_live:
                gate = live_gate_status(self.store, self.s)
                if not gate["unlocked"]:
                    return self._err(gate["message"])
                cash = self.ex.available_cash()
                if cash is not None and cash < capital:
                    return self._err(f"Only ₹{cash:.2f} available in your Angel One account.")
            self.day = now.date()
            self.risk = DayRisk(capital=capital, cfg=self.s.risk)
            self.state = State.WAITING
            self.event(f"Started for today with ₹{capital:.0f} ({self.mode} mode). "
                       f"Watching: {', '.join(self.watch_symbols()) or 'nothing yet'}.")
            return {"ok": True}

    def pause(self) -> dict:
        with self.lock:
            if self.state not in (State.TRADING, State.WAITING, State.COOLDOWN):
                return self._err(f"Can't pause while {self.state.value}.")
            self.state = State.PAUSED
            self.event("Paused: no new trades. Open trades keep their stop and target.")
            return {"ok": True}

    def resume(self) -> dict:
        with self.lock:
            if self.state is not State.PAUSED:
                return self._err("Not paused.")
            self.state = State.TRADING
            self.event("Resumed.")
            return {"ok": True}

    def stop_day(self) -> dict:
        with self.lock:
            if self.risk is None or self.state in (State.DONE, State.KILLED):
                return self._err("Nothing to stop.")
            self._flatten("stopped by you")
            self.risk.end_day("stopped by you")
            self.state = State.DONE
            self.event("Stopped for today by you. All positions closed.")
            return {"ok": True}

    def kill(self) -> dict:
        with self.lock:
            self._flatten("kill switch")
            if self.risk:
                self.risk.end_day("kill switch")
            self.state = State.KILLED
            self.day = self.clock.now().date()
            self.event("KILL SWITCH: everything closed, trading locked until tomorrow.", "warning")
            return {"ok": True}

    def run_research_now(self) -> dict:
        if self.busy:
            return self._err(f"Busy: {self.busy}")
        threading.Thread(target=self._nightly_research, daemon=True).start()
        return {"ok": True}

    # ================= status =================
    @property
    def mode(self) -> str:
        return "live" if self.ex.is_live else "paper"

    def watchlist(self) -> dict:
        return self.store.get("watchlist", {}) or {}

    def watch_symbols(self) -> list[str]:
        return [p["symbol"] for p in self.watchlist().get("picks", [])]

    def status(self) -> dict:
        now = self.clock.now()
        unreal = sum(p.unrealized(self.ltp.get(p.symbol, p.entry_price)) for p in self.positions.values())
        return {
            "now": now.isoformat(timespec="seconds"),
            "mode": self.mode,
            "state": self.state.value,
            "busy": self.busy,
            "phase": self.cal.phase(now).value,
            "trading_day": self.cal.is_trading_day(now.date()),
            "risk": self.risk.snapshot() if self.risk else None,
            "unrealized": round(unreal, 2),
            "day_pnl": round((self.risk.realized_total if self.risk else 0) + unreal, 2),
            "positions": [{
                "symbol": p.symbol, "direction": "long" if p.direction > 0 else "short", "qty": p.qty,
                "entry": p.entry_price, "ltp": self.ltp.get(p.symbol), "stop": round(p.stop, 2),
                "target": round(p.target, 2), "unrealized": round(p.unrealized(self.ltp.get(p.symbol, p.entry_price)), 2),
                "since": p.entry_ts.isoformat(timespec="minutes"), "reason": p.entry_reason,
            } for p in self.positions.values()],
            "watching": self.watch_symbols(),
            "live_gate": live_gate_status(self.store, self.s),
            "schedule": {k: v.strftime("%H:%M") for k, v in {
                "trade_start": self.s.market.trade_start, "last_entry": self.s.market.last_entry,
                "square_off": self.s.market.square_off, "review_at": self.s.market.review_at,
                "research_at": self.s.market.research_at}.items()},
            "last_error": self.last_error,
        }

    # ================= main loop =================
    def run_forever(self, tick_seconds: float = 5.0) -> None:
        if not self.watchlist():
            self._nightly_research()
        while not self._stop.is_set():
            try:
                self.tick()
                self.last_error = None
            except Exception as e:  # noqa: BLE001 — keep the loop alive, report the error
                self.last_error = f"{type(e).__name__}: {e}"
                log.error("tick failed: %s", traceback.format_exc())
                self.event(f"Error: {self.last_error}", "error")
            self._stop.wait(tick_seconds)

    def stop(self) -> None:
        self._stop.set()

    def tick(self) -> None:
        now = self.clock.now()
        t = now.timetz().replace(tzinfo=None)
        today = now.date()
        with self.lock:
            if self.day != today and self.state is not State.IDLE and not self.positions:
                self._new_day()
            phase = self.cal.phase(now)
            if self.risk is not None and self.state is not State.KILLED:
                self._trading_tick(now, phase)
            run_review = (self.risk is not None and self.day == today and t >= self.s.market.review_at
                          and self.reviewed != today.isoformat() and not self.positions)
            run_research = t >= self.s.market.research_at and self.researched != today.isoformat()
        if run_review:
            self._review(today)
        if run_research:
            self._nightly_research()

    def _new_day(self) -> None:
        self.state, self.risk, self.day = State.IDLE, None, None
        self.last_bar.clear()
        self.exit_failures.clear()

    def _trading_tick(self, now: datetime, phase: Phase) -> None:
        r = self.risk
        assert r is not None
        if self.positions:
            self._refresh_ltp()

        # square-off time: close everything, the trading day is over
        if now.timetz().replace(tzinfo=None) >= self.s.market.square_off or not self.cal.is_trading_day(now.date()):
            if self.positions:
                self._flatten("square-off")
            if self.state not in (State.DONE,):
                r.end_day("market square-off time")
                self.state = State.DONE
                self.event(f"Square-off done. Day result: ₹{r.realized_total:.2f}.")
            return
        if self.state is State.DONE or phase is Phase.CLOSED:
            return

        # stops and targets
        for sym, p in list(self.positions.items()):
            px = self.ltp.get(sym)
            if px is None:
                continue
            if (p.direction > 0 and px <= p.stop) or (p.direction < 0 and px >= p.stop):
                self._exit(sym, px, "stop")
            elif (p.direction > 0 and px >= p.target) or (p.direction < 0 and px <= p.target):
                self._exit(sym, px, "target")

        # loss limits
        unreal = sum(p.unrealized(self.ltp.get(p.symbol, p.entry_price)) for p in self.positions.values())
        # (while re-researching the cycle's loss is already booked and positions are flat)
        action = LimitAction.NONE if self.state is State.RESEARCHING else r.check_limits(unreal)
        if action is LimitAction.DAY_STOP:
            self._flatten("daily loss limit")
            r.end_day("loss limit reached")
            self.state = State.DONE
            self.event(f"Loss limit reached (₹{r.realized_total:.2f}). Everything is closed and there are "
                       f"no more trades today.", "warning")
            self._loss_analysis(now)
            return
        if action is LimitAction.CYCLE_STOP:
            self._flatten("cycle loss limit")
            r.stop_cycle(now)
            self.state = State.RESEARCHING
            self.event(f"Cycle {r.cycle} lost ₹{-r.cycle_realized:.2f}. Closing out, studying today's "
                       f"moves, earliest comeback {r.comeback_after:%H:%M}.", "warning")
            self._midday_research(now)
            return

        # automatic states
        if self.state is State.WAITING and phase is Phase.ENTRY_WINDOW:
            self.state = State.TRADING
            self.event("Trading window open." if self.watch_symbols() else
                       "Trading window open, but the watchlist is empty: sitting out unless research finds something.")
        if self.state is State.COOLDOWN and r.cooldown_until and now >= r.cooldown_until:
            self.state = State.TRADING
            self.event("Break over, back to trading.")
        if self.state is State.RESEARCHING and r.comeback_after and now >= r.comeback_after:
            if phase is Phase.ENTRY_WINDOW and self.watch_symbols():
                r.start_next_cycle()
                self.state = State.TRADING
                self.event(f"Coming back: cycle {r.cycle} of {self.s.risk.max_cycles}.")
            else:
                r.end_day("no good setups after re-research")
                self.state = State.DONE
                self.event("Re-research found nothing worth trading. Done for today.")
                return

        # bar-based decisions
        if phase in (Phase.ENTRY_WINDOW, Phase.EXIT_ONLY):
            self._on_bars(now, allow_entries=(phase is Phase.ENTRY_WINDOW and self.state is State.TRADING))

    def _on_bars(self, now: datetime, allow_entries: bool) -> None:
        picks = {p["symbol"]: p for p in self.watchlist().get("picks", [])}
        symbols = set(picks) | set(self.positions)
        step = timedelta(minutes=self.s.strategy.interval_minutes)
        for sym in symbols:
            pick = picks.get(sym, {})
            s = effective_settings(self.s, self.store, sym)
            strat = s.strategy.model_copy(update=pick.get("params", {}))
            bars = self.md.candles(sym, strat.interval_minutes, now - timedelta(days=6), now)
            if bars is None or bars.empty:
                continue
            bars = bars[bars.index + step <= now]           # closed bars only
            if len(bars) < strat.slow_ema + 5:
                continue
            last_ts = bars.index[-1]
            if self.last_bar.get(sym) == last_ts:
                continue
            self.last_bar[sym] = last_ts
            sig = compute_signals(bars, strat).iloc[-1]
            pos = self.positions.get(sym)
            if pos:
                if (pos.direction > 0 and sig["exit_long"]) or (pos.direction < 0 and sig["exit_short"]):
                    self._exit(sym, self.ltp.get(sym) or float(sig["close"]), "signal reversed")
                continue
            if not allow_entries or sym not in picks or last_ts.date() != now.date():
                continue
            direction = 1 if sig["enter_long"] else (-1 if sig["enter_short"] else 0)
            if not direction:
                continue
            trend = pick.get("context", {}).get("trend")
            if trend_filter_on(self.store, sym) and ((trend == "down" and direction > 0) or (trend == "up" and direction < 0)):
                self.event(f"{sym}: skipped a {'long' if direction > 0 else 'short'} against the daily trend.")
                continue
            self._enter(sym, direction, sig, strat, s, now)

    def _enter(self, sym: str, direction: int, sig: pd.Series, strat, s: Settings, now: datetime) -> None:
        r = self.risk
        ok, why = r.can_enter(now, len(self.positions))
        if not ok:
            return
        ref = self.md.ltp(sym) or float(sig["close"])
        stop_dist, tgt_dist = strat.stop_atr * float(sig["atr"]), strat.target_atr * float(sig["atr"])
        qty = r.position_size(ref, ref - direction * stop_dist)
        if qty <= 0:
            self.event(f"{sym}: signal, but the position would be 0 shares at ₹{ref:.2f}.")
            return
        if not worth_it(ref, qty, tgt_dist, strat, s.costs):
            self.event(f"{sym}: signal skipped — target profit too small compared with charges.")
            return
        side = Side.BUY if direction > 0 else Side.SELL
        fill = self.ex.place(sym, side, qty, ref, now)
        if fill.status is not OrderStatus.FILLED or fill.qty <= 0:
            self.event(f"{sym}: entry order not filled ({fill.message or fill.status.value}).", "warning")
            return
        px = fill.price
        self.positions[sym] = Position(
            symbol=sym, direction=direction, qty=fill.qty, entry_price=px, entry_ts=now,
            stop=px - direction * stop_dist, target=px + direction * tgt_dist, cycle=r.cycle,
            entry_reason=describe_entry(sig, direction, strat),
            entry_costs=side_costs(px * fill.qty, side is Side.BUY, s.costs), ref_price=ref,
        )
        self.ltp[sym] = px
        self.event(f"{'BUY' if direction > 0 else 'SELL SHORT'} {fill.qty} {sym} @ ₹{px:.2f} "
                   f"(stop {px - direction * stop_dist:.2f}, target {px + direction * tgt_dist:.2f})")

    def _exit(self, sym: str, ref: float, reason: str) -> bool:
        p = self.positions.get(sym)
        if not p:
            return True
        now = self.clock.now()
        side = Side.SELL if p.direction > 0 else Side.BUY
        fill = self.ex.place(sym, side, p.qty, ref, now)
        if fill.status is not OrderStatus.FILLED or fill.qty <= 0:
            n = self.exit_failures.get(sym, 0) + 1
            self.exit_failures[sym] = n
            level = "error" if n >= 3 else "warning"
            self.event(f"{sym}: exit order failed ({fill.message or 'not filled'}), attempt {n}."
                       + (" CHECK YOUR ANGEL ONE APP." if n >= 3 else ""), level)
            return False
        if fill.qty < p.qty:  # partial exit: keep the rest open
            p.qty -= fill.qty
            self.event(f"{sym}: only {fill.qty} shares exited, {p.qty} still open.", "warning")
            return False
        self.exit_failures.pop(sym, None)
        del self.positions[sym]
        costs = p.entry_costs + side_costs(fill.price * p.qty, side is Side.BUY, self.s.costs)
        gross = (fill.price - p.entry_price) * p.qty * p.direction
        ref_in = p.ref_price or p.entry_price
        slip_in = abs(p.entry_price - ref_in) / ref_in * 100 if ref_in else 0
        slip_out = abs(fill.price - ref) / ref * 100 if ref else 0
        trade = Trade(
            day=now.date().isoformat(), symbol=sym, direction=p.direction, qty=p.qty,
            entry_ts=p.entry_ts.isoformat(timespec="seconds"), entry_price=round(p.entry_price, 2),
            exit_ts=now.isoformat(timespec="seconds"), exit_price=round(fill.price, 2),
            gross=round(gross, 2), costs=round(costs, 2), net=round(gross - costs, 2),
            entry_reason=p.entry_reason, exit_reason=reason, cycle=p.cycle, mode=self.mode,
            bars_held=int((now - p.entry_ts).total_seconds() // 60 // self.s.strategy.interval_minutes),
            extra={"slippage_pct": round((slip_in + slip_out) / 2, 4)} if self.ex.is_live else {},
        )
        self.store.save_trade(trade)
        self.event(f"EXIT {sym} @ ₹{fill.price:.2f} ({reason}): net ₹{trade.net:.2f} after ₹{trade.costs:.2f} charges")
        if self.risk:
            msg = self.risk.on_trade_closed(trade, now)
            if msg and self.state is State.TRADING:
                self.state = State.COOLDOWN
                self.event(msg)
        return True

    def _flatten(self, reason: str) -> None:
        self._refresh_ltp()
        for sym in list(self.positions):
            self._exit(sym, self.ltp.get(sym) or self.positions[sym].entry_price, reason)

    def _refresh_ltp(self) -> None:
        for sym in self.positions:
            px = self.md.ltp(sym)
            if px:
                self.ltp[sym] = px

    # ================= research & review =================
    def _midday_research(self, now: datetime) -> None:
        """After a cycle stop: re-run research including today's bars, benching today's losers."""
        losers = {t["symbol"] for t in self.store.trades(day=now.date().isoformat(), mode=self.mode)
                  if t["net"] < 0 and t.get("cycle") == self.risk.cycle}
        self.busy = "re-researching after cycle stop"
        try:
            res = research(self.history, self.store, self.s, now, capital=self.risk.capital,
                           exclude=losers, label="midday")
            self.event(f"Re-research: {res['note']} Benched for today: {', '.join(sorted(losers)) or 'none'}.")
        finally:
            self.busy = None

    def _loss_analysis(self, now: datetime) -> None:
        """After the loss cap: bench today's losing stocks for tomorrow and re-plan using
        past + today's data. The bot does NOT trade again today."""
        day = now.date()
        losers = sorted({t["symbol"] for t in self.store.trades(day=day.isoformat(), mode=self.mode)
                         if t["net"] < 0})
        until = self.cal.next_trading_day(day).isoformat()
        block = self.store.get("blocklist", {}) or {}
        for sym in losers:
            block[sym] = max(block.get(sym, ""), until)
        self.store.put("blocklist", block)
        self.busy = "analysing today's losses"
        try:
            res = research(self.history, self.store, self.s, now, capital=self.risk.capital,
                           exclude=set(losers), label="after-loss")
            self.event(f"Analysis for tomorrow: {res['note']} Benched until {until}: "
                       f"{', '.join(losers) or 'none'}. Full review at "
                       f"{self.s.market.review_at.strftime('%H:%M')}.")
        except Exception as e:  # noqa: BLE001
            self.event(f"Analysis after the loss failed: {e}", "error")
        finally:
            self.busy = None

    def _nightly_research(self) -> None:
        now = self.clock.now()
        self.busy = "overnight research"
        self.event("Overnight research started.")
        try:
            res = research(self.history, self.store, self.s, now,
                           capital=self.store.get("last_capital") or self.s.research.assumed_capital)
            self.researched = now.date().isoformat()
            self.store.put("researched_day", self.researched)
            self.event(f"Research done: {res['note']} Watchlist: "
                       f"{', '.join(p['symbol'] for p in res['picks']) or 'empty'}.")
        except Exception as e:  # noqa: BLE001
            self.event(f"Research failed: {e}", "error")
        finally:
            self.busy = None

    def _review(self, day: date) -> None:
        self.busy = "post-market review"
        try:
            with self.lock:
                hist = list(self.risk.history) if self.risk else []
                capital = self.risk.capital if self.risk else 0
            rev = review_day(self.store, self.s, day, self.mode, capital, hist, self.watchlist())
            self.store.put("last_capital", capital)
            self.reviewed = day.isoformat()
            self.store.put("reviewed_day", self.reviewed)
            changes = [f["change"] for f in rev["findings"] if f.get("change")]
            self.event(f"Review done: net ₹{rev['summary']['net']} over {rev['summary']['trades']} trades. "
                       + (f"{len(changes)} rule change(s) for tomorrow." if changes else "No rule changes."))
        finally:
            self.busy = None

    # ================= helpers =================
    def event(self, message: str, level: str = "info") -> None:
        log.log(logging.WARNING if level != "info" else logging.INFO, message)
        self.store.log(message, level, self.clock.now())

    def _err(self, message: str) -> dict:
        return {"ok": False, "error": message}
