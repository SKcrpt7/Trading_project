"""Shared dashboard helpers: steps, state, sidebar, cached loaders, UI pieces, charts.

Business logic does NOT live here - it lives in fxlab/workflow.py (shared with the
CLI). This module only turns workflow results into Streamlit UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from fxlab import config, strategy_store, workflow

APP_NAME = "PipLab"
ASSETS = Path(__file__).resolve().parent / "assets"

# Chart colors, matched to the dark theme in .streamlit/config.toml.
# One series = blue; gain vs loss = green vs red (always with a legend/label,
# never color alone); two compared series = blue vs orange.
BLUE, GREEN, RED, ORANGE, MUTED = "#60A5FA", "#34D399", "#F87171", "#FB923C", "#94A3B8"
CHART_HEIGHT = 260
SAMPLE_LABEL = "Bundled sample (MOCK)"


# --------------------------------------------------------------------------- #
# The workflow steps - one source of truth for navigation, Home and "Next" buttons
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Step:
    key: str
    num: int
    title: str
    page: str
    icon: str
    purpose: str        # one line shown at the top of the page
    explain: str        # the longer "what does this mean?" text


STEPS: list[Step] = [
    Step("data", 1, "Data", "app_pages/data.py", ":material/database:",
         "Check the data is trustworthy before you test anything.",
         "Bad data gives confident wrong answers. Look for gaps, broken bars and whether "
         "real bid/ask prices exist. The shaded part of the chart is the **hold-out**: the "
         "last 30% of history, kept locked as a stand-in for the future."),
    Step("strategy", 2, "Strategy", "app_pages/strategy.py", ":material/tune:",
         "Set the rules. Every change is saved as a new version.",
         "Saving archives the previous file in `config/strategy_history/`, so every result "
         "can be traced back to the exact settings behind it. These fields drive the built-in "
         "trend-following (EMA crossover) logic; a different kind of strategy needs new code."),
    Step("dev", 3, "Dev backtest", "app_pages/dev_backtest.py", ":material/science:",
         "Tune on the first 70% of history. The hold-out stays locked.",
         "Run as often as you like - this never touches the hold-out, so comparing versions "
         "here is safe. Fewer than ~50 trades is mostly luck. If one year or one session "
         "makes all the money, that's usually luck too."),
    Step("review", 4, "Final review", "app_pages/review.py", ":material/gavel:",
         "Judge the strategy once, on data it has never seen.",
         "The review tests the hold-out, walk-forward windows, nearby parameter values and "
         "doubled costs, then decides REJECT, NEEDS INVESTIGATION or ELIGIBLE FOR PAPER. "
         "Every run is logged. Re-running after tweaking fits the strategy to the hold-out "
         "and makes a pass meaningless - even under a new version number."),
    Step("paper", 5, "Paper trading", "app_pages/paper.py", ":material/description:",
         "Rehearse live trading with simulated fills and every safety check.",
         "Bars are replayed through the strategy, the risk manager (daily loss limit, "
         "spread limit, stale data, duplicate orders, kill switch) and a simulated broker. "
         "Results should match the backtest unless a safety check fired. Nothing reaches a "
         "real broker - live trading is disabled in code."),
    Step("monitor", 6, "Monitor", "app_pages/monitor.py", ":material/monitor_heart:",
         "Safety switch, audit trail and upcoming news.",
         "The kill switch is a file checked before every entry. The audit log records every "
         "signal, order, fill and error, with paper runs stamped at the simulated bar time."),
    Step("log", 7, "Research log", "app_pages/research_log.py", ":material/edit_note:",
         "Write down what you tried and why, so you never repeat a dead end.",
         "Reviews and runs are recorded automatically. Add a note per idea: what you "
         "changed, what happened, and whether you kept or dropped it."),
]
STEP_BY_KEY = {s.key: s for s in STEPS}


def intro(key: str) -> None:
    """One-line purpose + a small 'what does this mean?' popover (keeps pages short)."""
    s = STEP_BY_KEY[key]
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(s.purpose)
        with st.popover("What does this mean?", icon=":material/help:", type="tertiary"):
            st.markdown(s.explain)


def next_step(key: str) -> None:
    """A 'Next step' button at the bottom of each page."""
    i = [s.key for s in STEPS].index(key)
    if i + 1 >= len(STEPS):
        return
    nxt = STEPS[i + 1]
    st.space("medium")
    if st.button(f"Next: {nxt.num} · {nxt.title}", icon=":material/arrow_forward:",
                 icon_position="right", key=f"next_{key}"):
        st.switch_page(nxt.page)


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
    """Switch the sidebar's strategy/dataset and rerun, optionally showing a toast."""
    st.session_state[f"_pending_{key}"] = value
    if flash:
        st.session_state["_flash"] = flash
    st.rerun()


