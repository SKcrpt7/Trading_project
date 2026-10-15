"""Data-quality checks must catch gaps and structurally broken bars."""
from fxlab.data.quality import assess_quality


def test_detects_injected_gap(sample_data_factory):
    closes = [1.10 + 0.0001 * i for i in range(100)]
    data = sample_data_factory(closes)
    # drop a chunk in the middle to create a gap
    df = data.df.drop(data.df.index[40:46])
    rep = assess_quality(df, "EURUSD", "H1", "TEST", "UTC")
    assert len(rep.missing_periods) >= 1
    assert rep.n_bars == len(df)


def test_detects_bad_ohlc(sample_data_factory):
    closes = [1.10] * 20
    data = sample_data_factory(closes)
    df = data.df.copy()
    # make one bar have high < low (impossible)
    df.iloc[5, df.columns.get_loc("high")] = 1.0
    df.iloc[5, df.columns.get_loc("low")] = 2.0
    rep = assess_quality(df, "EURUSD", "H1", "TEST", "UTC")
    assert rep.n_bad_ohlc >= 1


def test_mock_source_is_flagged(sample_data_factory):
    data = sample_data_factory([1.10] * 10, source="MOCK")
    rep = data.quality()
    assert any("MOCK" in n for n in rep.notes)
