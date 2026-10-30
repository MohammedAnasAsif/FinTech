"""Indian equity intraday transaction costs.

Every backtest, paper trade and research score is net of these. Small accounts that
trade often lose most of their edge here, so the bot is built around this number.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import CostSettings


@dataclass
class CostBreakdown:
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    ipft: float
    gst: float

    @property
    def total(self) -> float:
        return self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.ipft + self.gst


def order_brokerage(value: float, c: CostSettings) -> float:
    return max(c.brokerage_min, min(c.brokerage_flat, value * c.brokerage_pct / 100))


def round_trip_costs(buy_value: float, sell_value: float, c: CostSettings) -> CostBreakdown:
    """Charges for one buy order and one sell order (in either order — shorts included)."""
    turnover = buy_value + sell_value
    brokerage = order_brokerage(buy_value, c) + order_brokerage(sell_value, c)
    stt = sell_value * c.stt_sell_pct / 100
    exchange = turnover * c.exchange_pct / 100
    sebi = turnover * c.sebi_per_crore / 1e7
    stamp = buy_value * c.stamp_buy_pct / 100
    ipft = turnover * c.ipft_pct / 100
    gst = (brokerage + exchange + sebi + ipft) * c.gst_pct / 100
    return CostBreakdown(brokerage, stt, exchange, sebi, stamp, ipft, gst)


def side_costs(value: float, is_buy: bool, c: CostSettings) -> float:
    """Charges for a single order, used to book costs as each leg fills."""
    brokerage = order_brokerage(value, c)
    exchange = value * c.exchange_pct / 100
    sebi = value * c.sebi_per_crore / 1e7
    ipft = value * c.ipft_pct / 100
    gst = (brokerage + exchange + sebi + ipft) * c.gst_pct / 100
    tax = value * (c.stamp_buy_pct if is_buy else c.stt_sell_pct) / 100
    return brokerage + exchange + sebi + ipft + gst + tax


def slip(price: float, is_buy: bool, c: CostSettings) -> float:
    """Assumed fill price after slippage (worse for us in both directions)."""
    s = price * c.slippage_pct / 100
    return price + s if is_buy else price - s
