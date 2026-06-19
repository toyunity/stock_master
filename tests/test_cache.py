import pandas as pd
from pathlib import Path
from backend.adapters.cache import OHLCVCache

def _frame():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3],
         "Close": [1.0, 2.0, 3.0], "Volume": [10, 20, 30]}, index=idx)

def test_put_then_get_roundtrip(tmp_path):
    cache = OHLCVCache(tmp_path)
    df = _frame()
    cache.put("005930", df)
    got = cache.get("005930")
    assert got is not None
    pd.testing.assert_frame_equal(got, df, check_freq=False)

def test_get_missing_returns_none(tmp_path):
    cache = OHLCVCache(tmp_path)
    assert cache.get("000000") is None
