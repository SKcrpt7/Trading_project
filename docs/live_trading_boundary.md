# Live trading boundary

**Live trading is disabled in this project, by design.** This document explains
exactly where the boundary is, how it is enforced in code, and what a *future*
live connection would require. Nothing here enables live trading.

## What the system does today
- **Backtesting** on historical data (sample or your own).
- **Paper trading** with a **simulated broker** (`fxlab/paper/sim_broker.py`).
  Every fill it produces is tagged `is_simulated=True`.

## How the boundary is enforced
- `fxlab/paper/broker_interface.py` defines `LIVE_TRADING_SUPPORTED = False`.
- Every broker must pass `assert_not_live()` before trading; it raises unless the
  backend is a simulator. The paper runner and sim broker both call it.
- There is **no live order code path** anywhere in the repo. The `Fill` type
  carries `is_simulated` and it is always `True`.
- Secrets are read only from environment variables / `.env` (never hard-coded,
  never printed). `.env` is git-ignored. `.env.example` contains **no real keys**
  and intentionally has no live-broker credentials.

## What a future live connection would require (NOT included here)
This is a checklist for *you*, later, as a deliberate and separately-authorized
project — not something this code will do automatically:

1. **A funded broker / platform account** and its API credentials, stored in a
   real secrets manager (not a file).
2. **A concrete `BrokerInterface` implementation** (e.g. MetaTrader 5 via the
   `MetaTrader5` package, or QuantConnect live via a supported brokerage) that
   actually sends orders, and sets `is_simulated=False` on real fills.
3. **Order-state reconciliation against the broker** (not just internal state):
   poll/subscribe to order and position updates, handle partial fills, rejects,
   requotes, disconnects, and restart recovery.
4. **Guaranteed protective orders**: confirm the stop is *accepted and resting* at
   the broker before considering the position protected; flatten on any failure.
5. **A real kill switch** wired to both software and your broker (cancel-all +
   flatten-all), plus heartbeats and alerting you actually receive.
6. **Extended paper-trading evidence** that observed behaviour matches backtest
   expectations, and a written risk mandate (max loss, position caps).
7. **Flipping `LIVE_TRADING_SUPPORTED`** and removing the guard — a change that
   should require code review and explicit human sign-off.
8. **Compliance / tax / regulatory** considerations for your jurisdiction.

Until *all* of the above exist and are tested, keep trading simulated.
