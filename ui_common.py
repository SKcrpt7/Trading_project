"""Shared dashboard helpers: session state, sidebar, cached loaders, charts.

Business logic does NOT live here - it lives in fxlab/workflow.py (shared with the
CLI). This module only turns workflow results into Streamlit UI.
"""
from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from fxlab import config, strategy_store, workflow

# Chart colors (dataviz reference palette): one series = blue; polarity (gain vs
# loss) = the blue <-> red diverging pair; two compared series = blue, orange.
BLUE, RED, ORANGE, MUTED = "#2a78d6", "#e34948", "#eb6834", "#898781"
SAMPLE_LABEL = "Bundled sample (MOCK)"


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def init_state() -> None:
    # Pages can't change a sidebar widget's value after it has been drawn, so they
    # queue the change with select_after_rerun() and it is applied here, before the
    # sidebar is drawn on the next run.
    for key in ("strategy_file", "dataset"):
        pending = st.session_state.pop(f"_pending_{key}", None)
        if pending is not None:
            st.session_state[key] = pending
    files = strategy_store.list_strategy_files()
    if st.session_state.get("strategy_file") not in files:
        st.session_state.strategy_file = (workflow.DEFAULT_STRATEGY
                                          if workflow.DEFAULT_STRATEGY in files else files[0])
    st.session_state.setdefault("dataset", SAMPLE_LABEL)


def select_after_rerun(key: str, value: str, flash: str | None = None) -> None:
    """Switch the sidebar's strategy/dataset and rerun, optionally showing a message."""
    st.session_state[f"_pending_{key}"] = value
    if flash:
        st.session_state["_flash"] = flash
    st.rerun()


def show_flash() -> None:
    msg = st.session_state.pop("_flash", None)
    if msg:
        st.success(msg, icon=":material/check_circle:")


def dataset_options() -> dict[str, Path]:
    opts = {SAMPLE_LABEL: Path(config.SAMPLE_PRICES)}
    user_dir = Path(config.USER_DATA_DIR)
    if user_dir.exists():
        for p in sorted(user_dir.glob("*.csv")):
            opts[f"Uploaded: {p.name}"] = p
    return opts


def data_path() -> Path:
    opts = dataset_options()
    return opts.get(st.session_state.get("dataset"), opts[SAMPLE_LABEL])


def cfg() -> dict:
    """Configs are re-read on every rerun (cheap) so file edits show up at once."""
    return workflow.load_configs(st.session_state.strategy_file)


@st.cache_data(max_entries=8, show_spinner="Loading price data...")
def _load_data_cached(path: str, symbol: str, timeframe: str, mtime: float):
    from fxlab.data.interface import CsvPriceProvider
    return CsvPriceProvider(path).load(symbol, timeframe)


def data(c: dict | None = None):
    c = c or cfg()
    p = data_path()
    s = c["strategy"]
    # the modification time is part of the cache key, so a regenerated or
    # re-uploaded file is never served stale
    return _load_data_cached(str(p), s["symbol"], s["timeframe"], p.stat().st_mtime)


def strategy_label(filename: str) -> str:
    try:
        s = strategy_store.load(filename)
        return f"{s['name']}  ·  v{s.get('version', '?')}"
    except Exception:
        return filename


# --------------------------------------------------------------------------- #
# Sidebar (rendered by streamlit_app.py on every page)
# --------------------------------------------------------------------------- #
def render_sidebar() -> None:
    with st.sidebar:
        st.selectbox("Strategy", strategy_store.list_strategy_files(), key="strategy_file",
                     format_func=strategy_label)
        st.selectbox("Dataset", list(dataset_options()), key="dataset")
        c = cfg()
        with st.container(horizontal=True):
            st.badge("Live trading: disabled", icon=":material/block:", color="gray")
            if workflow.kill_switch_active(c):
                st.badge("Kill switch ON", icon=":material/power_settings_new:", color="red")
            else:
                st.badge("Kill switch off", icon=":material/power_settings_new:", color="green")
        if data_path() == Path(config.SAMPLE_PRICES):
            st.caption(":material/warning: Sample data is synthetic. Results show the "
                       "machinery works, not that a strategy has an edge.")


# --------------------------------------------------------------------------- #
# Small UI pieces
# --------------------------------------------------------------------------- #
def metric_row(m) -> None:
    """Headline metrics for a Metrics object, as equal-height bordered tiles."""
    pf = "inf" if m.profit_factor == float("inf") else f"{m.profit_factor:.3f}"
    tiles = [
        ("Trades", f"{m.trade_count}", "Fewer than ~50 trades is mostly noise."),
        ("Net return", f"{m.net_return_pct:+.2f}%", "After spread, slippage, commission and swap."),
        ("Profit factor", pf, "Gross wins / gross losses. Below 1.0 loses money."),
        ("Max drawdown", f"{m.max_drawdown_pct:.2f}%", "Worst peak-to-trough on this sample. The future can be worse."),
        ("Win rate", f"{m.win_rate_pct:.1f}%", "A low win rate is fine if winners are bigger than losers."),
        ("Costs paid", f"${m.total_costs:,.2f}", "Total trading costs. Compare with gross profit."),
    ]
    cols = st.columns(len(tiles))
    for col, (label, value, help_) in zip(cols, tiles):
        col.metric(label, value, help=help_, border=True, height="stretch")


