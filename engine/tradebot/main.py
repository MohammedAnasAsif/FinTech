"""Command line:  tradebot serve | demo | research | backtest | review"""
from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .clock import IST, Clock, MarketCalendar, load_holidays
from .config import Settings, load_secrets, load_settings
from .store import Store

log = logging.getLogger("tradebot")


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def build(settings: Settings, clock: Clock | None = None):
    from .broker.base import PaperExecutor
    from .engine import Engine
    from .replay import ReplayMarketData

    store = Store(settings.data_path / "tradebot.db")
    cal = MarketCalendar(settings.market, load_holidays(settings.market.holidays_file))
    clock = clock or Clock()
    if settings.data_source == "replay":
        md = ReplayMarketData(store, clock)
        if settings.mode == "live":
            raise SystemExit("Replay data can only be used in paper mode.")
        ex = PaperExecutor(settings.costs)
        cache = False
    else:
        from .broker.angelone import AngelExecutor, AngelMarketData, AngelSession
        session = AngelSession(load_secrets(), settings.data_path)
        md = AngelMarketData(session)
        ex = AngelExecutor(session, settings.risk.max_orders_per_second) if settings.mode == "live" \
            else PaperExecutor(settings.costs)
        cache = True
    return Engine(settings, store, clock, cal, md, ex, cache_history=cache), store, cal


def serve(settings: Settings, clock: Clock | None = None, tick: float = 5.0) -> None:
    import uvicorn

    from .api import build_app, load_or_create_token

    engine, _, _ = build(settings, clock)
    token = load_or_create_token(settings.data_path)
    print("\n" + "=" * 60)
    print(f"  TradeBot engine — {engine.mode.upper()} mode, data: {settings.data_source}")
    print(f"  In the app, enter:  http://{lan_ip()}:{settings.api.port}")
    print(f"  Pairing token:      {token}")
    print("=" * 60 + "\n")
    threading.Thread(target=engine.run_forever, kwargs={"tick_seconds": tick}, daemon=True).start()
    uvicorn.run(build_app(engine, token), host=settings.api.host, port=settings.api.port, log_level="warning")


def cmd_demo(settings: Settings, args) -> None:
    """Synthetic market, fast clock: watch a full trading day in a few minutes, no account needed."""
    from .replay import SimClock, seed_synthetic

    settings = settings.model_copy(update={"data_source": "replay", "mode": "paper",
                                           "data_dir": str(Path(settings.data_dir) / "demo")})
    settings.research.universe = ["DEMOA", "DEMOB", "DEMOC", "DEMOD"]
    settings.research.min_avg_turnover_cr = 0
    settings.research.min_trades = 1
    # random-walk data has no real edge, so loosen the filters to see the bot actually trade
    settings.strategy.min_volume_ratio = 0
    settings.strategy.use_vwap_filter = False
    settings.strategy.min_reward_to_cost = 1
    settings.strategy.allow_short = True
    store = Store(settings.data_path / "tradebot.db")
    cal = MarketCalendar(settings.market, set())
    today = datetime.now(IST).date()
    day = today if cal.is_trading_day(today) else cal.next_trading_day(today)
    if not store.symbols_with_candles(1):
        print("Creating synthetic price history (this is fake data, for testing only)...")
        hist = cal.previous_trading_days(day, 40) + [day]
        seed_synthetic(store, {"DEMOA": 420.0, "DEMOB": 180.0, "DEMOC": 95.0, "DEMOD": 640.0}, hist)
    clock = SimClock(datetime.combine(day, time(9, 40), tzinfo=IST), speed=args.speed)
    # research "last night" so there's a watchlist in the morning
    engine, _, _ = build(settings, clock)
    from .research import research
    res = research(engine.history, store, settings, clock.now() - timedelta(minutes=30), capital=2000)
    if not res["picks"]:
        res["picks"] = [{"symbol": s, "params": {}, "context": {}, "score": 0,
                         "reasons": ["demo: watched anyway so you can see the bot trade"]}
                        for s in settings.research.universe[:2]]
        res["note"] = "Demo: no stock passed the tests on fake data; watching two anyway."
        store.put("watchlist", res)
    serve(settings, clock, tick=max(0.2, 30 / args.speed))


def cmd_research(settings: Settings, args) -> None:
    engine, _, _ = build(settings)
    from .research import research
    res = research(engine.history, engine.store, settings, datetime.now(IST), capital=args.capital)
    print(json.dumps({k: res[k] for k in ("note", "picks")}, indent=2, default=str))
    for r in res["rejected"]:
        print(f"  skipped {r['symbol']}: {r['reason']}")


def cmd_backtest(settings: Settings, args) -> None:
    from .backtest import run_backtest
    engine, _, _ = build(settings)
    end = datetime.now(IST)
    bars = engine.history.get(args.symbol.upper(), settings.strategy.interval_minutes,
                              end - timedelta(days=args.days), end)
    res = run_backtest(bars, args.symbol.upper(), settings, args.capital)
    for t in res.trades:
        print(f"{t.entry_ts[:16]}  {'L' if t.direction > 0 else 'S'} {t.qty:>4} @ {t.entry_price:>9.2f} -> "
              f"{t.exit_price:>9.2f}  {t.exit_reason:<16} net {t.net:>8.2f}")
    print(json.dumps(res.metrics, indent=2))


def cmd_review(settings: Settings, args) -> None:
    from .review import review_day
    store = Store(settings.data_path / "tradebot.db")
    day = date.fromisoformat(args.day) if args.day else datetime.now(IST).date()
    print(json.dumps(review_day(store, settings, day, settings.mode, args.capital,
                                watchlist=store.get("watchlist")), indent=2, default=str))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="tradebot", description="Open-source intraday research & trading engine")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the engine and the app API")
    d = sub.add_parser("demo", help="fake market at high speed, to try the app")
    d.add_argument("--speed", type=float, default=60.0, help="simulated seconds per real second")
    r = sub.add_parser("research", help="run research now and print the watchlist")
    r.add_argument("--capital", type=float, default=2000)
    b = sub.add_parser("backtest", help="backtest one stock")
    b.add_argument("symbol")
    b.add_argument("--days", type=int, default=30)
    b.add_argument("--capital", type=float, default=2000)
    v = sub.add_parser("review", help="run the post-market review for a day")
    v.add_argument("--day", default=None)
    v.add_argument("--capital", type=float, default=2000)
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):   # ₹ signs on older Windows consoles
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    settings = load_settings(args.config)
    {"serve": lambda: serve(settings), "demo": lambda: cmd_demo(settings, args),
     "research": lambda: cmd_research(settings, args), "backtest": lambda: cmd_backtest(settings, args),
     "review": lambda: cmd_review(settings, args), None: lambda: serve(settings)}[args.cmd]()


if __name__ == "__main__":
    main()
