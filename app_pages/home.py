"""Home: where am I in the workflow, and what should I do next?"""
import streamlit as st

import ui_common
from fxlab import journal
from ui_common import APP_NAME, STEP_BY_KEY

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
n_notes = len(journal.notes(name))
data_ok = q.n_bad_ohlc == 0 and q.n_duplicate_timestamps == 0 and q.completeness_pct >= 95

# key -> (done?, short status)
status = {
    "data": (data_ok, f"{q.n_bars:,} bars · {q.completeness_pct}% complete"
             + ("" if data_ok else " · fix first")),
    "strategy": (True, f"Version {version}"),
    "dev": (bool(dev_runs), f"{len(dev_runs)} run(s) of v{version}" if dev_runs else "Not run yet"),
    "review": (decision is not None, decision["decision"].replace("_", " ").title() if decision
               else ("Hold-out untouched" if not uses else f"Hold-out used {uses}x before")),
    "paper": (bool(paper_runs), f"{len(paper_runs)} run(s)" if paper_runs else "Not run yet"),
    "monitor": (True, "Kill switch, audit log, news"),
    "log": (n_notes > 0, f"{n_notes} note(s)" if n_notes else "No notes yet"),
}

# Suggested next step, guided by the review decision.
if not data_ok:
    nxt = "data"
elif not dev_runs:
    nxt = "dev"
elif decision is None:
    nxt = "review"
elif decision["decision"] == "ELIGIBLE_FOR_PAPER" and not paper_runs:
    nxt = "paper"
elif decision["decision"] != "ELIGIBLE_FOR_PAPER":
    nxt = "log"
else:
    nxt = "monitor"
nstep = STEP_BY_KEY[nxt]

# ---- hero ------------------------------------------------------------------ #
with st.container(border=True):
    st.title(APP_NAME, icon=":material/candlestick_chart:")
    st.caption("Research, test and paper-trade forex strategies honestly.")
    with st.container(horizontal=True):
        st.badge(f"{name} · v{version}", icon=":material/tune:", color="blue")
        st.badge(f"{s['symbol']} {s['timeframe']}", icon=":material/currency_exchange:", color="gray")
        ui_common.decision_badge(decision["decision"] if decision else None)
    done = sum(1 for d, _ in status.values() if d)
    st.progress(done / len(status), text=f"{done} of {len(status)} steps done")

    why = {
        "data": "The data has problems. Fix them before testing anything.",
        "dev": "Tune this version on the development data.",
        "review": "Happy with the dev results? Judge it once on the hold-out.",
        "paper": "It passed review. Rehearse it with simulated fills.",
        "log": "It didn't pass. Note what you learned, then try a new idea.",
        "monitor": "Keep an eye on the safety switch and audit log.",
    }[nxt]
    st.markdown(f"**Next:** {why}")
    if st.button(f"Go to {nstep.num} · {nstep.title}", icon=":material/arrow_forward:",
                 icon_position="right", type="primary", width="stretch", key="do_next"):
        st.switch_page(nstep.page)

# ---- quick actions ---------------------------------------------------------- #
with st.container(horizontal=True):
    if st.button("Run dev backtest", icon=":material/play_arrow:", key="quick_dev"):
        st.session_state["autorun_dev"] = True
        st.switch_page(STEP_BY_KEY["dev"].page)
    if st.button("Edit strategy", icon=":material/tune:", key="quick_strategy"):
        st.switch_page(STEP_BY_KEY["strategy"].page)
    if st.button("Add a note", icon=":material/edit_note:", key="quick_note"):
        st.switch_page(STEP_BY_KEY["log"].page)

# ---- all steps -------------------------------------------------------------- #
st.subheader("Your workflow", icon=":material/route:")
# Two cards per ROW (not two long columns), so a phone shows them in order 1..7.
steps_list = ui_common.STEPS
for row_start in range(0, len(steps_list), 2):
    cols = st.columns(2)
    for col, step in zip(cols, steps_list[row_start:row_start + 2]):
        ok, text = status[step.key]
        with col.container(border=True, height="stretch"):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"{':material/check_circle:' if ok else ':material/radio_button_unchecked:'} "
                            f"**{step.num} · {step.title}**")
                st.page_link(step.page, label="Open", icon=":material/open_in_new:")
            st.caption(text)

with st.popover("The one rule: don't tune on the hold-out", icon=":material/lock:"):
    st.markdown(STEP_BY_KEY["review"].explain)
