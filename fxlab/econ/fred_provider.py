"""FRED economic-release provider.

FRED (Federal Reserve Economic Data, St. Louis Fed) exposes a free API of
official US economic series and their RELEASE DATES. Docs:
  https://fred.stlouisfed.org/docs/api/fred/

What FRED gives us: the DATE a release is published (releases/dates endpoint).
What FRED does NOT give us: the exact intraday publication TIME. So we attach a
documented CONVENTIONAL time (e.g. 08:30 America/New_York for CPI/NFP) and set
time_is_exact=False. That flag tells the rest of the system to stay conservative.

This keeps us honest: we use OFFICIAL dates and clearly-labelled conventional
times, and we never fabricate a precise timestamp we cannot verify.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Optional

import requests

from fxlab.types import EconomicEvent

FRED_BASE = "https://api.stlouisfed.org/fred"

# FRED "release" IDs for the headline US releases most relevant to EUR/USD.
# (Release IDs are stable; see https://fred.stlouisfed.org/releases)
RELEASES = {
    10: ("CPI", "CPI"),                       # Consumer Price Index
    50: ("NFP", "Employment Situation"),      # includes Nonfarm Payrolls
    53: ("GDP", "Gross Domestic Product"),
    101: ("RETAIL_SALES", "Advance Retail Sales"),
}

_EASTERN = "America/New_York"


def _conventional_time(kind: str, news_cfg: dict) -> time:
    table = news_cfg.get("conventional_times_eastern", {})
    hhmm = table.get(kind, "08:30")
    h, m = map(int, hhmm.split(":"))
    return time(h, m)


def _to_utc(date_str: str, t: time) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(_EASTERN)
    except Exception:  # pragma: no cover
        from datetime import timezone
        tz = timezone.utc
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    local = datetime.combine(d, t).replace(tzinfo=tz)
    from datetime import timezone as _tz
    return local.astimezone(_tz.utc)


def fetch_fred_events(
    api_key: str,
    news_cfg: dict,
    start: str = "2015-01-01",
    end: Optional[str] = None,
    timeout: int = 20,
) -> list[EconomicEvent]:
    """Fetch official release DATES and attach conventional times.

    Returns EconomicEvent objects with time_is_exact=False (date is official,
    intraday time is conventional).
    """
    events: list[EconomicEvent] = []
    params_common = {"api_key": api_key, "file_type": "json"}
    for release_id, (kind, title) in RELEASES.items():
        url = f"{FRED_BASE}/release/dates"
        params = {**params_common, "release_id": release_id,
                  "realtime_start": start, "include_release_dates_with_no_data": "false"}
        if end:
            params["realtime_end"] = end
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        conv_t = _conventional_time(kind, news_cfg)
        for rd in data.get("release_dates", []):
            date_str = rd.get("date")
            if not date_str:
                continue
            events.append(EconomicEvent(
                time_utc=_to_utc(date_str, conv_t),
                country="US", title=kind, impact="high",
                source="FRED(release_date)+conventional_time",
                time_is_exact=False,
            ))
    return events
