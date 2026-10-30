from datetime import timedelta

from conftest import DAY, at
from tradebot.backtest import run_backtest
from tradebot.research import History, research, split_days
from tradebot.replay import ManualClock, ReplayMarketData


def bars(store, settings, sym="AAA"):
    md = ReplayMarketData(store, ManualClock(at(16, 0)))
    return md.candles(sym, 5, at(9, 0) - timedelta(days=40), at(16, 0))


def test_backtest_is_net_of_costs_and_squares_off(store, settings):
    b = bars(store, settings)
    res = run_backtest(b, "AAA", settings, 2000)
    assert res.trades, "synthetic data should produce some trades"
    for t in res.trades:
        assert abs(t.net - (t.gross - t.costs)) < 0.02
        assert t.costs > 0
        assert t.exit_ts[11:16] <= "15:00"
        assert t.entry_ts[11:16] >= "10:00"
    m = res.metrics
    assert set(m) >= {"net", "costs", "win_rate", "profit_factor", "max_drawdown"}


def test_min_reward_to_cost_filters_trades(store, settings):
    b = bars(store, settings)
    loose = run_backtest(b, "AAA", settings, 2000, settings.strategy.model_copy(update={"min_reward_to_cost": 0}))
    strict = run_backtest(b, "AAA", settings, 2000, settings.strategy.model_copy(update={"min_reward_to_cost": 50}))
    assert len(strict.trades) < len(loose.trades)


def test_walk_forward_split_has_no_overlap(store, settings):
    train, test = split_days(bars(store, settings), 0.3)
    assert train.index.max() < test.index.min()


def test_research_produces_explained_watchlist(store, settings):
    clock = ManualClock(at(20, 0, DAY - timedelta(days=1)))
    h = History(ReplayMarketData(store, clock), store, cache=False)
    res = research(h, store, settings, clock.now(), capital=2000)
    assert len(res["picks"]) + len(res["rejected"]) == 3
    for p in res["picks"]:
        assert p["train"]["net"] > 0 and p["test"]["net"] > 0
        assert p["reasons"]
    for r in res["rejected"]:
        assert r["reason"]
    assert store.get("watchlist") == res


def test_research_respects_price_and_blocklist(store, settings):
    store.put("blocklist", {"BBB": "2099-01-01"})
    clock = ManualClock(at(20, 0))
    h = History(ReplayMarketData(store, clock), store, cache=False)
    res = research(h, store, settings, clock.now(), capital=200)   # AAA (~300) too expensive
    reasons = {r["symbol"]: r["reason"] for r in res["rejected"]}
    assert "too high" in reasons["AAA"]
    assert "blocked" in reasons["BBB"]