def trades_frame(trades) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame([t.__dict__ for t in trades])
    df["side"] = df["side"].map(lambda s: getattr(s, "value", s))  # enum -> "LONG"/"SHORT"
    keep = ["entry_time", "exit_time", "side", "entry_price", "exit_price", "quantity",
            "net_pnl", "costs", "bars_held", "exit_reason"]
    return df[[c for c in keep if c in df.columns]]


def breakdown_frame(d: dict, key_name: str) -> pd.DataFrame:
    return pd.DataFrame([{key_name: k, "trades": v["trades"], "net_pnl": v["net_pnl"]}
                         for k, v in d.items()])


# --------------------------------------------------------------------------- #
# Charts (Altair). Every chart gets a tooltip and an alt text, and is shown next
# to a table holding the same numbers.
# --------------------------------------------------------------------------- #
def equity_chart(curve: pd.Series, starting_equity: float, alt_text: str):
    df = curve.rename("equity").rename_axis("time").reset_index()
    if df.empty:
        st.info("No closed trades yet, so there is no equity curve.")
        return
    base = alt.Chart(df).encode(
        x=alt.X("time:T", title=None),
        y=alt.Y("equity:Q", title="Equity ($)", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("time:T", title="Time"),
                 alt.Tooltip("equity:Q", title="Equity", format="$,.2f")],
    )
    line = base.mark_line(color=BLUE, strokeWidth=2, interpolate="step-after")
    start = alt.Chart(pd.DataFrame({"y": [starting_equity]})).mark_rule(
        color=MUTED, strokeWidth=1).encode(y="y:Q")
    st.altair_chart(line + start + base.mark_point(opacity=0, size=80), alt=alt_text)


def compare_equity_chart(curves: dict[str, pd.Series], alt_text: str):
    frames = []
    for name, curve in curves.items():
        d = curve.rename("equity").rename_axis("time").reset_index()
        d["series"] = name
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    names = list(curves)
    chart = alt.Chart(df).mark_line(strokeWidth=2, interpolate="step-after").encode(
        x=alt.X("time:T", title=None),
        y=alt.Y("equity:Q", title="Equity ($)", scale=alt.Scale(zero=False)),
        color=alt.Color("series:N", title=None,
                        scale=alt.Scale(domain=names, range=[BLUE, ORANGE][:len(names)]),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("series:N", title="Series"), alt.Tooltip("time:T", title="Time"),
                 alt.Tooltip("equity:Q", title="Equity", format="$,.2f")],
    )
    st.altair_chart(chart, alt=alt_text)


def signed_bar_chart(df: pd.DataFrame, x: str, y: str, x_title: str, y_title: str,
                     alt_text: str, x_type: str = "O"):
    """Bars colored by sign: gains blue, losses red (diverging pair)."""
    if df.empty:
        st.info("Nothing to chart yet.")
        return
    d = df.copy()
    d["result"] = d[y].map(lambda v: "Gain" if v > 0 else ("Loss" if v < 0 else "Flat"))
    chart = alt.Chart(d).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X(f"{x}:{x_type}", title=x_title),
        y=alt.Y(f"{y}:Q", title=y_title),
        color=alt.Color("result:N", title=None,
                        scale=alt.Scale(domain=["Gain", "Loss", "Flat"], range=[BLUE, RED, MUTED]),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip(f"{x}:{x_type}", title=x_title),
                 alt.Tooltip(f"{y}:Q", title=y_title, format=",.2f")],
    )
    st.altair_chart(chart, alt=alt_text)


def price_chart(daily: pd.DataFrame, holdout_start: pd.Timestamp, alt_text: str):
    """Daily close with the hold-out region shaded, so you can see what is fenced off."""
    shade = alt.Chart(pd.DataFrame({"start": [holdout_start], "end": [daily["time"].max()],
                                    "label": ["Hold-out (judged once, at review)"]})).mark_rect(
        color=MUTED, opacity=0.12).encode(x="start:T", x2="end:T", tooltip=["label:N"])
    line = alt.Chart(daily).mark_line(color=BLUE, strokeWidth=1.5).encode(
        x=alt.X("time:T", title=None),
        y=alt.Y("close:Q", title="Close", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("time:T", title="Date"), alt.Tooltip("close:Q", title="Close", format=".5f")],
    )
    st.altair_chart(shade + line, alt=alt_text)


def decision_banner(decision: str, reasons: list[str]) -> None:
    body = "\n".join(f"- {r}" for r in reasons)
    if decision == "ELIGIBLE_FOR_PAPER":
        st.success(body, icon=":material/check_circle:", title="Eligible for paper trading")
    elif decision == "NEEDS_INVESTIGATION":
        st.warning(body, icon=":material/help:", title="Needs investigation")
    else:
        st.error(body, icon=":material/cancel:", title="Rejected")
