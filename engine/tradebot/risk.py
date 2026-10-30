"""Risk rules. Pure logic, no I/O, so every rule is unit-tested.

The cycle the user asked for:
  trade -> lose `session_loss_limit` in this cycle -> flatten, research, wait
  -> come back as the next cycle ... until `max_cycles` or `daily_loss_limit` ends the day.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from .config import RiskSettings
from .models import Trade


class LimitAction(str, Enum):
    NONE = "NONE"
    CYCLE_STOP = "CYCLE_STOP"   # lost the per-cycle limit: flatten and go research
    DAY_STOP = "DAY_STOP"       # daily limit or out of cycles: flatten and stop for the day


@dataclass
class DayRisk:
    capital: float
    cfg: RiskSettings
    cycle: int = 1
    realized_total: float = 0.0
    cycle_realized: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    cooldown_until: datetime | None = None
    comeback_after: datetime | None = None
    day_over: bool = False
    day_over_reason: str = ""
    history: list[str] = field(default_factory=list)

    # ---------- entries ----------
    def can_enter(self, now: datetime, open_positions: int) -> tuple[bool, str]:
        if self.day_over:
            return False, f"day over: {self.day_over_reason}"
        if self.comeback_after and now < self.comeback_after:
            return False, "researching after a cycle stop"
        if self.cooldown_until and now < self.cooldown_until:
            return False, "taking a break after a losing streak"
        if open_positions >= self.cfg.max_open_positions:
            return False, "max open positions reached"
        if self.trades_today >= self.cfg.max_trades_per_day:
            return False, "max trades for today reached"
        return True, ""

    def position_size(self, price: float, stop: float, available_cash: float | None = None) -> int:
        """Shares to buy so that hitting the stop loses about risk_per_trade_pct of capital."""
        if price <= 0:
            return 0
        cash = self.capital if available_cash is None else min(self.capital, available_cash)
        # never size a trade that could push past the remaining cycle allowance
        room = self.cfg.session_loss_limit + self.cycle_realized
        cash_qty = math.floor(cash / price) if not self.cfg.use_leverage else math.floor(cash * 5 / price)
        risk_amt = min(self.capital * self.cfg.risk_per_trade_pct / 100, max(room, 0))
        per_share = abs(price - stop)
        risk_qty = math.floor(risk_amt / per_share) if per_share > 0 else cash_qty
        return max(0, min(cash_qty, risk_qty))

    # ---------- limits ----------
    def check_limits(self, unrealized: float) -> LimitAction:
        if self.day_over:
            return LimitAction.NONE
        if self.realized_total + unrealized <= -self.cfg.daily_loss_limit:
            return LimitAction.DAY_STOP
        if self.cycle_realized + unrealized <= -self.cfg.session_loss_limit:
            return LimitAction.DAY_STOP if self.cycle >= self.cfg.max_cycles else LimitAction.CYCLE_STOP
        return LimitAction.NONE

    def on_trade_closed(self, trade: Trade, now: datetime) -> str | None:
        self.realized_total += trade.net
        self.cycle_realized += trade.net
        self.trades_today += 1
        if trade.net < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.cfg.cooldown_after_losses:
                self.consecutive_losses = 0
                self.cooldown_until = now + timedelta(minutes=self.cfg.cooldown_minutes)
                msg = f"{self.cfg.cooldown_after_losses} losses in a row: break for {self.cfg.cooldown_minutes} min"
                self.history.append(msg)
                return msg
        else:
            self.consecutive_losses = 0
        return None

    def stop_cycle(self, now: datetime) -> None:
        self.history.append(f"cycle {self.cycle} stopped at {self.cycle_realized:.2f}")
        self.comeback_after = now + timedelta(minutes=self.cfg.comeback_wait_minutes)

    def start_next_cycle(self) -> None:
        self.cycle += 1
        self.cycle_realized = 0.0
        self.consecutive_losses = 0
        self.comeback_after = None
        self.history.append(f"cycle {self.cycle} started")

    def end_day(self, reason: str) -> None:
        self.day_over = True
        self.day_over_reason = reason
        self.history.append(f"day over: {reason}")

    def snapshot(self) -> dict:
        return {
            "capital": self.capital,
            "cycle": self.cycle,
            "max_cycles": self.cfg.max_cycles,
            "realized_total": round(self.realized_total, 2),
            "cycle_realized": round(self.cycle_realized, 2),
            "cycle_loss_limit": self.cfg.session_loss_limit,
            "daily_loss_limit": self.cfg.daily_loss_limit,
            "trades_today": self.trades_today,
            "max_trades_per_day": self.cfg.max_trades_per_day,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "comeback_after": self.comeback_after.isoformat() if self.comeback_after else None,
            "day_over": self.day_over,
            "day_over_reason": self.day_over_reason,
        }
