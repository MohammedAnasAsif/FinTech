# Setup: Angel One + your PC + your phone

Everything here is free. You'll only need to spend money on a **static IP**, and only if you go live later (see step 7).

## 1. Angel One account and SmartAPI key

1. Open an Angel One trading account if you don't have one.
2. Go to **smartapi.angelbroking.com**, sign up with your Angel One client ID, and create an app of type **Trading API**.
3. Copy the app's **API key**.

## 2. Turn on TOTP

On the SmartAPI site, open **Enable TOTP**. Enter your client ID and PIN, then the OTP you receive.

It shows a QR code **and the same secret as text**. Scan the QR code with an authenticator app as a backup. Then copy the **text secret**, not a 6-digit code. The engine uses it to log in by itself every morning.

## 3. Install the engine on your PC

**Windows, easiest:** download `TradeBot-engine-windows.zip` from the repo's Releases page and unzip it somewhere permanent, for example `C:\TradeBot`.

**Any OS, from source:** install Python 3.11 or newer, then run:

```bash
cd engine
pip install -e .
```

## 4. Add your credentials

In the engine folder, copy `.env.example` to `.env` and fill in the four values:

```
ANGEL_API_KEY=...        # step 1
ANGEL_CLIENT_CODE=...    # your client ID
ANGEL_PIN=...            # your 4-digit PIN
ANGEL_TOTP_SECRET=...    # step 2, the text secret
```

`.env` never leaves your PC, and `.gitignore` keeps it out of git. Don't share it. Anyone with it can log in to your account.

Optionally, copy `config.example.yaml` to `config.yaml` to change limits, timings or the stock universe.

## 5. Run it

- Windows: double-click **`start-engine.bat`**.
- Source install: run `tradebot serve` inside `engine/`.

The engine prints something like:

```
  In the app, enter:  http://192.168.1.20:8765
  Pairing token:      Xy3...
```

When Windows Firewall asks, allow access on **private networks** so your phone can reach the engine.

Keep the PC awake during market hours and at 20:00 for research. Set Windows power settings to "Sleep: never" while plugged in.

Useful commands:

```bash
tradebot research          # run tonight's research right now and print the reasons
tradebot backtest SBIN     # see how the strategy did on one stock, after charges
tradebot demo              # fake market at high speed (no account needed)
```

## 6. Connect the app

- **Android:** install `TradeBot.apk` from Releases. Allow "install unknown apps" for your browser or file manager. Your phone must be on the **same Wi-Fi** as the PC. Enter the address and pairing token.
- **Windows app:** unzip `TradeBot-app-windows.zip` and run `TradeBot.exe`. On the same PC, the address `http://127.0.0.1:8765` works.

## 7. Paper first, live later

The engine starts in **paper mode**. It uses real Angel One prices with simulated fills, net of every charge. The Today screen shows progress toward the live gate: 20 trading days with trades, and a positive total after charges.

Going live needs two things:

1. **A static IP**, registered in your SmartAPI app. Since 1 April 2026 Angel One rejects API orders from any other IP. Ask your internet provider for one, which usually costs extra. Paper trading only reads market data and doesn't need it.
2. **`mode: live`** in `config.yaml`, once the gate shows as unlocked.

Start live with the smallest capital you're genuinely fine losing.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Angel One login failed` | Check the `.env` values. The TOTP secret must be the text secret, and the PC clock must be correct, because TOTP depends on time. |
| Phone can't connect | Same Wi-Fi? Use the PC's address, not `127.0.0.1`. Allow the firewall prompt, or add an inbound rule for port 8765 on private networks. |
| Watchlist is empty | Normal on some days. No stock passed both the tuning and unseen-data tests. Run `tradebot research` to see each stock's reason. |
| "Market is closed today" | Weekend or an NSE holiday from `holidays.yaml`. Update that file each year. |
