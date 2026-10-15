# fxlab — forex strategy research & paper-trading toolkit

A learning-first system for designing, backtesting, reviewing, and **paper**-trading
rule-based forex strategies — built so you can understand **every** decision it
makes. It runs end-to-end **right now** on bundled mock data, with **no broker and
no subscription**, and is ready to connect to QuantConnect LEAN when you install
Docker or create a QC account.

> ⚠️ **Educational only.** Nothing here is financial advice. A passing backtest is
> **never** proof of future profitability. **Live trading is disabled by design**
> (see [`docs/live_trading_boundary.md`](docs/live_trading_boundary.md)). The
> bundled data is **synthetic/MOCK** and clearly labelled everywhere it appears.

---

## What this does (the 6-step workflow)

1. **Economic calendar & news** — tracks high-impact releases (FRED or sample),
   stored in UTC, shown in America/Toronto, with a configurable **news blackout**.
2. **Strategy as testable rules** — defined in YAML + a small `Strategy` class.
3. **Realistic backtests** — spread, commission, slippage, swap; next-bar
   execution (no look-ahead); pessimistic stop/target fills.
4. **A review** that outputs **reject / needs-investigation / eligible-for-paper**,
   with the evidence and reasons shown.
5. **Paper trading** (simulated fills) with position sizing, stops/targets, and
   hard risk limits.
6. **An audit log** recording every signal, order, fill, error, and decision.

## What you need

| To do this | You need | Included / required now? |
|---|---|---|
| Run research + paper locally | **Python 3.10+** (you have 3.14) | ✅ works now, no account |
| Official event **dates** | Free **FRED** API key (optional) | optional — sample events work without it |
| Real FX price history | Your own CSV, or a data subscription | later — MOCK sample included |
| LEAN **local** backtests | **Docker Desktop** (free) | optional, later |
| LEAN **cloud** / QC paper | **QuantConnect** account + API token (free tier) | optional, later |
| A broker / MT5 / live money | A broker account | **out of scope** — live disabled |

## Setup (Windows / PowerShell)

```powershell
# from the project root
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# (optional) secrets — copy the example and fill in only what you have
Copy-Item .env.example .env
```

## Dashboard (the easiest way to use it)

**Double-click `run_dashboard.bat`.** It starts the app and opens
<http://127.0.0.1:8501> in your browser after a few seconds. Close the black window
to stop it. (Manual start: `.\.venv\Scripts\streamlit run streamlit_app.py`.)

The app is served to **this computer only** (`.streamlit/config.toml`), drives the
same code as the CLI (`fxlab/workflow.py`), and cannot trade live. Pages follow
the workflow:

| Page | What you do there |
|---|---|
| **Home** | Checklist for the selected strategy/version + the suggested next step |
| **1 · Data** | Quality report, price chart with the hold-out shaded, upload your own CSV, event calendar |
| **2 · Strategy** | Edit parameters in a form. Saving **requires a new version** and archives the old file to `config/strategy_history/` (comments in the YAML are kept). Or fork into a new strategy |
| **3 · Dev backtest** | Tune on the **development slice only** (the hold-out is never used); equity curve, trades, breakdowns, and a table comparing every version you've tried |
| **4 · Final review** | The one place the hold-out is judged. Shows how often this strategy has used it, and asks for confirmation before a re-use. Decision, gates, walk-forward, sensitivity, cost stress, downloads |
| **5 · Paper trading** | Simulated fills through the full risk stack; backtest-vs-paper comparison; failure drill. Warns if the version isn't ELIGIBLE |
| **6 · Monitor** | Kill-switch button, data health, upcoming events, live audit log (auto-refreshes) |
| **7 · Research log** | Your notes, plus every review and run, recorded automatically |

Everything the app records is plain text in `reports/`: `review_ledger.jsonl`
(every final review), `runs.jsonl` (every dev/paper run with its parameters) and
`research_log.jsonl` (your notes).

## Commands (CLI)

All commands can be run as `python -m fxlab.cli <cmd>` or, after `pip install -e .`,
as `fxlab <cmd>`. Every data command accepts `--strategy <file>` (any
`config/strategy_*.yaml`) and `--data <csv>`.

```powershell
# 1) generate the MOCK sample dataset (prices + events)
python -m fxlab.cli gen-sample

# 2) inspect data quality (gaps, bid/ask, completeness, MOCK flag)
python -m fxlab.cli quality

# 3) see upcoming economic events (UTC + America/Toronto)
python -m fxlab.cli events --hours 72

# 4) TUNE: backtest on the development slice only (hold-out untouched; repeat freely)
python -m fxlab.cli dev
#    (`backtest --save` runs on ALL data incl. the hold-out - for reference, not tuning)

# 5) full review -> reject / needs-investigation / eligible (writes reports/)
#    This judges the hold-out: run it once per idea. Re-runs are logged and warned about.
python -m fxlab.cli report

# 6) paper-trade the hold-out slice (SIMULATED fills) and compare to backtest
python -m fxlab.cli paper

#    ...and prove the safety path: force a protective-stop rejection
python -m fxlab.cli paper --inject-failure-at 50

# 7) operational status view (data health, events, risk, recent signals/errors)
python -m fxlab.cli status
```