def show_flash() -> None:
    msg = st.session_state.pop("_flash", None)
    if msg:
        st.toast(msg, icon=":material/check_circle:")


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
# Branding + sidebar (rendered by streamlit_app.py on every page)
# --------------------------------------------------------------------------- #
def render_brand() -> None:
    st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "icon.svg"), size="large")


def render_sidebar() -> None:
    with st.sidebar:
        st.selectbox("Strategy", strategy_store.list_strategy_files(), key="strategy_file",
                     format_func=strategy_label)
        st.selectbox("Dataset", list(dataset_options()), key="dataset")
        c = cfg()
        with st.container(horizontal=True):
            st.badge("Live trading off", icon=":material/block:", color="gray")
            if workflow.kill_switch_active(c):
                st.badge("Kill switch ON", icon=":material/power_settings_new:", color="red")
            else:
                st.badge("Kill switch off", icon=":material/power_settings_new:", color="green")
            if data_path() == Path(config.SAMPLE_PRICES):
                st.badge("Mock data", icon=":material/science:", color="orange",
                         help="Synthetic sample data: shows the machinery works, not that a "
                              "strategy has an edge.")


# --------------------------------------------------------------------------- #
# Small UI pieces
# --------------------------------------------------------------------------- #
DECISION_STYLE = {
    "ELIGIBLE_FOR_PAPER": ("Eligible for paper", "green", ":material/check_circle:"),
    "NEEDS_INVESTIGATION": ("Needs investigation", "orange", ":material/help:"),
    "REJECT": ("Rejected", "red", ":material/cancel:"),
}


def decision_badge(decision: str | None) -> None:
    if decision is None:
        st.badge("Not reviewed", icon=":material/pending:", color="gray")
        return
    label, color, icon = DECISION_STYLE.get(decision, (decision, "gray", ":material/info:"))
    st.badge(label, icon=icon, color=color)


def metric_row(m) -> None:
    """Headline metrics as fixed-width tiles in a wrapping row: two per row on a
    phone, all six on a desktop. The three most important numbers come first."""
    pf = "∞" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"
    tiles = [
        ("Net return", f"{m.net_return_pct:+.2f}%", "After spread, slippage, commission and swap."),
        ("Profit factor", pf, "Gross wins ÷ gross losses. Below 1.0 loses money."),
        ("Trades", f"{m.trade_count}", "Fewer than ~50 trades is mostly noise."),
        ("Max drawdown", f"{m.max_drawdown_pct:.2f}%", "Worst peak-to-trough on this sample. The future can be worse."),
        ("Win rate", f"{m.win_rate_pct:.0f}%", "A low win rate is fine if winners are bigger than losers."),
        ("Costs paid", f"${m.total_costs:,.0f}", "Total trading costs. Compare with gross profit."),
    ]
    with st.container(horizontal=True, gap="small"):
        for label, value, help_ in tiles:
            st.metric(label, value, help=help_, border=True, width=150)


def trades_frame(trades) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame([t.__dict__ for t in trades])
    df["side"] = df["side"].map(lambda s: getattr(s, "value", s))  # enum -> "LONG"/"SHORT"
    keep = ["entry_time", "side", "net_pnl", "exit_reason", "exit_time", "entry_price",
            "exit_price", "quantity", "costs", "bars_held"]   # phone-first column order
    return df[[c for c in keep if c in df.columns]]


