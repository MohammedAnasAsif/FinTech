import sys
from datetime import date, datetime, time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradebot.clock import IST, MarketCalendar  # noqa: E402
from tradebot.config import Settings  # noqa: E402
from tradebot.replay import seed_synthetic  # noqa: E402
from tradebot.store import Store  # noqa: E402

DAY = date(2026, 10, 29)  # a Thursday, not a holiday


@pytest.fixture
def settings(tmp_path):
    s = Settings(data_dir=str(tmp_path), data_source="replay")
    s.research.universe = ["AAA", "BBB", "CCC"]
    s.research.min_avg_turnover_cr = 0
    return s


@pytest.fixture
def store(settings):
    st = Store(settings.data_path / "t.db")
    cal = MarketCalendar(settings.market, set())
    days = cal.previous_trading_days(DAY, 30) + [DAY]
    seed_synthetic(st, {"AAA": 300.0, "BBB": 150.0, "CCC": 90.0}, days)
    return st


def at(h, m, d=DAY):
    return datetime.combine(d, time(h, m), tzinfo=IST)