**Kill switch:** create a file named `KILL_SWITCH` in the project root to halt all
new entries (`New-Item KILL_SWITCH`); delete it to resume.

## Project structure

```
config/        all tunable parameters (strategy, risk, news, backtest, review)
data/sample/   MOCK EUR/USD H1 bars + MOCK economic events (clearly labelled)
docs/          strategy guide, spec template, data-sources & live-boundary notes
fxlab/
  data/        price-data interface + quality checks
  econ/        economic calendar (FRED + sample) + news blackout
  strategy/    indicators, Strategy base, EUR/USD trend example
  backtest/    cost model, event-driven engine, metrics, robustness checks
  review/      evidence -> decision (reject / investigate / eligible)
  risk/        position sizing + stateful risk manager (the gatekeeper)
  paper/       broker interface, simulated broker, paper runner
  audit/       SQLite black-box recorder
  pipeline.py  one place that assembles everything from config
  workflow.py  one function per workflow step - shared by the CLI and dashboard
  journal.py   review ledger, run history, research notes (reports/*.jsonl)
  strategy_store.py  list/validate/save strategy files (versioned, comments kept)
  cli.py       the commands above
streamlit_app.py, ui_common.py, app_pages/   the dashboard
lean/          the same strategy for QuantConnect LEAN (needs Docker or QC)
scripts/       sample-data generator
tests/         sizing, blackout, look-ahead, risk, order failure, parity, workflow, dashboard
```

## How it avoids fooling you (the honest-research features)

- **No look-ahead:** indicators are causal; a signal on bar *i* executes at the
  **open of bar i+1**. Enforced and unit-tested (`tests/test_lookahead.py`).
- **Hold-out split:** data is split chronologically; the evaluation slice is judged
  separately and gates are applied to it, not the development slice.
- **Robustness:** walk-forward windows, parameter **sensitivity**, and a
  **cost-stress** run (doubled spread/slippage).
- **Costs are explicit:** every trade's `costs` line = spread + slippage +
  commission + swap, in account currency.
- **Metrics come with limitations:** each number is printed with what it *cannot*
  tell you (`fxlab/backtest/metrics.py`).

## Walkthrough — add a new strategy and decide if it's ready

See the end-to-end walkthrough below, then:

1. **Write the spec.** Copy `docs/strategy_spec_template.md`; fill every field.
2. **Create a config** `config/strategy_myidea.yaml` (copy the EUR/USD one).
3. **Implement the rules.** Add a `Strategy` subclass (e.g.
   `fxlab/strategy/my_idea.py`) returning the `signal / stop_distance /
   target_distance / reason` frame — look-ahead-safe (use only data ≤ current bar).
4. **Register it** in `fxlab/pipeline.py: STRATEGY_REGISTRY`.
5. **Add a test** that pins one expected behaviour (even a tiny one).
6. **Backtest & review:** `python -m fxlab.cli backtest` then `... report`.
7. **Read the decision:**
   - **REJECT** → a hard gate failed (e.g. lost money net of costs, PF < 1). Stop.
   - **NEEDS_INVESTIGATION** → promising but a gate missed; inspect the evidence,
     check sensitivity (does it only work at one parameter?), look for look-ahead
     or overfitting, consider more/different data. Do **not** cherry-pick.
   - **ELIGIBLE_FOR_PAPER** → run `python -m fxlab.cli paper` on the hold-out,
     compare observed vs expected, watch the invalidation conditions. Paper for a
     meaningful period before any human decision about going further.

## Testing

```powershell
python -m pytest -q
```

Covers position sizing, news-blackout windows, look-ahead prevention, risk limits,
order-failure handling, backtest/paper parity, the hold-out ledger, versioned
strategy saves, and every dashboard page (headless, via Streamlit `AppTest`). Tests
write only to a temporary folder, never to your real `config/` or `reports/`.

## Current status (what works vs what needs more)

- ✅ **Works now, offline:** data quality, calendar/blackout, backtest, review,
  paper simulation, audit log, status view, dashboard, full test suite (58 tests).
- 🔧 **Needs a (free) account/software, later:** LEAN local backtests
  (Docker), QuantConnect cloud/paper (QC account), official event **dates** (FRED
  key), real FX price history (your CSV or a data subscription).
- ⛔ **Intentionally out of scope:** live-money trading (see the live boundary doc).

See [`docs/data_sources.md`](docs/data_sources.md) for provenance and the honest
limitations of the news/time data.