TRADE_COLUMNS = {
    "entry_time": st.column_config.DatetimeColumn("Entry", format="YYYY-MM-DD HH:mm"),
    "exit_time": st.column_config.DatetimeColumn("Exit", format="YYYY-MM-DD HH:mm"),
    "side": "Side",
    "net_pnl": st.column_config.NumberColumn("Net P&L", format="$%.2f"),
    "costs": st.column_config.NumberColumn("Costs", format="$%.2f"),
    "exit_reason": "Exit reason",
    "entry_price": st.column_config.NumberColumn("Entry px", format="%.5f"),
    "exit_price": st.column_config.NumberColumn("Exit px", format="%.5f"),
    "quantity": st.column_config.NumberColumn("Units", format="%d"),
    "bars_held": "Bars",
}


def breakdown_frame(d: dict, key_name: str) -> pd.DataFrame:
    return pd.DataFrame([{key_name: k, "trades": v["trades"], "net_pnl": v["net_pnl"]}
                         for k, v in d.items()])


# --------------------------------------------------------------------------- #
# Charts (Altair). Each gets a tooltip, an alt text and a compact fixed height,
# and is shown next to a table holding the same numbers.
# --------------------------------------------------------------------------- #
def _show(chart, alt_text: str):
    st.altair_chart(chart.properties(height=CHART_HEIGHT), alt=alt_text)


def equity_chart(curve: pd.Series, starting_equity: float, alt_text: str):
    df = curve.rename("equity").rename_axis("time").reset_index()
    if df.empty:
        st.caption("No closed trades yet, so there is no equity curve.")
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
    _show(line + start + base.mark_point(opacity=0, size=80), alt_text)


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
    _show(chart, alt_text)


def signed_bar_chart(df: pd.DataFrame, x: str, y: str, x_title: str, y_title: str,
                     alt_text: str, x_type: str = "O"):
    """Bars colored by sign: gains green, losses red (legend always shown)."""
    if df.empty:
        st.caption("Nothing to chart yet.")
        return
    d = df.copy()
    d["result"] = d[y].map(lambda v: "Gain" if v > 0 else ("Loss" if v < 0 else "Flat"))
    chart = alt.Chart(d).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X(f"{x}:{x_type}", title=x_title),
        y=alt.Y(f"{y}:Q", title=y_title),
        color=alt.Color("result:N", title=None,
                        scale=alt.Scale(domain=["Gain", "Loss", "Flat"], range=[GREEN, RED, MUTED]),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip(f"{x}:{x_type}", title=x_title),
                 alt.Tooltip(f"{y}:Q", title=y_title, format=",.2f")],
    )
    _show(chart, alt_text)


def price_chart(daily: pd.DataFrame, holdout_start: pd.Timestamp, alt_text: str):
    """Daily close with the hold-out region shaded, so you can see what is fenced off."""
    shade = alt.Chart(pd.DataFrame({"start": [holdout_start], "end": [daily["time"].max()],
                                    "label": ["Hold-out (judged once, at review)"]})).mark_rect(
        color=MUTED, opacity=0.15).encode(x="start:T", x2="end:T", tooltip=["label:N"])
    line = alt.Chart(daily).mark_line(color=BLUE, strokeWidth=1.5).encode(
        x=alt.X("time:T", title=None, axis=alt.Axis(format="%b %Y", labelOverlap=True)),
        y=alt.Y("close:Q", title="Close", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("time:T", title="Date"), alt.Tooltip("close:Q", title="Close", format=".5f")],
    )
    _show(shade + line, alt_text)


def decision_banner(decision: str, reasons: list[str]) -> None:
    body = "\n".join(f"- {r}" for r in reasons)
    if decision == "ELIGIBLE_FOR_PAPER":
        st.success(body, icon=":material/check_circle:", title="Eligible for paper trading")
    elif decision == "NEEDS_INVESTIGATION":
        st.warning(body, icon=":material/help:", title="Needs investigation")
    else:
        st.error(body, icon=":material/cancel:", title="Rejected")
