"""The shared workflow layer (used by both the CLI and the dashboard).

The two properties that matter most: dev backtests can never see the hold-out,
and every use of the hold-out is recorded."""
import pytest

from fxlab import journal, workflow


@pytest.fixture
def cfg(sandbox):
    return workflow.load_configs()


@pytest.fixture
def data(cfg):
    return workflow.load_data(cfg)


@pytest.fixture
def small_data(cfg):
    # a shorter history keeps the review (walk-forward + sensitivity) quick
    return workflow.load_data(cfg, start="2022-01-01")


def test_dev_backtest_never_touches_the_holdout(cfg, data):
    run = workflow.run_dev_backtest(cfg, data)
    assert run.dev_end < run.holdout_start
    assert run.result.trades, "expected trades on the dev slice"
    assert all(t.exit_time <= run.dev_end for t in run.result.trades)
    # and the run is logged with its parameters
    logged = journal.runs("dev", cfg["strategy"]["name"])
    assert len(logged) == 1 and logged[0]["params"]["entry"]["fast_ema"] == 20


def test_every_review_is_ledgered_and_reuse_is_counted(cfg, small_data, sandbox):
    first = workflow.run_review(cfg, small_data)
    assert first.prior_holdout_uses == 0
    assert first.md_path.exists() and first.md_path.parent == sandbox / "reports"

    second = workflow.run_review(cfg, small_data)
    assert second.prior_holdout_uses == 1
    name, fp = cfg["strategy"]["name"], journal.data_fingerprint(small_data)
    assert journal.holdout_uses(name, fp) == 2
    assert journal.latest_decision(name)["decision"] == second.review.decision.value
    # a different dataset is a different hold-out
    assert journal.holdout_uses(name, "other:dataset") == 0


def test_paper_run_is_recorded_and_matches_backtest(cfg, data):
    out = workflow.run_paper(cfg, data)
    assert out.on_holdout
    assert out.paper_metrics.trade_count == out.backtest_metrics.trade_count
    rec = journal.runs("paper", cfg["strategy"]["name"])
    assert len(rec) == 1 and rec[0]["slice"] == "holdout"


def test_kill_switch_toggle_is_audited(cfg, sandbox):
    from fxlab import config
    from fxlab.audit.store import AuditStore
    workflow.set_kill_switch(cfg, True, who="test")
    assert workflow.kill_switch_active(cfg) and (sandbox / "KILL_SWITCH").exists()
    workflow.set_kill_switch(cfg, False, who="test")
    assert not workflow.kill_switch_active(cfg)
    audit = AuditStore(config.AUDIT_DB)
    assert [r["message"] for r in audit.recent(5, "kill")] == [
        "Kill switch deactivated (test)", "Kill switch ACTIVATED (test)"]
    audit.close()


def test_notes_round_trip_and_validation(sandbox):
    journal.add_note(strategy="s", version="0.1.0", kind="idea", text="  try a breakout  ")
    assert [n["text"] for n in journal.notes("s")] == ["try a breakout"]
    with pytest.raises(ValueError):
        journal.add_note(strategy="s", version="0.1.0", kind="idea", text="   ")
    with pytest.raises(ValueError):
        journal.add_note(strategy="s", version="0.1.0", kind="nonsense", text="x")


def test_torn_last_line_does_not_hide_earlier_records(sandbox):
    journal.add_note(strategy="s", version="1", kind="idea", text="kept")
    with open(sandbox / "reports" / journal.NOTES_FILE, "a", encoding="utf-8") as f:
        f.write('{"broken": ')   # simulate a crash mid-write
    assert [n["text"] for n in journal.notes()] == ["kept"]
