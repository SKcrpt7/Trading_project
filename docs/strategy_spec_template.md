# Strategy specification template

Copy this when defining a new strategy. Every field should be answerable *before*
you write code. If you cannot state a rule precisely enough to automate it, it is
not ready to test. The matching machine-readable version is a YAML file in
`config/` (see `config/strategy_eurusd_trend.yaml` for a filled-in example).

---

## Identity
- **Name:** short unique id (e.g. `eurusd_trend_ema`)
- **Version:** bump when rules/params change (e.g. `0.1.0`)
- **Family:** trend_following | breakout | mean_reversion | other
- **One-line description:** what it does, in plain English.
- **Market hypothesis:** *why* you believe this could have an edge.

## Market & timeframe
- **Pair(s):** e.g. EUR/USD
- **Timeframe:** bar size for signals (e.g. H1)
- **Trading session:** which hours (in UTC) and days you will trade, and why
  (liquidity, volatility). State the display timezone too (America/Toronto).

## Entry rules
- Exact, testable conditions evaluated **on closed bars only**.
- Every indicator and its parameters (periods, thresholds).
- Long conditions and short conditions stated separately.

## Exit rules
- **Protective stop:** where and how computed (e.g. `2 × ATR(14)`). This is
  mandatory for automation.
- **Target / take-profit:** where (e.g. `1.5 ×` stop distance), or the rule for a
  discretionary-free exit (opposite signal, time stop).
- **Time stop:** max bars to hold before giving up (optional).

## Position sizing
- **Method:** e.g. fixed-fractional risk.
- **Risk per trade:** % of equity risked if the stop is hit.
- Any scaling/pyramiding rules (default: none).

## Risk limits (account level — usually inherited from `config/risk.yaml`)
- Max risk per trade, max daily loss, max open positions, max spread, stale-data
  threshold.

## News restrictions
- Which events (impact level, which releases) and the blackout window
  (minutes before / after). Whether to widen for uncertain (conventional) times.

## Invalidation conditions
- The concrete, observable conditions under which you will **stop trusting** this
  strategy (e.g. live drawdown exceeds 1.5× backtest max; realised spread
  persistently 2× modelled; N consecutive losses beyond backtest worst streak).
  These feed monitoring in paper trading.

## Evidence required to advance (review gates)
- The thresholds (in `config/review_thresholds.yaml`) that map backtest evidence
  to **reject / needs-investigation / eligible-for-paper**. State any you override
  and why.

---

### Reminder
A completed spec + a passing review means the strategy may go to **paper trading
only**. It is never permission to trade live money and never a prediction of
profit.
