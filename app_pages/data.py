"""Step 1 - Data: is the data trustworthy enough to test on?"""
import runpy
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

import ui_common
from fxlab import config, strategy_store, workflow
from fxlab.data.interface import CsvPriceProvider

c = ui_common.cfg()
data = ui_common.data(c)
q = data.quality()
_, hold = workflow.split(data, c)

if data.source.upper() == "MOCK":
    st.warning("This is synthetic sample data. Use it to learn the workflow; load real "
               "hourly data with bid/ask prices before trusting any result.",
               icon=":material/warning:", title="Mock data")

# ---- quality tiles -------------------------------------------------------- #
st.subheader("Quality report")
st.caption(f"`{ui_common.data_path().name}` · {data.symbol} {data.timeframe} · source "
           f"**{data.source}** · {q.start:%Y-%m-%d} → {q.end:%Y-%m-%d} (UTC)")
tiles = [
    ("Bars", f"{q.n_bars:,}", f"Expected about {q.expected_bars:,} weekday bars."),
    ("Completeness", f"{q.completeness_pct}%", "Bars present vs expected. Below ~98% deserves a look."),
    ("Gaps", f"{len(q.missing_periods)}", "Missing stretches on weekdays (weekends are excluded)."),
    ("Bad bars", f"{q.n_bad_ohlc + q.n_nonpositive_price}", "Broken OHLC (e.g. high < low) or prices <= 0."),
    ("Duplicates", f"{q.n_duplicate_timestamps}", "Repeated timestamps."),
    ("Bid / ask", "Yes" if q.has_bid_ask else "No", "Without bid/ask the spread is assumed, not observed."),
]
for col, (label, value, help_) in zip(st.columns(len(tiles)), tiles):
    col.metric(label, value, help=help_, border=True, height="stretch")
for note in q.notes:
    st.caption(f":material/info: {note}")

# ---- price chart ---------------------------------------------------------- #
st.subheader("Price history and the hold-out")
daily = data.df["close"].resample("1D").last().dropna().rename_axis("time").reset_index()
ui_common.price_chart(daily, hold.df.index[0],
                      alt_text=f"Daily {data.symbol} close; the last "
                               f"{100 - int(c['backtest']['evaluation']['dev_fraction'] * 100)}% "
                               "is shaded as the hold-out")
st.caption(f"Development: first {int(c['backtest']['evaluation']['dev_fraction'] * 100)}% of bars. "
           f"Hold-out (shaded): from **{hold.df.index[0]:%Y-%m-%d %H:%M} UTC**. "
           "The split comes from `config/backtest.yaml` → `evaluation.dev_fraction`.")

if q.missing_periods:
    with st.expander(f"Gaps ({len(q.missing_periods)})", icon=":material/report:"):
        st.dataframe(pd.DataFrame(q.missing_periods, columns=["missing from", "missing until"]),
                     hide_index=True, alt="Missing data periods")

# ---- add data ------------------------------------------------------------- #
st.subheader("Use your own data")
with st.container(border=True):
    st.markdown(
        "CSV with a `timestamp` column in **UTC** plus `open, high, low, close`. Optional: "
        "`bid, ask` (strongly recommended) and `source` (e.g. `dukascopy`), which is shown "
        "on every result. The symbol and timeframe must match the strategy "
        f"(**{data.symbol} {data.timeframe}**)."
    )
    up = st.file_uploader("Price CSV", type=["csv"])
    if up is not None and st.button("Check and add this file", icon=":material/upload:", type="primary"):
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
                flash=f"Added {target.name}: {uq.n_bars:,} bars, {uq.completeness_pct}% complete, "
                      f"{len(uq.missing_periods)} gaps. It is now the active dataset.")

with st.expander("Maintenance", icon=":material/build:"):
    st.caption("Re-creates the bundled MOCK dataset. It is seeded, so you get the same "
               "data back. Useful if the sample files were edited or deleted.")
    if st.button("Regenerate sample data", icon=":material/refresh:"):
        with st.spinner("Generating..."):
            runpy.run_path(str(config.PROJECT_ROOT / "scripts" / "generate_sample_data.py"),
                           run_name="__main__")
        st.success("Sample data regenerated.", icon=":material/check_circle:")

# ---- events --------------------------------------------------------------- #
st.subheader("Economic events (news blackout input)")
cal = workflow.event_calendar(c)
now = datetime.now(timezone.utc)
upcoming = cal.upcoming(now, 72, "high")
st.caption(f"{len(cal)} events from provider **{c['news'].get('provider', 'sample')}** "
           f"(`config/news.yaml`). {len(upcoming)} high-impact event(s) in the next 72 hours. "
           "Times with `time_is_exact = false` are conventional release times, so the "
           "blackout window is widened around them.")
impact = st.pills("Impact", ["high", "medium", "low"], selection_mode="multi", default=["high"])
ev = cal.to_dataframe()
if len(ev):
    ev = ev[ev["impact"].isin(impact or ["high", "medium", "low"])]
    ev = ev.rename(columns={"time_America_Toronto": "time (Toronto)", "time_utc": "time (UTC)"})
    st.dataframe(ev, hide_index=True, alt="Economic event calendar",
                 column_config={
                     "time (UTC)": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                     "time (Toronto)": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                 })
