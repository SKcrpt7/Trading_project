"""Headless dashboard tests (Streamlit AppTest - no browser, no server).

Every page must render without an exception, and the main actions must work
end to end. The `sandbox` fixture redirects all written files to a temp folder."""
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = "../streamlit_app.py"
PAGES = ["app_pages/home.py", "app_pages/data.py", "app_pages/strategy.py",
         "app_pages/dev_backtest.py", "app_pages/review.py", "app_pages/paper.py",
         "app_pages/monitor.py", "app_pages/research_log.py"]


def _app():
    return AppTest.from_file(APP, default_timeout=60).run()


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(sandbox, page):
    at = _app()
    at.switch_page(page).run()
    assert not at.exception, at.exception


def test_dev_backtest_button_shows_results(sandbox):
    at = _app()
    at.switch_page("app_pages/dev_backtest.py").run()
    at.button(key="run_dev").click().run()
    assert not at.exception, at.exception
    labels = [m.label for m in at.metric]
    assert {"Trades", "Net return", "Profit factor"} <= set(labels)
    assert len(at.dataframe) >= 1   # the run-history table now has a row


def test_strategy_save_creates_version_and_switches_to_it(sandbox):
    from fxlab import strategy_store as store
    at = _app()
    at.switch_page("app_pages/strategy.py").run()
    fname = "strategy_eurusd_trend.yaml"
    at.number_input(key=f"f_entry_fast_ema_{fname}:0.1.0").set_value(25)
    at.button[[b.label for b in at.button].index("Save as new version")].click().run()
    assert not at.exception, at.exception
    assert store.load(fname)["entry"]["fast_ema"] == 25
    assert store.load(fname)["version"] == "0.2.0"
    assert [p.name for p in store.history("eurusd_trend_ema")] == ["eurusd_trend_ema_v0.1.0.yaml"]


def test_paper_requires_demo_ack_when_not_eligible(sandbox):
    at = _app()
    at.switch_page("app_pages/paper.py").run()
    assert at.button(key="run_paper").disabled          # not reviewed -> gated
    at.checkbox[0].check().run()
    at.button(key="run_paper").click().run()
    assert not at.exception, at.exception
    assert any("Backtest vs paper" in s.value for s in at.subheader)


def test_note_can_be_added(sandbox):
    from fxlab import journal
    at = _app()
    at.switch_page("app_pages/research_log.py").run()
    at.text_area[0].set_value("EMA 20/50 loses on mock data, as expected.")
    at.button[[b.label for b in at.button].index("Add note to eurusd_trend_ema v0.1.0")].click().run()
    assert not at.exception, at.exception
    assert [n["text"] for n in journal.notes("eurusd_trend_ema")] == [
        "EMA 20/50 loses on mock data, as expected."]
