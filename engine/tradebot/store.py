"""SQLite storage: candle cache, trades, events (the app's live log), reviews, daily results."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd

from .clock import IST
from .models import Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
  symbol TEXT, interval INTEGER, ts TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY (symbol, interval, ts));
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, mode TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS reviews (day TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS days (
  day TEXT, mode TEXT, capital REAL, net REAL, trades INTEGER, PRIMARY KEY (day, mode));
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._db.commit()

    def _exec(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            cur = self._db.execute(sql, args)
            rows = cur.fetchall()
            self._db.commit()
            return rows

    # ---------- candles ----------
    def save_candles(self, symbol: str, interval: int, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        rows = [(symbol, interval, ts.isoformat(), r.open, r.high, r.low, r.close, r.volume)
                for ts, r in zip(df.index, df.itertuples())]
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?)", rows)
            self._db.commit()

    def load_candles(self, symbol: str, interval: int, start: datetime | None = None,
                     end: datetime | None = None) -> pd.DataFrame:
        sql = "SELECT ts, open, high, low, close, volume FROM candles WHERE symbol=? AND interval=?"
        args: list = [symbol, interval]
        if start:
            sql += " AND ts >= ?"
            args.append(start.isoformat())
        if end:
            sql += " AND ts < ?"
            args.append(end.isoformat())
        rows = self._exec(sql + " ORDER BY ts", tuple(args))
        return frame(rows)

    def symbols_with_candles(self, interval: int) -> list[str]:
        return [r[0] for r in self._exec("SELECT DISTINCT symbol FROM candles WHERE interval=?", (interval,))]

    # ---------- trades ----------
    def save_trade(self, t: Trade) -> None:
        self._exec("INSERT INTO trades (day, mode, data) VALUES (?,?,?)", (t.day, t.mode, json.dumps(t.to_dict())))

    def trades(self, day: str | None = None, mode: str | None = None, limit: int = 500) -> list[dict]:
        sql, args = "SELECT data FROM trades WHERE 1=1", []
        if day:
            sql += " AND day=?"
            args.append(day)
        if mode:
            sql += " AND mode=?"
            args.append(mode)
        rows = self._exec(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
        return [json.loads(r[0]) for r in rows]

    # ---------- events ----------
    def log(self, message: str, level: str = "info", ts: datetime | None = None) -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO events (ts, level, message) VALUES (?,?,?)",
                                   ((ts or datetime.now(IST)).isoformat(timespec="seconds"), level, message))
            self._db.commit()
            return cur.lastrowid

    def events(self, since: int = 0, limit: int = 200) -> list[dict]:
        rows = self._exec("SELECT id, ts, level, message FROM events WHERE id > ? ORDER BY id DESC LIMIT ?",
                          (since, limit))
        return [{"id": r[0], "ts": r[1], "level": r[2], "message": r[3]} for r in reversed(rows)]

    # ---------- reviews & daily results ----------
    def save_review(self, day: str, data: dict) -> None:
        self._exec("INSERT OR REPLACE INTO reviews VALUES (?,?)", (day, json.dumps(data, default=str)))

    def reviews(self, limit: int = 30) -> list[dict]:
        rows = self._exec("SELECT day, data FROM reviews ORDER BY day DESC LIMIT ?", (limit,))
        return [{"day": r[0], **json.loads(r[1])} for r in rows]

    def save_day(self, day: str, mode: str, capital: float, net: float, trades: int) -> None:
        self._exec("INSERT OR REPLACE INTO days VALUES (?,?,?,?,?)", (day, mode, capital, net, trades))

    def days(self, mode: str | None = None) -> list[dict]:
        sql, args = "SELECT day, mode, capital, net, trades FROM days", ()
        if mode:
            sql, args = sql + " WHERE mode=?", (mode,)
        rows = self._exec(sql + " ORDER BY day", args)
        return [dict(zip(["day", "mode", "capital", "net", "trades"], r)) for r in rows]

    # ---------- key/value ----------
    def get(self, k: str, default=None):
        rows = self._exec("SELECT v FROM kv WHERE k=?", (k,))
        return json.loads(rows[0][0]) if rows else default

    def put(self, k: str, v) -> None:
        self._exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v, default=str)))


def frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df.set_index("ts")
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(IST)
    return df.set_index("ts")
