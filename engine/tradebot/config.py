"""Settings for the engine.

Everything the bot does is driven by `config.yaml` (see config.example.yaml).
Secrets (Angel One login) live only in `.env` and are never written anywhere else.
"""
from __future__ import annotations

import os
from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class MarketSettings(BaseModel):
    timezone: str = "Asia/Kolkata"
    market_open: time = time(9, 15)
    market_close: time = time(15, 30)
    trade_start: time = time(10, 0)      # first entry allowed (skips the opening chaos)
    last_entry: time = time(14, 45)      # no new positions after this
    square_off: time = time(15, 0)       # everything is closed by this time
    review_at: time = time(15, 10)       # post-market self-review
    research_at: time = time(20, 0)      # overnight research for tomorrow
    holidays_file: str = "holidays.yaml"   # pydantic reads "HH:MM" strings into times


class RiskSettings(BaseModel):
    daily_loss_limit: float = 500.0      # THE cap: lose this much today (open losses included) -> close all, stop for the day
    session_loss_limit: float = 500.0    # advanced: per-cycle limit, only used if max_cycles > 1
    max_cycles: int = 1                  # 1 = never come back after hitting the cap (recommended)
    max_open_positions: int = 1
    max_trades_per_day: int = 6
    risk_per_trade_pct: float = 1.5      # % of today's capital risked between entry and stop
    use_leverage: bool = False           # never borrow intraday margin unless you change this
    cooldown_after_losses: int = 3       # consecutive losing trades -> take a break
    cooldown_minutes: int = 20
    comeback_wait_minutes: int = 30      # minimum wait after a cycle stop before trading again
    max_orders_per_second: float = 1.0   # far below SEBI's registration threshold


class CostSettings(BaseModel):
    """NSE equity intraday charges (Angel One schedule, checked Oct 2026). Update if they change."""
    brokerage_flat: float = 20.0
    brokerage_pct: float = 0.1           # lower of flat or pct ...
    brokerage_min: float = 5.0           # ... but at least this
    stt_sell_pct: float = 0.025
    exchange_pct: float = 0.0030699
    sebi_per_crore: float = 10.0
    stamp_buy_pct: float = 0.003
    ipft_pct: float = 0.0000001
    gst_pct: float = 18.0
    slippage_pct: float = 0.05           # assumed price slippage per fill, in backtests and paper trades


class StrategySettings(BaseModel):
    name: str = "ema_vwap"
    interval_minutes: int = 5
    fast_ema: int = 9
    slow_ema: int = 21
    atr_period: int = 14
    stop_atr: float = 1.5
    target_atr: float = 2.5
    use_vwap_filter: bool = True
    min_volume_ratio: float = 1.0        # entry bar volume vs 20-bar average
    min_reward_to_cost: float = 3.0      # skip trades whose target profit isn't at least this many times the charges
    allow_short: bool = False


class ResearchSettings(BaseModel):
    universe: list[str] = Field(default_factory=lambda: [
        "SBIN", "ITC", "TATASTEEL", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL",
        "WIPRO", "HINDALCO", "BEL", "IOC", "GAIL", "BANKBARODA",
        "PNB", "IDFCFIRSTB", "ASHOKLEY", "VEDL", "NHPC", "SAIL",
    ])
    lookback_days: int = 45              # calendar days of 5-minute history to study
    validation_fraction: float = 0.3     # newest part of history kept aside to test the tuned settings
    top_k: int = 3                       # stocks to watch tomorrow
    min_trades: int = 4                  # in each of the tuning and test windows
    max_price_fraction: float = 0.5      # skip stocks whose price is above this share of capital
    min_avg_turnover_cr: float = 50.0    # skip illiquid stocks (average daily turnover, crores)
    assumed_capital: float = 2000.0      # used for sizing in research when no capital is set yet


class LiveGate(BaseModel):
    """Live trading stays locked until paper trading has proven itself."""
    min_paper_days: int = 20
    require_positive_net: bool = True
    i_accept_the_risk: bool = False      # set true to skip the gate (not recommended)


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8765


class Settings(BaseModel):
    mode: Literal["paper", "live"] = "paper"
    data_source: Literal["angelone", "replay"] = "angelone"
    data_dir: str = "data"
    market: MarketSettings = MarketSettings()
    risk: RiskSettings = RiskSettings()
    costs: CostSettings = CostSettings()
    strategy: StrategySettings = StrategySettings()
    research: ResearchSettings = ResearchSettings()
    live_gate: LiveGate = LiveGate()
    api: ApiSettings = ApiSettings()

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    path = Path(path or os.environ.get("TRADEBOT_CONFIG", "config.yaml"))
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Settings.model_validate(raw)
    return Settings()


class Secrets(BaseModel):
    api_key: str = ""
    client_code: str = ""
    pin: str = ""
    totp_secret: str = ""

    @property
    def complete(self) -> bool:
        return all([self.api_key, self.client_code, self.pin, self.totp_secret])


def load_secrets() -> Secrets:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:  # pragma: no cover
        pass
    return Secrets(
        api_key=os.environ.get("ANGEL_API_KEY", ""),
        client_code=os.environ.get("ANGEL_CLIENT_CODE", ""),
        pin=os.environ.get("ANGEL_PIN", ""),
        totp_secret=os.environ.get("ANGEL_TOTP_SECRET", ""),
    )
