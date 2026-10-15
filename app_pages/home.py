"""Home: where am I in the workflow, and what should I do next?"""
import streamlit as st

import ui_common
from fxlab import journal, workflow

c = ui_common.cfg()
s = c["strategy"]
name, version = s["name"], str(s.get("version", "0"))
data = ui_common.data(c)
fp = journal.data_fingerprint(data)
q = data.quality()

dev_runs = [r for r in journal.runs("dev", name) if r["version"] == version and r["data"] == fp]
paper_runs = [r for r in journal.runs("paper", name) if r["version"] == version and r["data"] == fp]
decision = journal.latest_decision(name, version, fp)
uses = journal.holdout_uses(name, fp)

st.caption(f"Strategy **{name} v{version}** · {s['symbol']} {s['timeframe']} · "
           f"dataset `{ui_common.data_path().name}` ({data.source})")

data_ok = q.n_bad_ohlc == 0 and q.n_duplicate_timestamps == 0 and q.completeness_pct >= 95
# (done?, title, status line, page)
steps = [
    (data_ok, "1 · Check the data",
     f"{q.n_bars:,} bars, {q.completeness_pct}% complete, {len(q.missing_periods)} gaps"
     + ("" if data_ok else " - fix the data first"), "app_pages/data.py"),
    (True, "2 · Define the strategy", f"Version {version}. Change parameters to start a new version.",
     "app_pages/strategy.py"),
    (bool(dev_runs), "3 · Tune on development data",
     f"{len(dev_runs)} dev run(s) of this version" if dev_runs else "Not run for this version yet",
     "app_pages/dev_backtest.py"),
    (decision is not None, "4 · Final review (once)",
     f"{decision['decision']} · hold-out used {uses}x by this strategy" if decision
     else ("Not reviewed. " + (f"Hold-out already used {uses}x by older versions."
                               if uses else "Hold-out untouched.")),
     "app_pages/review.py"),
    (bool(paper_runs), "5 · Paper trade",
     f"{len(paper_runs)} paper run(s)" if paper_runs else "Not run for this version yet",
     "app_pages/paper.py"),
    (True, "6 · Monitor", "Kill switch, audit log, upcoming events.", "app_pages/monitor.py"),
    (bool(journal.notes(name)), "7 · Keep a research log",
     f"{len(journal.notes(name))} note(s) for this strategy", "app_pages/research_log.py"),
]

# Suggested next step = first unfinished step among 1-5, guided by the decision.
if not data_ok:
    nxt = steps[0]
elif not dev_runs:
    nxt = steps[2]
elif decision is None:
    nxt = steps[3]
elif decision["decision"] == "ELIGIBLE_FOR_PAPER" and not paper_runs:
    nxt = steps[4]
elif decision["decision"] != "ELIGIBLE_FOR_PAPER":
    nxt = steps[6]
else:
    nxt = steps[5]

with st.container(border=True):
    st.markdown(f"**Suggested next step: {nxt[1]}**")
    if decision and decision["decision"] != "ELIGIBLE_FOR_PAPER" and nxt is steps[6]:
        st.caption("This version did not pass review. Record what you learned, then start a "
                   "new idea (Strategy page) rather than tuning until it passes.")
    st.page_link(nxt[3], label=f"Go to {nxt[1][4:]}", icon=":material/arrow_forward:")

cols = st.columns(2)
for i, (done, title, status, page) in enumerate(steps):
    with cols[i % 2].container(border=True, height="stretch"):
        icon = ":material/check_circle:" if done else ":material/radio_button_unchecked:"
        st.markdown(f"{icon} **{title}**")
        st.caption(status)
        st.page_link(page, label="Open", icon=":material/open_in_new:")

with st.expander("The one rule: don't tune on the hold-out", icon=":material/lock:"):
    st.markdown(
        "The last part of the data (the **hold-out**) stands in for the future. "
        "The *Dev backtest* page never touches it. The *Final review* page is the "
        "only place it is judged, and every review is written to a ledger. If you "
        "change parameters after seeing the review and run it again, you are fitting "
        "the strategy to that slice, and an 'eligible' result stops meaning anything. "
        "Bumping the version number does not reset this, because the ledger counts "
        "uses per strategy name."
    )
