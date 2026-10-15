"""Economic-event calendar.

Stores scheduled releases in UTC and can display them in America/Toronto.

Two providers:
  * sample : bundled curated MOCK events (always available, clearly labelled).
  * fred   : official release DATES from FRED (https://fred.stlouisfed.org). FRED
             gives the DATE a series is released; it does NOT give a guaranteed
             intraday timestamp, so we attach the CONVENTIONAL US release time
             (e.g. 08:30 ET for CPI/NFP) and mark time_is_exact=False.

DATA-INTEGRITY RULE: events are only usable in a backtest at or after time_utc.
When time_is_exact is False, downstream code widens blackout windows and refrains
from precise event-driven logic, rather than pretending the time is known.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from fxlab.config import DISPLAY_TZ, get_secret
from fxlab.types import EconomicEvent


class EventCalendar:
    def __init__(self, events: list[EconomicEvent]):
        # Always keep sorted by UTC time.
        self.events = sorted(events, key=lambda e: e.time_utc)

    def __len__(self) -> int:
        return len(self.events)

    # ---------- constructors ----------
    @classmethod
    def from_sample_csv(cls, path: str | Path) -> "EventCalendar":
        df = pd.read_csv(path)
        df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
        events = [
            EconomicEvent(
                time_utc=row.time_utc.to_pydatetime(),
                country=str(row.country),
                title=str(row.title),
                impact=str(row.impact),
                source=str(getattr(row, "source", "sample")),
                time_is_exact=bool(getattr(row, "time_is_exact", False)),
            )
            for row in df.itertuples()
        ]
        return cls(events)

    @classmethod
    def from_config(cls, news_cfg: dict, sample_path: str | Path) -> "EventCalendar":
        """Build according to config/news.yaml 'provider' setting, with graceful
        fallback to the sample set if FRED is requested but unavailable."""
        provider = str(news_cfg.get("provider", "sample")).lower()
        if provider == "fred":
            api_key = get_secret("FRED_API_KEY")
            if not api_key:
                print("[news] provider=fred but FRED_API_KEY not set -> falling back to sample events.")
                return cls.from_sample_csv(sample_path)
            try:
                from fxlab.econ.fred_provider import fetch_fred_events
                events = fetch_fred_events(api_key, news_cfg)
                if not events:
                    print("[news] FRED returned no events -> falling back to sample events.")
                    return cls.from_sample_csv(sample_path)
                return cls(events)
            except Exception as exc:  # network / API issues must never crash research
                print(f"[news] FRED fetch failed ({exc}) -> falling back to sample events.")
                return cls.from_sample_csv(sample_path)
        return cls.from_sample_csv(sample_path)

    # ---------- queries ----------
    def between(self, start: datetime, end: datetime,
                min_impact: Optional[str] = None) -> list[EconomicEvent]:
        order = {"low": 0, "medium": 1, "high": 2}
        floor = order.get((min_impact or "low").lower(), 0)
        return [e for e in self.events
                if start <= e.time_utc <= end and order.get(e.impact.lower(), 0) >= floor]

    def upcoming(self, now: datetime, within_hours: int = 48,
                 min_impact: Optional[str] = None) -> list[EconomicEvent]:
        return self.between(now, now + timedelta(hours=within_hours), min_impact)

    def to_dataframe(self, display_tz: str = DISPLAY_TZ) -> pd.DataFrame:
        rows = []
        for e in self.events:
            local = e.time_utc.astimezone(_tz(display_tz))
            rows.append({
                "time_utc": e.time_utc,
                f"time_{display_tz.replace('/', '_')}": local,
                "country": e.country, "title": e.title, "impact": e.impact,
                "source": e.source, "time_is_exact": e.time_is_exact,
            })
        return pd.DataFrame(rows)


def _tz(name: str):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return timezone.utc
