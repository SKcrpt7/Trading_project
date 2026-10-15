"""Strategy files are the record of what produced every result, so saving them must
(a) keep the explanatory comments, (b) force a new version for any change, and
(c) archive the old version. Bad parameters must never reach disk."""
import pytest
import yaml

from fxlab import strategy_store as store

FILE = "strategy_eurusd_trend.yaml"


def _comment_lines(text):
    return [l for l in text.splitlines() if l.lstrip().startswith("#")]


def test_update_keeps_comments_and_changes_only_the_value(sandbox):
    before = store.read_text(FILE)
    after = store.update_yaml_text(before, {("entry", "fast_ema"): 30, ("exit", "reward_risk"): 2.0})
    assert _comment_lines(after) == _comment_lines(before)          # every comment line kept
    assert "stop_atr_mult: 2.0           # protective stop" in after  # untouched line identical
    parsed = yaml.safe_load(after)
    assert parsed["entry"]["fast_ema"] == 30 and parsed["exit"]["reward_risk"] == 2.0
    # an inline comment on an edited line survives too
    assert any(l.strip().startswith("reward_risk: 2.0") and "#" in l for l in after.splitlines())


def test_update_refuses_block_values_and_unknown_keys(sandbox):
    text = store.read_text(FILE)
    with pytest.raises(KeyError):
        store.update_yaml_text(text, {("description",): "x"})        # folded block scalar
    with pytest.raises(KeyError):
        store.update_yaml_text(text, {("entry", "no_such_param"): 1})


def test_new_version_is_required_and_old_file_is_archived(sandbox):
    old_text = store.read_text(FILE)
    with pytest.raises(ValueError, match="new version"):
        store.save_new_version(FILE, {("entry", "fast_ema"): 25}, "0.1.0")

    store.save_new_version(FILE, {("entry", "fast_ema"): 25}, "0.2.0")
    cfg = store.load(FILE)
    assert cfg["version"] == "0.2.0" and cfg["entry"]["fast_ema"] == 25
    hist = store.history("eurusd_trend_ema")
    assert [p.name for p in hist] == ["eurusd_trend_ema_v0.1.0.yaml"]
    assert hist[0].read_text(encoding="utf-8") == old_text            # exact old file preserved


def test_invalid_parameters_never_reach_disk(sandbox):
    before = store.read_text(FILE)
    with pytest.raises(ValueError, match="Fast EMA must be smaller"):
        store.save_new_version(FILE, {("entry", "fast_ema"): 60}, "0.2.0")   # slow is 50
    assert store.read_text(FILE) == before
    assert store.history("eurusd_trend_ema") == []


def test_fork_creates_a_new_strategy_at_v010(sandbox):
    path = store.save_as_new_strategy(FILE, {("exit", "time_stop_bars"): 24}, "My Slow Trend")
    assert path.name == "strategy_my_slow_trend.yaml"
    cfg = store.load(path.name)
    assert (cfg["name"], cfg["version"], cfg["exit"]["time_stop_bars"]) == ("my_slow_trend", "0.1.0", 24)
    assert path.name in store.list_strategy_files()
    with pytest.raises(ValueError, match="already exists"):
        store.save_as_new_strategy(FILE, {}, "my slow trend")


def test_validation_catches_bad_settings():
    cfg = yaml.safe_load(open(store.config_dir() / FILE, encoding="utf-8"))
    assert store.validate(cfg) == []
    cfg["sizing"]["risk_per_trade_pct"] = 2.0
    cfg["session"]["start_utc"], cfg["session"]["end_utc"] = "20:00", "07:00"
    cfg["entry"]["allow_long"] = cfg["entry"]["allow_short"] = False
    errs = store.validate(cfg, {"limits": {"max_risk_per_trade_pct": 1.0}})
    assert any("never trades" in e for e in errs)
    assert any("Session start" in e for e in errs)
    assert any("account limit" in e for e in errs)


def test_bump_version():
    assert store.bump_version("0.1.0") == "0.2.0"
    assert store.bump_version("1.9.3") == "1.10.0"
    assert store.bump_version("beta") == "beta.1"
