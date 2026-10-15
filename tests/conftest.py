"""Shared test fixtures."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from fxlab.data.interface import PriceData


@pytest.fixture
def pip():
    return 0.0001


def make_price_data(closes, highs=None, lows=None, opens=None, source="TEST",
                    start="2022-01-03 00:00", freq="1h", symbol="EURUSD"):
    """Build a PriceData from a list of closes (weekday hours)."""
    n = len(closes)
    idx = pd.date_range(start=pd.Timestamp(start, tz="UTC"), periods=n, freq=freq)
    closes = np.asarray(closes, dtype=float)
    opens = np.asarray(opens, dtype=float) if opens is not None else np.r_[closes[0], closes[:-1]]
    highs = np.asarray(highs, dtype=float) if highs is not None else np.maximum(opens, closes) + 0.0005
    lows = np.asarray(lows, dtype=float) if lows is not None else np.minimum(opens, closes) - 0.0005
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "bid": closes - 0.00005, "ask": closes + 0.00005, "source": source},
        index=idx,
    )
    df.index.name = "timestamp"
    return PriceData(symbol, "H1", source, df, "UTC", True)


@pytest.fixture
def sample_data_factory():
    return make_price_data


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect every file the workflow WRITES (configs, reports, journal, audit log,
    uploads, kill switch) into a temp folder, so tests never touch your real files.
    Works because writers read these as `config.X` at call time."""
    import shutil
    from fxlab import config
    cfg_dir = tmp_path / "config"
    shutil.copytree(config.CONFIG_DIR, cfg_dir, ignore=shutil.ignore_patterns("strategy_history"))
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "AUDIT_DB", tmp_path / "audit.sqlite")
    monkeypatch.setattr(config, "USER_DATA_DIR", tmp_path / "user")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)   # kill-switch file location
    return tmp_path
