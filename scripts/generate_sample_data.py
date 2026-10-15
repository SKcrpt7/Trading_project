"""Generate MOCK EUR/USD H1 data and a MOCK economic-events file.

!!! THIS IS SYNTHETIC DATA. IT IS NOT REAL MARKET DATA. !!!
It exists only so the whole pipeline can be demonstrated end-to-end without any
paid subscription or broker. Every row is tagged source='MOCK'. Never draw
conclusions about real markets from results produced on this data.

The generator is SEEDED, so it is reproducible. It deliberately:
  * injects a couple of missing periods (to exercise data-quality checks),
  * restricts bars to weekday trading hours,
  * builds a bid/ask spread around the mid price.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sample"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
START = datetime(2021, 1, 4, 0, 0, tzinfo=timezone.utc)   # a Monday
END = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
SPREAD_PIPS_MEAN = 1.0
PIP = 0.0001


def generate_prices() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)

    # Build the hourly timestamp index for weekday hours only (Mon 00:00 - Fri 23:00).
    hours = []
    t = START
    while t < END:
        if t.weekday() < 5:  # 0=Mon .. 4=Fri
            hours.append(t)
        t += timedelta(hours=1)
    idx = pd.DatetimeIndex(hours, tz="UTC")
    n = len(idx)

    # Mid price: geometric random walk with slowly switching drift regimes so that
    # trend and mean-reversion phases both appear (makes the demo interesting but
    # is NOT meant to resemble real EUR/USD dynamics).
    regime_len = 500
    drift = np.zeros(n)
    for start in range(0, n, regime_len):
        d = rng.normal(0.0, 0.00003)
        drift[start:start + regime_len] = d
    vol = 0.0010  # ~10 pip hourly sigma
    shocks = rng.normal(0, vol, n)
    log_ret = drift + shocks
    mid = 1.08 * np.exp(np.cumsum(log_ret))

    # Build OHLC from the mid by simulating intrabar range.
    rng2 = np.random.default_rng(SEED + 1)
    rng_range = np.abs(rng2.normal(0, vol, n)) + 0.5 * vol
    close = mid
    openp = np.empty(n)
    openp[0] = mid[0]
    openp[1:] = close[:-1]
    high = np.maximum(openp, close) + rng_range
    low = np.minimum(openp, close) - rng_range

    # Spread (in price) around the mid, slightly wider at session edges.
    spread_pips = np.clip(rng2.normal(SPREAD_PIPS_MEAN, 0.3, n), 0.3, 4.0)
    spread = spread_pips * PIP
    volume = rng2.integers(200, 2000, n).astype(float)

    df = pd.DataFrame(
        {
            "timestamp": idx,
            "open": openp,
            "high": high,
            "low": low,
            "close": close,
            "spread": spread,
            "volume": volume,
            "source": "MOCK",
        }
    )
    df["bid"] = df["close"] - spread / 2.0
    df["ask"] = df["close"] + spread / 2.0

    # Inject two missing periods to test gap detection.
    # (a) a 6-hour gap, (b) a full missing day.
    gap_a_start = idx[2000]
    gap_a_mask = (df["timestamp"] >= gap_a_start) & (df["timestamp"] < gap_a_start + timedelta(hours=6))
    gap_b_day = idx[5000].date()
    gap_b_mask = df["timestamp"].dt.date == gap_b_day
    df = df[~(gap_a_mask | gap_b_mask)].reset_index(drop=True)

    # Round to sensible precision.
    for col in ["open", "high", "low", "close", "bid", "ask"]:
        df[col] = df[col].round(5)
    df["spread"] = df["spread"].round(6)
    return df


def generate_events() -> pd.DataFrame:
    """A small curated set of MOCK high-impact events across the sample period.
    time_is_exact is True here only because we are inventing the data for a demo;
    in real use, conventional times would be flagged False. These are clearly MOCK.
    """
    rows = []
    # Monthly-ish CPI and NFP, quarterly FOMC-like, across 2021-2023.
    for year in (2021, 2022, 2023):
        for month in range(1, 13):
            # CPI ~ mid month 08:30 ET (13:30 UTC during EDT; we store a fixed UTC for demo)
            rows.append((datetime(year, month, 12, 13, 30, tzinfo=timezone.utc),
                         "US", "CPI", "high"))
            # NFP ~ first Friday 08:30 ET
            rows.append((datetime(year, month, 7, 13, 30, tzinfo=timezone.utc),
                         "US", "NFP", "high"))
        # FOMC-like decisions, four per year, 14:00 ET (~19:00 UTC demo)
        for month in (3, 6, 9, 12):
            rows.append((datetime(year, month, 15, 19, 0, tzinfo=timezone.utc),
                         "US", "FOMC", "high"))

    df = pd.DataFrame(rows, columns=["time_utc", "country", "title", "impact"])
    df["source"] = "MOCK"
    df["time_is_exact"] = True   # MOCK data; see note above
    df = df.sort_values("time_utc").reset_index(drop=True)
    return df


def main() -> None:
    prices = generate_prices()
    events = generate_events()
    price_path = OUT_DIR / "EURUSD_H1_sample.csv"
    events_path = OUT_DIR / "economic_events_sample.csv"
    prices.to_csv(price_path, index=False)
    events.to_csv(events_path, index=False)
    print(f"[MOCK] Wrote {len(prices):,} price bars -> {price_path}")
    print(f"[MOCK] Wrote {len(events):,} economic events -> {events_path}")
    print(f"[MOCK] Price range: {prices['timestamp'].min()} .. {prices['timestamp'].max()}")


if __name__ == "__main__":
    main()
