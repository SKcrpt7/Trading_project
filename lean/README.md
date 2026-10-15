# Running the strategy in QuantConnect LEAN

This folder holds the **same** EUR/USD trend example as the local `fxlab` engine,
written for QuantConnect's LEAN. Use it to cross-check the local backtest against
a mature, battle-tested engine with real OANDA data.

> **You cannot run this on your machine yet** — LEAN's local engine runs inside
> **Docker**, which is not installed. Two options below.

## Option A — Local LEAN (needs Docker Desktop)
1. Install **Docker Desktop** for Windows and start it.
   (Requirements: 64-bit CPU, virtualization enabled in BIOS, Windows 10 1903+.)
2. In your venv: `pip install lean`
3. Create a LEAN workspace (once): `lean init`
4. Copy `EURUSDTrendAlgorithm.py` into a project folder LEAN created, or:
   `lean project-create "EURUSDTrend" --language python` and replace `main.py`
   with this algorithm.
5. Run: `lean backtest "EURUSDTrend"`
   The first run downloads a Docker image (large) and the LEAN sample data.

Docs: <https://www.quantconnect.com/docs/v2/lean-cli/installation/installing-docker>
and <https://www.quantconnect.com/docs/v2/lean-cli/backtesting/deployment>

## Option B — QuantConnect Cloud (free account, no Docker)
1. Create a free account at <https://www.quantconnect.com> and get an API token
   (User ID + token) from your account settings.
2. `pip install lean` then `lean login` (paste User ID + token).
   Put them in `.env` as `QC_USER_ID` / `QC_API_TOKEN` if you script it — never
   commit them.
3. `lean cloud push` to upload, then `lean cloud backtest "EURUSDTrend" --open`.
   Cloud backtests use QuantConnect's data; a data subscription may be required
   for some resolutions/markets.

## What to compare
- Trade count, net return, max drawdown, profit factor between LEAN and the local
  `fxlab backtest`. They will **not** match exactly (different data, fill models,
  spread handling) — the point is directional agreement and sane behaviour.
- LEAN uses **real OANDA quote data**; the local engine (by default) uses the
  **MOCK** sample. Differences are expected and informative.

## Paper / live in LEAN
- QuantConnect supports **paper (live-paper)** deployment in the cloud. That is the
  intended place to paper-trade this with live data once you have an account.
- **Live money is out of scope for this project** — see
  `../docs/live_trading_boundary.md`.
