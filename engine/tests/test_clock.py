from datetime import date

from conftest import at
from tradebot.clock import MarketCalendar, Phase
from tradebot.config import MarketSettings


def test_phases():
    cal = MarketCalendar(MarketSettings(), {date(2026, 11, 10)})
    assert cal.phase(at(9, 0)) is Phase.CLOSED
    assert cal.phase(at(9, 30)) is Phase.PRE_TRADE
    assert cal.phase(at(10, 0)) is Phase.ENTRY_WINDOW
    assert cal.phase(at(14, 50)) is Phase.EXIT_ONLY
    assert cal.phase(at(15, 0)) is Phase.AFTER_SQUARE_OFF
    assert cal.phase(at(11, 0, date(2026, 11, 10))) is Phase.CLOSED   # holiday
    assert cal.phase(at(11, 0, date(2026, 10, 31))) is Phase.CLOSED   # Saturday
    assert cal.next_trading_day(date(2026, 11, 9)) == date(2026, 11, 11)


def test_holiday_file_loads():
    from pathlib import Path
    from tradebot.clock import load_holidays
    h = load_holidays(Path(__file__).resolve().parents[1] / "holidays.yaml")
    assert date(2026, 12, 25) in h and len(h) == 16
