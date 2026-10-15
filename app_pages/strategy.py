"""Step 2 - Strategy: edit parameters; every change becomes a new, traceable version."""
from datetime import time

import streamlit as st

import ui_common
from fxlab import strategy_store as store

c = ui_common.cfg()
s = c["strategy"]
fname = st.session_state.strategy_file
version = str(s.get("version", "0"))
risk_cap = float(c["risk"]["limits"]["max_risk_per_trade_pct"])

with st.container(border=True):
    st.markdown(f"**{s['name']}** · v{version} · `{s.get('kind')}` · {s['symbol']} {s['timeframe']} "
                f"· file `config/{fname}`")
    if s.get("description"):
        st.caption(s["description"].strip())

st.info("Saving a change creates a **new version**; the old file is archived to "
        "`config/strategy_history/`, so every result stays traceable to its exact parameters. "
        "Only the trend-following (EMA crossover) logic is implemented in code, so these "
        "fields are its parameters. A different kind of strategy needs a new Python class "
        "(see `fxlab/pipeline.py`).", icon=":material/info:")

SECTIONS = {"entry": "Entry", "exit": "Exit", "sizing": "Position sizing",
            "session": "Trading session", "news": "News blackout"}
key_sfx = f"{fname}:{version}"   # fresh widgets whenever the strategy or version changes


def widget(f: store.Field, current):
    k = f"f_{f.section}_{f.key}_{key_sfx}"
    if f.kind == "int":
        return int(st.number_input(f.label, min_value=int(f.min), max_value=int(f.max),
                                   value=int(current), step=1, help=f.help, key=k))
    if f.kind == "float":
        hi = min(f.max, risk_cap) if f.key == "risk_per_trade_pct" else f.max
        return round(float(st.number_input(f.label, min_value=float(f.min), max_value=float(hi),
                                           value=float(min(current, hi)), step=0.1, format="%.2f",
                                           help=f.help, key=k)), 4)
    if f.kind == "bool":
        return bool(st.toggle(f.label, value=bool(current), help=f.help, key=k))
    if f.kind == "time":
        h, m = map(int, str(current).split(":"))
        t = st.time_input(f.label, value=time(h, m), step=1800, help=f.help, key=k)
        return f"{t.hour:02d}:{t.minute:02d}"
    if f.kind == "days":
        picked = st.pills(f.label, store.DAYS, selection_mode="multi", default=list(current),
                          help=f.help, key=k) or []
        return [d for d in store.DAYS if d in picked]   # calendar order, not click order
    if f.kind == "choice":
        v = st.segmented_control(f.label, list(f.choices), default=current, help=f.help, key=k)
        return v or current
    raise ValueError(f.kind)


with st.form(f"edit_{key_sfx}", border=True):
    params = {}
    cols = st.columns(len(SECTIONS))
    for col, (sec, title) in zip(cols, SECTIONS.items()):
        with col:
            st.markdown(f"**{title}**")
            for f in [f for f in store.EDITABLE_FIELDS if f.section == sec]:
                params[(f.section, f.key)] = widget(f, store.get_value(s, f.section, f.key))

    st.divider()
    left, right = st.columns(2)
    with left:
        new_version = st.text_input("New version", value=store.bump_version(version),
                                    help="Saved into this strategy's file. The current file is archived.")
        save_version = st.form_submit_button("Save as new version", icon=":material/save:",
                                             type="primary")
    with right:
        new_name = st.text_input("New strategy name", placeholder="e.g. eurusd_trend_slow",
                                 help="Copies this strategy (comments included) into a new file at v0.1.0.")
        save_fork = st.form_submit_button("Save as new strategy", icon=":material/fork_right:")

changed = {p: v for p, v in params.items() if v != store.get_value(s, *p)}
if save_version or save_fork:
    try:
        if save_version:
            if not changed:
                raise ValueError("Nothing changed - edit a parameter first.")
            path = store.save_new_version(fname, params, new_version, c["risk"])
            msg = (f"Saved {s['name']} v{new_version} ({len(changed)} change(s)); "
                   f"v{version} archived. Run a dev backtest next.")
        else:
            path = store.save_as_new_strategy(fname, params, new_name, c["risk"])
            msg = f"Created {path.name} (v0.1.0). It is now the selected strategy."
    except (ValueError, KeyError) as exc:
        st.error(str(exc), icon=":material/error:", title="Not saved")
    else:
        ui_common.select_after_rerun("strategy_file", path.name, flash=msg)
elif changed:
    st.caption(f":material/edit: {len(changed)} unsaved change(s): "
               + ", ".join(f"{k} {store.get_value(s, sec, k)} → {v}" for (sec, k), v in changed.items()))

# ---- invalidation, history, raw file ------------------------------------- #
if s.get("invalidation"):
    with st.expander("When to stop trusting this strategy", icon=":material/rule:"):
        for line in s["invalidation"]:
            st.markdown(f"- {line}")
        st.caption("Edit these directly in the YAML file.")

hist = store.history(s["name"])
with st.expander(f"Version history ({len(hist)} archived)", icon=":material/history:"):
    if not hist:
        st.caption("No earlier versions yet. Saving a new version archives the current one here.")
    else:
        pick = st.selectbox("Archived version", hist, format_func=lambda p: p.stem,
                            index=len(hist) - 1)
        st.code(pick.read_text(encoding="utf-8"), language="yaml")

with st.expander("Current YAML file", icon=":material/code:"):
    st.code(store.read_text(fname), language="yaml")
