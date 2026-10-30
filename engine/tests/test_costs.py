from tradebot.config import CostSettings
from tradebot.costs import order_brokerage, round_trip_costs


def test_brokerage_rules():
    c = CostSettings()
    assert order_brokerage(100_000, c) == 20          # capped at ₹20
    assert order_brokerage(10_000, c) == 10           # 0.1%
    assert order_brokerage(1_000, c) == 5             # minimum ₹5


def test_round_trip_small_trade_is_expensive():
    c = CostSettings()
    b = round_trip_costs(2000, 2010, c)
    # ₹5 + ₹5 brokerage + 18% GST alone is ~₹11.8 on a ₹10 move
    assert 12 < b.total < 13.5
    assert b.stt == 2010 * 0.025 / 100
    assert b.stamp == 2000 * 0.003 / 100
