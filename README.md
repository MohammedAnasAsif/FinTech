# TradeBot

An open-source intraday trading assistant for NSE stocks. It studies the market overnight, trades a small daily budget during market hours, and reviews its own mistakes after the close. It works with Angel One's free SmartAPI.

It has two parts:

- **Engine** (Python, runs on your PC). Does the research, trading, risk control and self-review.
- **App** (Flutter). An Android APK and a Windows .exe that act as the remote control. You use it to set today's capital, take a break, stop, hit the kill switch, and read why every trade happened.

> **Read this first.** A SEBI study found that 71% of individual intraday traders lost money in FY23, and 80% of very frequent traders did. This bot does not change those odds by magic. It starts in **paper mode** (real prices, fake money). Live trading stays **locked** until paper trading has been profitable *after all charges* for 20 trading days. Nothing here is investment advice.

## A day in the life

| Time (IST) | What the bot does |
|---|---|
| 20:00 (night before) | **Research.** For each stock in the universe, it tunes the strategy on older 5-minute history, then tests those settings on newer days the tuning never saw. A stock is only picked if it made money **after charges** in both. An empty watchlist is allowed, and on those days the bot sits out. |
| Morning | You open the app and enter today's capital (for example ₹2,000). |
| 10:00 | Trading starts on the watchlist. Each trade has a stop and a target, and is sized so the stop costs about 1.5% of capital. |
| Any time | **₹500 is the most it can lose in a day**, and open losses count toward it. When it hits ₹500, the bot closes everything and **stops trading until tomorrow**. It doesn't come back the same day. It benches the stocks that lost and runs its analysis on past and today's data to plan tomorrow. |
| Any time | It takes an automatic 20-minute break after 3 losses in a row. **Take a break**, **Stop for today** and **Kill switch** are in the app. |
| 14:45 | No new trades. |
| 15:00 | Everything is squared off. This is earlier than the broker's own auto square-off. |
| 15:10 | **Self-review.** It names each mistake with evidence and turns it into a small rule change for tomorrow. For example, a stock that keeps losing is benched for a week. Entries that got stopped out within 2 bars mean that stock now needs more volume to enter. When charges eat the profit, the minimum target-to-charges ratio goes up. The review can only make the bot pickier. It can never raise limits, increase position size or switch to live mode. |

Every number above is a setting in `engine/config.yaml`.

## Downloads

The [latest release](../../releases/latest) is rebuilt automatically from `main`:

- [TradeBot.apk](../../releases/latest/download/TradeBot.apk). Android control app.
- [TradeBot-app-windows.zip](../../releases/latest/download/TradeBot-app-windows.zip). Windows control app (`TradeBot.exe`).
- [TradeBot-engine-windows.zip](../../releases/latest/download/TradeBot-engine-windows.zip). The engine (`tradebot-engine.exe` plus start scripts).

## Try it in two minutes (no account needed)

The demo runs a fake market at 60× speed, so you can watch a whole day in about 6 minutes. **The demo prices are random and not real data.**

```bash
cd engine
pip install -e .
tradebot demo
```

On Windows you can instead download `TradeBot-engine-windows.zip` from [Releases](../../releases) and double-click `start-demo.bat`. Then open the app and enter the address and pairing token the engine prints.

## Real setup

See **[docs/SETUP.md](docs/SETUP.md)**. It covers the free Angel One SmartAPI key, TOTP, the `.env` file, running the engine on your PC, and connecting your phone.

## Safety rules built into the code

- **Paper mode by default.** Live mode needs `mode: live` in the config *and* 20 profitable paper days. The `i_accept_the_risk` override exists, but it is off.
- **No leverage.** The bot only buys what today's capital can pay for in full.
- **One ₹500 loss cap per day.** It is checked every few seconds, open losses included. Trades are also sized so a stop-loss can't exceed what's left of the ₹500. A very fast price jump between checks can still push the final loss slightly past ₹500.
- **Costs are always counted.** Brokerage, STT, exchange fees, SEBI fees, stamp duty, GST and slippage are subtracted in backtests, research, paper and live trading. A trade is skipped if its target profit isn't at least 3× its charges.
- **Orders are marketable limit orders**, tagged `tradebot`, sent at no more than one per second through Angel One's official API with your own static IP. There is no screen-scraping and nothing hidden.
- **The app needs a pairing token** for every action.

### Know the limits

Stops are managed by the engine, not placed at the broker. If your PC or internet goes down mid-trade, an open position stays open until you close it in the Angel One app, or until Angel One's own auto square-off. The bot holds at most one small position at a time, which limits this risk, but keep the PC awake during market hours.

## Repository layout

```
engine/                 Python engine
  tradebot/
    engine.py           daily timetable & state machine
    risk.py             ₹500 daily loss cap, cooldowns, position sizing
    research.py         overnight walk-forward research
    review.py           post-market self-review & learned rules, live-trading gate
    backtest.py         bar-by-bar backtester (net of costs)
    costs.py            Indian intraday charges
    strategy/           EMA + VWAP + volume entries, ATR stop/target
    broker/angelone.py  SmartAPI login (TOTP), candles, LTP, orders
    api.py              HTTP API for the app (token protected)
  tests/                22 tests: risk rules, costs, full simulated days, API, order handling
app/                    Flutter control app (Android + Windows)
.github/workflows/      builds the APK and both .exe files on every push
```

## Building

GitHub Actions builds everything on every push. Each successful build of `main` refreshes the **Latest build** release. A tag like `v0.1.0` creates a versioned release.

To build locally, you need Flutter (stable) for the app. Run `cd app && flutter create --platforms=android,windows . && python ../tools/patch_platforms.py . && flutter build apk`. For the engine, use Python 3.11+ and run `pip install -e "engine[dev]" && pytest engine/tests`.

## Roadmap

- Company fundamentals and results calendar in research. Avoid trading a stock on its results day.
- News and social sentiment as a low-weight research input.
- Broker-side protective stop orders, so stops survive a PC or internet outage.
- WebSocket price feed instead of polling.
- More strategies, each one having to earn its place through the same walk-forward test.

## Legal

Since 1 April 2026, SEBI requires retail API algo orders to go through the broker's API from a registered static IP, tagged with an algo ID. This project is a self-hosted tool you run for your own account with your own API key. If you ever offer it to others as a service, check SEBI's research-analyst and algo-provider rules first. MIT licensed. No warranty. Trading can lose money.
