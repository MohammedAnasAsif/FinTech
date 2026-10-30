"""Angel One SmartAPI connector (free API, including market data).

Login uses your client code, 4-digit PIN and the TOTP secret from Angel One's
"Enable TOTP" page, all read from `.env`. Orders go out as marketable LIMIT orders
(a small buffer past the last price) tagged "tradebot", and are polled until filled.

Since 1 April 2026 Angel One only accepts API *orders* from your registered static IP.
Market data works from any IP, which is why paper trading needs no static IP.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time as _time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from ..clock import IST
from ..config import Secrets
from ..models import Fill, OrderStatus, Side
from .base import Executor, MarketData

log = logging.getLogger(__name__)

SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
INTERVALS = {1: "ONE_MINUTE", 3: "THREE_MINUTE", 5: "FIVE_MINUTE", 10: "TEN_MINUTE",
             15: "FIFTEEN_MINUTE", 30: "THIRTY_MINUTE", 60: "ONE_HOUR", 1440: "ONE_DAY"}
MAX_DAYS_PER_CALL = {1: 25, 3: 55, 5: 90, 10: 90, 15: 180, 30: 180, 60: 360, 1440: 1900}


class RateLimiter:
    def __init__(self, per_second: float):
        self.gap = 1.0 / per_second
        self.last = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            delta = self.gap - (_time.monotonic() - self.last)
            if delta > 0:
                _time.sleep(delta)
            self.last = _time.monotonic()


class Instruments:
    """NSE equity symbol -> Angel One token and tick size, from the public scrip master."""

    def __init__(self, cache_dir: Path):
        self.path = cache_dir / "scrip_master.json"
        self.map: dict[str, dict] = {}

    def load(self) -> None:
        fresh = self.path.exists() and date.fromtimestamp(self.path.stat().st_mtime) == date.today()
        if not fresh:
            log.info("downloading Angel One scrip master")
            r = requests.get(SCRIP_MASTER_URL, timeout=120)
            r.raise_for_status()
            self.path.write_bytes(r.content)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        for it in data:
            if it.get("exch_seg") == "NSE" and str(it.get("symbol", "")).endswith("-EQ"):
                name = it["symbol"][:-3]
                tick = float(it.get("tick_size") or 5) / 100
                self.map[name] = {"token": str(it["token"]), "tradingsymbol": it["symbol"], "tick": tick or 0.05}

    def get(self, symbol: str) -> dict | None:
        return self.map.get(symbol.upper())


class AngelSession:
    """Holds the logged-in SmartConnect client and logs in again each trading day."""

    def __init__(self, secrets: Secrets, data_dir: Path):
        if not secrets.complete:
            raise RuntimeError(
                "Angel One credentials missing. Copy engine/.env.example to engine/.env and fill it in "
                "(see docs/SETUP.md), or run with data_source: replay."
            )
        self.secrets = secrets
        self.instruments = Instruments(data_dir)
        self.client = None
        self.login_day: date | None = None
        self.lock = threading.Lock()

    def ensure(self):
        with self.lock:
            today = datetime.now(IST).date()
            if self.client is None or self.login_day != today:
                self._login()
                self.login_day = today
            return self.client

    def _login(self) -> None:
        import pyotp
        from SmartApi import SmartConnect

        client = SmartConnect(api_key=self.secrets.api_key)
        totp = pyotp.TOTP(self.secrets.totp_secret).now()
        resp = client.generateSession(self.secrets.client_code, self.secrets.pin, totp)
        if not resp or not resp.get("status"):
            raise RuntimeError(f"Angel One login failed: {resp.get('message') if resp else 'no response'}")
        self.client = client
        if not self.instruments.map:
            self.instruments.load()
        log.info("logged in to Angel One")

    def logout(self) -> None:
        if self.client is not None:
            try:
                self.client.terminateSession(self.secrets.client_code)
            except Exception:  # noqa: BLE001
                pass
            self.client = None


class AngelMarketData(MarketData):
    def __init__(self, session: AngelSession):
        self.s = session
        self.limiter = RateLimiter(2.5)   # candle API allows ~3/s

    def has_symbol(self, symbol: str) -> bool:
        self.s.ensure()
        return self.s.instruments.get(symbol) is not None

    def candles(self, symbol: str, interval_minutes: int, start: datetime, end: datetime) -> pd.DataFrame:
        client = self.s.ensure()
        inst = self.s.instruments.get(symbol)
        if inst is None or interval_minutes not in INTERVALS:
            return _empty()
        frames, cur = [], start
        span = timedelta(days=MAX_DAYS_PER_CALL[interval_minutes])
        while cur < end:
            stop = min(cur + span, end)
            self.limiter.wait()
            resp = client.getCandleData({
                "exchange": "NSE",
                "symboltoken": inst["token"],
                "interval": INTERVALS[interval_minutes],
                "fromdate": cur.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
                "todate": stop.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
            })
            rows = (resp or {}).get("data") or []
            if rows:
                frames.append(pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]))
            elif resp and not resp.get("status", True):
                log.warning("candles %s: %s", symbol, resp.get("message"))
            cur = stop
        if not frames:
            return _empty()
        df = pd.concat(frames).drop_duplicates("ts")
        df["ts"] = pd.to_datetime(df["ts"]).dt.tz_convert(IST)
        return df.set_index("ts").sort_index().astype(float)

    def ltp(self, symbol: str) -> float | None:
        client = self.s.ensure()
        inst = self.s.instruments.get(symbol)
        if inst is None:
            return None
        self.limiter.wait()
        resp = client.ltpData("NSE", inst["tradingsymbol"], inst["token"])
        try:
            return float(resp["data"]["ltp"])
        except (TypeError, KeyError):
            return None


class AngelExecutor(Executor):
    """Real orders. Only used in live mode, after the paper-trading gate has been passed."""

    is_live = True
    BUFFER_PCT = 0.15      # how far past the last price a marketable limit order is placed
    WAIT_SECONDS = 12

    def __init__(self, session: AngelSession, max_orders_per_second: float = 1.0):
        self.s = session
        self.limiter = RateLimiter(max_orders_per_second)

    def place(self, symbol: str, side: Side, qty: int, ref_price: float, now: datetime) -> Fill:
        client = self.s.ensure()
        inst = self.s.instruments.get(symbol)
        if inst is None:
            return Fill(symbol, side, 0, 0.0, now, "", OrderStatus.REJECTED, "unknown symbol")
        remaining, filled_qty, filled_value, last_id, msg = qty, 0, 0.0, "", ""
        for attempt in range(3):     # retry the unfilled part with a wider buffer
            buf = self.BUFFER_PCT * (attempt + 1) / 100
            raw = ref_price * (1 + buf) if side is Side.BUY else ref_price * (1 - buf)
            price = _to_tick(raw, inst["tick"], up=side is Side.BUY)
            self.limiter.wait()
            order_id = client.placeOrder({
                "variety": "NORMAL", "tradingsymbol": inst["tradingsymbol"], "symboltoken": inst["token"],
                "transactiontype": side.value, "exchange": "NSE", "ordertype": "LIMIT",
                "producttype": "INTRADAY", "duration": "DAY", "price": f"{price:.2f}",
                "quantity": str(remaining), "ordertag": "tradebot",
            })
            if not order_id:
                return Fill(symbol, side, filled_qty, _avg(filled_value, filled_qty), now, last_id,
                            OrderStatus.REJECTED if not filled_qty else OrderStatus.FILLED, "order placement failed")
            last_id = str(order_id)
            status, got, avg, msg = self._wait(client, last_id)
            if got:
                filled_qty += got
                filled_value += got * avg
                remaining -= got
            if remaining <= 0:
                break
            if status == "rejected":
                break
            if status not in ("complete", "cancelled", "rejected"):
                self.limiter.wait()
                client.cancelOrder(last_id, "NORMAL")
                _time.sleep(1)
                status2, got2, avg2, _ = self._status(client, last_id)
                extra = max(0, got2 - got)
                if extra:
                    filled_qty += extra
                    filled_value += extra * avg2
                    remaining -= extra
            ltp = AngelMarketData(self.s).ltp(symbol)
            ref_price = ltp or ref_price
        st = OrderStatus.FILLED if filled_qty else OrderStatus.REJECTED
        return Fill(symbol, side, filled_qty, round(_avg(filled_value, filled_qty), 2), now, last_id, st, msg)

    def _status(self, client, order_id: str) -> tuple[str, int, float, str]:
        book = (client.orderBook() or {}).get("data") or []
        for o in book:
            if str(o.get("orderid")) == order_id:
                return (str(o.get("status", "")).lower(), int(float(o.get("filledshares") or 0)),
                        float(o.get("averageprice") or 0), str(o.get("text") or ""))
        return "unknown", 0, 0.0, ""

    def _wait(self, client, order_id: str) -> tuple[str, int, float, str]:
        deadline = _time.monotonic() + self.WAIT_SECONDS
        status = ("unknown", 0, 0.0, "")
        while _time.monotonic() < deadline:
            _time.sleep(1.0)
            status = self._status(client, order_id)
            if status[0] in ("complete", "rejected", "cancelled"):
                break
        return status

    def available_cash(self) -> float | None:
        resp = self.s.ensure().rmsLimit()
        try:
            return float(resp["data"]["availablecash"])
        except (TypeError, KeyError, ValueError):
            return None

    def open_quantities(self) -> dict[str, int]:
        resp = self.s.ensure().position() or {}
        out = {}
        for p in resp.get("data") or []:
            q = int(float(p.get("netqty") or 0))
            if q and str(p.get("producttype", "")).upper() in ("INTRADAY", "MIS"):
                out[str(p.get("tradingsymbol", "")).removesuffix("-EQ")] = q
        return out


def _to_tick(price: float, tick: float, up: bool) -> float:
    n = price / tick
    return round((math.ceil(n) if up else math.floor(n)) * tick, 2)


def _avg(value: float, qty: int) -> float:
    return value / qty if qty else 0.0


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                        index=pd.DatetimeIndex([], tz=IST, name="ts"))
