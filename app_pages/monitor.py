"""Step 6 - Monitor: safety controls, audit log and upcoming events. Refreshes itself."""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

import ui_common
from fxlab import config, workflow
from fxlab.audit.store import VALID_CATEGORIES, AuditStore

c = ui_common.cfg()

# ---- kill switch (outside the fragment: toggling it must redraw the sidebar too) --- #
with st.container(border=True):
    on = workflow.kill_switch_active(c)
    left, right = st.columns([3, 1], vertical_alignment="center")
    with left:
        st.markdown("**Kill switch** · " + (":red[**ACTIVE** - all new entries are blocked]" if on
                                            else "inactive - entries allowed (paper only)"))
        st.caption(f"It's a file named `{c['risk']['controls']['kill_switch_file']}` in the project "
                   "folder, checked before every entry. You can also create or delete it by hand. "
                   "Every toggle is written to the audit log.")
    with right:
        if on:
            if st.button("Deactivate", icon=":material/play_arrow:", width="stretch"):
                workflow.set_kill_switch(c, False)
                st.rerun()
        elif st.button("Activate", icon=":material/stop_circle:", type="primary", width="stretch"):
            workflow.set_kill_switch(c, True)
            st.rerun()

category = st.pills("Audit categories", sorted(VALID_CATEGORIES), selection_mode="multi",
                    help="Leave empty to show all categories.")
limit = st.select_slider("Rows to show", [25, 50, 100, 250, 500], value=50)


@st.fragment(run_every="15s")
def live_panel():
    data = ui_common.data(c)
    q = data.quality()
    now = datetime.now(timezone.utc)
    up = workflow.event_calendar(c).upcoming(now, 48, "high")

    t = st.columns(4)
    t[0].metric("Live trading", "Disabled", help="Hard-disabled in fxlab/paper/broker_interface.py.",
                border=True, height="stretch")
    t[1].metric("Data", f"{q.completeness_pct}% complete",
                help=f"{q.n_bars:,} bars, {len(q.missing_periods)} gaps, source {q.source}.",
                border=True, height="stretch")
    t[2].metric("High-impact events (48h)", f"{len(up)}",
                help="Next: " + (f"{up[0].title} {up[0].time_utc:%Y-%m-%d %H:%M} UTC" if up else "none"),
                border=True, height="stretch")

    if not Path(config.AUDIT_DB).exists():
        t[3].metric("Audit errors", "0", border=True, height="stretch")
        st.caption("No audit log yet. Run a paper simulation first.")
        return
    audit = AuditStore(config.AUDIT_DB)
    try:
        n_err = audit.count("error")
        t[3].metric("Audit errors", f"{n_err}", help="All-time count across every run.",
                    border=True, height="stretch")
        counts = {cat: audit.count(cat) for cat in sorted(VALID_CATEGORIES)}
        rows = []
        for cat in (category or [None]):
            rows += audit.recent(limit, cat)
    finally:
        audit.close()

    st.caption("All-time totals: " + " · ".join(f"{k} {v:,}" for k, v in counts.items() if v)
               + f" · refreshed {now:%H:%M:%S} UTC")
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values("id", ascending=False).head(limit)
        st.dataframe(df[["id", "ts_utc", "category", "strategy", "message", "data_json"]],
                     hide_index=True, alt="Most recent audit log entries",
                     column_config={"ts_utc": "time (UTC, simulated bar time for paper runs)",
                                    "data_json": st.column_config.JsonColumn("data")})


live_panel()
st.caption("Paper-run entries carry the simulated bar's time, so they show historical dates. "
           "The audit log is append-only; nothing here deletes it.")
