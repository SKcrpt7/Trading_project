# A beginner's guide to the three strategy families

This guide explains the three classic rule-based strategy families this project
is built around. For each one you get: the **market hypothesis** (why anyone
believes it could work), a concrete **forex example**, **when and why it fails**,
and the **exact rules** you would need to automate it.

Read this first. Everything else in the repo — the spec template, the backtester,
the review gates — exists to test the claims made below *honestly*, on your data,
with realistic costs. None of these strategies is profitable by default. The
whole point of the system is to let you find out, without fooling yourself.

A note that matters more than any rule below: **a strategy is a hypothesis, not a
fact.** The job of a backtest is to try hard to *disprove* it. If it survives, you
get cautious interest and a paper-trading trial — never certainty.

---

## 1. Trend following

**Hypothesis.** Prices sometimes move in persistent directional runs (driven by
slow repricing of interest-rate expectations, capital flows, positioning). If you
enter in the direction of an established move and let winners run while cutting
losers quickly, the occasional large win can pay for many small losses.

**Forex example (EUR/USD).** A central-bank policy divergence (e.g. the Fed hiking
while the ECB holds) can push EUR/USD lower for weeks. A trend follower shorts
after momentum confirms the move and holds with a trailing or wide stop.

**Exact automatable rules (this repo's example).**
- Compute a fast EMA (20) and a slow EMA (50) on H1 closes.
- **Long** when the fast EMA crosses *above* the slow EMA *and* price is above the
  slow EMA. **Short** on the mirror condition.
- Protective stop at `2.0 × ATR(14)` from entry.
- Target at `1.5 ×` the stop distance (or exit on the opposite cross).

**When it fails.**
- **Choppy, range-bound markets.** Crossovers whipsaw: you buy the top, sell the
  bottom, repeat. Trend followers typically have a *low win rate* (e.g. 35–45%)
  and rely on a few big trends; a year without trends bleeds money.
- **News gaps and spikes** can jump the stop. Costs (spread + slippage) accumulate
  because of frequent entries/exits.
- **Over-fitting the EMA lengths** to one period of history. (This is exactly what
  the sensitivity test in this repo checks.)

---

## 2. Breakout

**Hypothesis.** When price escapes a well-defined range or prior extreme, it can
trigger stop orders and attract momentum, producing a fast follow-through move.
You try to catch the start of that expansion.

**Forex example (GBP/USD around a session).** During the quiet Asian session a pair
coils in a tight range. At the London open, volume surges; a break above the Asian
high often runs. A breakout system buys the break of the prior range high.

**Exact automatable rules (sketch).**
- Define the range: highest high / lowest low of the prior `N` bars
  (Donchian channel — see `fxlab/strategy/indicators.py: donchian_high/low`).
- **Long** when price closes above the prior `N`-bar high; **short** below the low.
- Optional filter: only take breakouts during a chosen session (e.g. London open).
- Stop below the range (or `k × ATR`); target a multiple of the range width.

**When it fails.**
- **False breakouts ("fakeouts").** Price pokes through, triggers entries, then
  reverses back into the range. Ranges are where most bars live, so false signals
  are common.
- **Already-extended moves.** Breaking out after a long run can be the exhaustion
  point. Breakout entries also pay the *worst* spread/slippage because you enter
  into fast-moving prices.
- **Illiquid hours** widen spreads and distort the "range".

> This repo ships the trend example wired end-to-end; breakout and mean reversion
> are documented here and can be added by implementing the same `Strategy`
> interface (see the walkthrough in the README).

---

## 3. Mean reversion

**Hypothesis.** Prices oscillate around a fair value and *over-react* in the short
term. After an unusually large move away from a reference (a moving average, a
band), price tends to snap back. You fade the extreme.

**Forex example (EUR/USD intraday).** During a calm, range-bound week, EUR/USD
stretches ~2 standard deviations below its 20-period average on H1 with no news.
A mean-reversion system buys the dip expecting a bounce back toward the average.

**Exact automatable rules (sketch).**
- Reference = SMA(20). Bands = reference ± `z × rolling_std` (Bollinger-style), or
  use RSI(14) thresholds (e.g. <30 oversold, >70 overbought).
- **Long** when price is below the lower band *and* RSI < 30; exit at the mean.
- **Short** on the mirror condition.
- Tight-ish stop beyond the band; target = reversion to the reference.

**When it fails — and this is the dangerous one.**
- **Trends and regime breaks.** "Oversold" in a crash just gets more oversold.
  Mean reversion often has a *high win rate* but occasional *catastrophic* losers
  — the opposite risk shape of trend following. A too-loose or missing stop can
  wipe out months of small gains in one move.
- **News.** A surprise release invalidates the "fair value" assumption instantly.
  This is a prime reason for the news-blackout rule.
- **Picking tops/bottoms** is inherently fighting momentum; sizing discipline and
  a hard stop are non-negotiable.

---

## How these map to the system

| Concern | Where it lives |
|---|---|
| Exact rules, parameters | `config/strategy_*.yaml` + a `Strategy` subclass |
| Realistic costs | `config/backtest.yaml` + `fxlab/backtest/costs.py` |
| News avoidance | `config/news.yaml` + `fxlab/econ/blackout.py` |
| "Did I fool myself?" | walk-forward, sensitivity, cost-stress, hold-out split |
| The verdict | `fxlab/review/report.py` → reject / investigate / eligible |
| Safe forward test | `fxlab/paper/` (simulated), never live by default |

**The honest summary:** trend following survives bad ranges by cutting losses fast;
mean reversion survives bad entries only if the stop is respected; breakout lives
or dies on false signals and entry costs. Test each on *out-of-sample* data with
*worse-than-expected* costs before you believe anything.
