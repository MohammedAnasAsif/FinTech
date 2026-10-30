from datetime import timedelta

from conftest import at
from tradebot.config import RiskSettings
from tradebot.models import Trade
from tradebot.risk import DayRisk, LimitAction


def trade(net):
    return Trade("d", "X", 1, 1, "", 1, "", 1, net, 0, net, "", "")


def test_cycle_then_day_stop():
    r = DayRisk(capital=2000, cfg=RiskSettings())
    r.on_trade_closed(trade(-300), at(10, 30))
    assert r.check_limits(0) is LimitAction.NONE
    assert r.check_limits(-250) is LimitAction.CYCLE_STOP
    r.on_trade_closed(trade(-250), at(10, 40))
    r.stop_cycle(at(10, 40))
    ok, why = r.can_enter(at(10, 50), 0)
    assert not ok and "research" in why
    assert r.can_enter(at(11, 15), 0)[0]
    r.start_next_cycle()
    assert r.cycle == 2 and r.cycle_realized == 0
    # second cycle is the last one -> a cycle loss ends the day
    assert r.check_limits(-500) is LimitAction.DAY_STOP


def test_daily_cap_beats_cycles():
    r = DayRisk(capital=2000, cfg=RiskSettings(session_loss_limit=800, daily_loss_limit=600, max_cycles=5))
    assert r.check_limits(-600) is LimitAction.DAY_STOP


def test_cooldown_after_streak():
    r = DayRisk(capital=2000, cfg=RiskSettings(cooldown_after_losses=2, cooldown_minutes=15))
    assert r.on_trade_closed(trade(-10), at(10, 0)) is None
    assert r.on_trade_closed(trade(-10), at(10, 5)) is not None
    assert not r.can_enter(at(10, 10), 0)[0]
    assert r.can_enter(at(10, 5) + timedelta(minutes=16), 0)[0]


def test_position_size_no_leverage_and_risk_cap():
    r = DayRisk(capital=2000, cfg=RiskSettings(risk_per_trade_pct=1.5))
    assert r.position_size(price=400, stop=399) == 5      # cash limit: 2000/400
    assert r.position_size(price=100, stop=95) == 6       # risk limit: 30/5
    assert r.position_size(price=2500, stop=2490) == 0    # can't afford one share


def test_limits_on_open_positions():
    r = DayRisk(capital=2000, cfg=RiskSettings(max_open_positions=1, max_trades_per_day=1))
    assert not r.can_enter(at(10, 0), 1)[0]
    r.on_trade_closed(trade(5), at(10, 0))
    assert not r.can_enter(at(10, 5), 0)[0]
