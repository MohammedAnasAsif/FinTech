from datetime import timedelta

from conftest import DAY, at
from tradebot.broker.base import PaperExecutor
from tradebot.clock import MarketCalendar
from tradebot.engine import Engine, State
from tradebot.replay import ManualClock, ReplayMarketData
from tradebot.research import History, research


def make_engine(store, settings, start=at(9, 30)):
    # permissive strategy so the synthetic day produces trades to exercise the engine
    settings.strategy.min_volume_ratio = 0
    settings.strategy.use_vwap_filter = False
    settings.strategy.min_reward_to_cost = 0
    settings.strategy.allow_short = True
    clock = ManualClock(start)
    md = ReplayMarketData(store, clock)
    eng = Engine(settings, store, clock, MarketCalendar(settings.market, set()), md,
                 PaperExecutor(settings.costs), cache_history=False)
    # last night's research, with a permissive filter so the day has something to trade
    settings.research.min_trades = 1
    research(History(md, store, cache=False), store, settings, at(20, 0, DAY - timedelta(days=1)), 2000)
    store.put("watchlist", {"picks": [{"symbol": s, "params": {"fast_ema": 5, "slow_ema": 21}, "context": {}}
                                      for s in ("AAA", "BBB", "CCC")]})
    return eng, clock


def run_until(eng, clock, h, m, step=1):
    while clock.now() < at(h, m):
        clock.advance(minutes=step)
        eng.tick()


def test_full_day_paper(store, settings):
    eng, clock = make_engine(store, settings)
    assert eng.start_day(2000)["ok"]
    assert eng.state is State.WAITING
    run_until(eng, clock, 10, 1)
    assert eng.state in (State.TRADING, State.COOLDOWN)
    run_until(eng, clock, 15, 1)
    assert not eng.positions, "everything must be closed by square-off"
    assert eng.state is State.DONE
    run_until(eng, clock, 15, 12)
    trades = store.trades(day=DAY.isoformat())
    assert trades, "the permissive settings should have produced trades"
    reviews = store.reviews()
    assert reviews and reviews[0]["day"] == DAY.isoformat()
    for t in store.trades(day=DAY.isoformat()):
        assert t["mode"] == "paper"
        assert "10:00" <= t["entry_ts"][11:16] < "14:45"


def test_cycle_stop_researches_then_ends_day(store, settings):
    settings.risk.session_loss_limit = 5        # almost any loss ends a cycle (charges alone are ~₹12)
    settings.risk.daily_loss_limit = 10_000
    settings.risk.max_cycles = 2
    settings.risk.comeback_wait_minutes = 10
    settings.strategy.min_reward_to_cost = 0
    eng, clock = make_engine(store, settings)
    eng.start_day(2000)
    seen = set()
    while clock.now() < at(15, 5):
        clock.advance(minutes=1)
        eng.tick()
        seen.add(eng.state)
    events = " ".join(e["message"] for e in store.events(limit=1000))
    losses = [t for t in store.trades(day=DAY.isoformat()) if t["net"] < 0]
    assert losses, "synthetic day should include a losing trade"
    assert State.RESEARCHING in seen
    assert "Cycle 1 lost" in events
    assert eng.risk.cycle <= 2
    assert not eng.positions


def test_pause_blocks_entries_and_kill_flattens(store, settings):
    eng, clock = make_engine(store, settings)
    eng.start_day(2000)
    run_until(eng, clock, 10, 1)
    assert eng.pause()["ok"] and eng.state is State.PAUSED
    n = len(store.trades(day=DAY.isoformat()))
    opened = len(eng.positions)
    run_until(eng, clock, 11, 0)
    assert len(eng.positions) <= opened                 # nothing new while paused
    assert eng.resume()["ok"]
    run_until(eng, clock, 12, 0)
    assert eng.kill()["ok"]
    assert not eng.positions and eng.state is State.KILLED
    assert not eng.start_day(2000)["ok"]
    assert len(store.trades(day=DAY.isoformat())) >= n


def test_refuses_bad_starts(store, settings):
    eng, clock = make_engine(store, settings, start=at(14, 50))
    assert not eng.start_day(2000)["ok"]                 # too late
    eng2, _ = make_engine(store, settings, start=at(10, 0, DAY + timedelta(days=2)))  # Saturday
    assert not eng2.start_day(2000)["ok"]
