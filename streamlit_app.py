"""fxlab dashboard - entry point.

Run it by double-clicking run_dashboard.bat, or:
    .venv\\Scripts\\streamlit run streamlit_app.py --server.address 127.0.0.1

That serves http://127.0.0.1:8501 to this computer only. The same code also runs
online on Streamlit Community Cloud (invite-only). It drives
the same code as the CLI (fxlab/workflow.py), never places a real order, and
cannot: live trading is disabled at the broker-interface level.
"""
import streamlit as st

import ui_common

st.set_page_config(page_title="fxlab", page_icon=":material/candlestick_chart:", layout="wide")
ui_common.init_state()

page = st.navigation(
    {
        "": [
            st.Page("app_pages/home.py", title="Home", icon=":material/home:", default=True),
        ],
        "Research": [
            st.Page("app_pages/data.py", title="1 · Data", icon=":material/database:"),
            st.Page("app_pages/strategy.py", title="2 · Strategy", icon=":material/tune:"),
            st.Page("app_pages/dev_backtest.py", title="3 · Dev backtest", icon=":material/science:"),
            st.Page("app_pages/review.py", title="4 · Final review", icon=":material/gavel:"),
        ],
        "Forward test": [
            st.Page("app_pages/paper.py", title="5 · Paper trading", icon=":material/description:"),
            st.Page("app_pages/monitor.py", title="6 · Monitor", icon=":material/monitor_heart:"),
        ],
        "Notes": [
            st.Page("app_pages/research_log.py", title="7 · Research log", icon=":material/edit_note:"),
        ],
    },
    position="sidebar",
)

ui_common.render_sidebar()
st.title(page.title, icon=page.icon)
ui_common.show_flash()
page.run()
