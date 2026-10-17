"""Step 7 - Research log: what you tried, what happened, and why you moved on."""
import pandas as pd
import streamlit as st

import ui_common
from fxlab import journal

ui_common.intro("log")
c = ui_common.cfg()
s = c["strategy"]
name, version = s["name"], str(s.get("version", "0"))

with st.form("note", clear_on_submit=True):
    kind = st.segmented_control("Type", journal.NOTE_KINDS, default="observation")
    text = st.text_area("Note", placeholder="e.g. Slower EMAs (30/80) cut trades to 70 and PF "
                        "to 0.8 on dev data. Not worth reviewing. Next idea: breakout.")
    if st.form_submit_button(f"Add note to {name} v{version}", icon=":material/add:", type="primary"):
        try:
            journal.add_note(strategy=name, version=version, kind=kind or "observation", text=text)
            st.toast("Note saved.", icon=":material/check_circle:")
        except ValueError as exc:
            st.error(str(exc), icon=":material/error:")

scope = st.segmented_control("Show", ["This strategy", "All strategies"], default="This strategy")
who = name if scope == "This strategy" else None

st.subheader("Notes", icon=":material/sticky_note_2:")
notes = journal.notes(who)
if notes:
    nd = pd.DataFrame([{"time (UTC)": n["ts_utc"].replace("T", " ")[:16], "strategy": n["strategy"],
                        "version": n["version"], "type": n["kind"], "note": n["text"]}
                       for n in reversed(notes)])
    st.dataframe(nd, hide_index=True, alt="Research notes, newest first")
    st.download_button("Download notes (CSV)", nd.to_csv(index=False), "research_log.csv",
                       "text/csv", icon=":material/download:")
else:
    st.caption("No notes yet. A line per idea - what you tried and why you kept or dropped it - "
               "stops you re-testing ideas you've already rejected.")

st.subheader("Final reviews", icon=":material/gavel:")
revs = journal.reviews(who)
if revs:
    st.dataframe(pd.DataFrame([{"time (UTC)": r["ts_utc"].replace("T", " ")[:16],
                                "strategy": r["strategy"], "version": r["version"],
                                "decision": r["decision"], "dataset": r["data"],
                                "why": "; ".join(r.get("reasons", []))}
                               for r in reversed(revs)]),
                 hide_index=True, alt="Every final review, newest first")
else:
    st.caption("Reviews are recorded here automatically.")

st.subheader("Runs", icon=":material/history:")
runs = journal.runs(strategy=who)
if runs:
    st.dataframe(pd.DataFrame([{"time (UTC)": r["ts_utc"].replace("T", " ")[:16], "kind": r["kind"],
                                "strategy": r["strategy"], "version": r["version"],
                                "trades": r["metrics"]["trade_count"],
                                "net %": r["metrics"]["net_return_pct"],
                                "PF": r["metrics"]["profit_factor"]}
                               for r in reversed(runs)]),
                 hide_index=True, alt="Every dev backtest and paper run, newest first")
st.caption("Stored as plain text in `reports/research_log.jsonl`, `review_ledger.jsonl` and "
           "`runs.jsonl`, so you can open them in any editor.")
