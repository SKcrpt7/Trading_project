"""Step 1 - Data: is the data trustworthy enough to test on?"""
import runpy
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

import ui_common
from fxlab import config, strategy_store, workflow
from fxlab.data.interface import CsvPriceProvider

ui_common.intro("data")
c = ui_common.cfg()
data = ui_common.data(c)
q = data.quality()
_, hold = workflow.split(data, c)
dev_pct = int(c["backtest"]["evaluation"]["dev_fraction"] * 100)

if data.source.upper() == "MOCK":
    st.warning("Synthetic sample data: good for learning the workflow, not for judging a strategy.",
               icon=":material/science:")

# ---- quality tiles -------------------------------------------------------- #
st.subheader("Quality", icon=":material/fact_check:")
st.caption(f"`{ui_common.data_path().name}` · {data.symbol} {data.timeframe} · {data.source} · "
           f"{q.start:%Y-%m-%d} → {q.end:%Y-%m-%d} UTC")
tiles = [
    ("Bars", f"{q.n_bars:,}", f"Expected about {q.expected_bars:,} weekday bars."),
    ("Complete", f"{q.completeness_pct}%", "Bars present vs expected. Below ~98% deserves a look."),
    ("Gaps", f"{len(q.missing_periods)}", "Missing stretches on weekdays (weekends excluded)."),
    ("Bad bars", f"{q.n_bad_ohlc + q.n_nonpositive_price}", "Broken OHLC (e.g. high < low) or prices ≤ 0."),
    ("Duplicates", f"{q.n_duplicate_timestamps}", "Repeated timestamps."),
    ("Bid / ask", "Yes" if q.has_bid_ask else "No", "Without bid/ask the spread is assumed, not observed."),
]
with st.container(horizontal=True, gap="small"):
    for label, value, help_ in tiles:
        st.metric(label, value, help=help_, border=True, width=150)

# ---- price chart ---------------------------------------------------------- #
st.subheader("Price and hold-out", icon=":material/show_chart:")
daily = data.df["close"].resample("1D").last().dropna().rename_axis("time").reset_index()
ui_common.price_chart(daily, hold.df.index[0],
                      alt_text=f"Daily {data.symbol} close; the last {100 - dev_pct}% is shaded as the hold-out")
st.caption(f"Shaded = hold-out, from **{hold.df.index[0]:%Y-%m-%d %H:%M} UTC** (last {100 - dev_pct}%).")
if q.missing_periods:
    with st.expander(f"Gaps ({len(q.missing_periods)})", icon=":material/report:"):
        st.dataframe(pd.DataFrame(q.missing_periods, columns=["missing from", "missing until"]),
                     hide_index=True, alt="Missing data periods")

# ---- add data ------------------------------------------------------------- #
st.subheader("Use your own data", icon=":material/upload_file:")
with st.container(border=True):
    up = st.file_uploader(
        f"Price CSV ({data.symbol} {data.timeframe})", type=["csv"],
        help="Columns: `timestamp` (UTC), `open`, `high`, `low`, `close`. Recommended: `bid`, "
             "`ask`. Optional: `source` (e.g. dukascopy), shown on every result.")
    if up is not None and st.button("Check and add", icon=":material/upload:", type="primary"):
        stem = strategy_store.slugify(Path(up.name).stem) or "prices"
        target = Path(config.USER_DATA_DIR) / f"{stem}.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(up.getvalue())
        try:
            loaded = CsvPriceProvider(target).load(data.symbol, data.timeframe)
            if len(loaded.df) < 100:
                raise ValueError(f"only {len(loaded.df)} rows - too few to test anything")
            uq = loaded.quality()
        except Exception as exc:
            target.unlink(missing_ok=True)
            st.error(f"{exc}", icon=":material/error:", title="File rejected")
        else:
            ui_common.select_after_rerun(
                "dataset", f"Uploaded: {target.name}",
                flash=f"Added {target.name}: {uq.n_bars:,} bars, {uq.completeness_pct}% complete.")

with st.expander("Maintenance", icon=":material/build:"):
    if st.button("Regenerate sample data", icon=":material/refresh:",
                 help="Re-creates the bundled MOCK dataset (seeded, so you get the same data back)."):
        with st.spinner("Generating..."):
            runpy.run_path(str(config.PROJECT_ROOT / "scripts" / "generate_sample_data.py"),
                           run_name="__main__")
        st.toast("Sample data regenerated.", icon=":material/check_circle:")

# ---- events --------------------------------------------------------------- #
st.subheader("Economic events", icon=":material/event:")
cal = workflow.event_calendar(c)
upcoming = cal.upcoming(datetime.now(timezone.utc), 72, "high")
st.caption(f"{len(cal)} events ({c['news'].get('provider', 'sample')}) · {len(upcoming)} high-impact "
           "in the next 72 h · used for the news blackout.")
impact = st.pills("Impact", ["high", "medium", "low"], selection_mode="multi", default=["high"],
                  label_visibility="collapsed")
ev = cal.to_dataframe()
if len(ev):
    ev = ev[ev["impact"].isin(impact or ["high", "medium", "low"])]
    ev = ev.rename(columns={"time_America_Toronto": "Toronto", "time_utc": "UTC"})
    st.dataframe(ev, hide_index=True, alt="Economic event calendar",
                 column_order=["Toronto", "title", "impact", "country", "time_is_exact", "UTC", "source"],
                 column_config={
                     "UTC": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                     "Toronto": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                     "time_is_exact": st.column_config.CheckboxColumn(
                         "Exact time", help="Unchecked = conventional release time; the blackout is widened."),
                 })

ui_common.next_step("data")
