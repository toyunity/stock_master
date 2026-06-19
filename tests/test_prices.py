import pandas as pd
from backend.adapters.cache import OHLCVCache
from backend.adapters.prices import PriceAdapter

def _frame():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3],
         "Close": [1.0, 2.0, 3.0], "Volume": [10, 20, 30]}, index=idx)

def test_fetches_from_source_on_miss_then_caches(tmp_path):
    calls = []
    def fake_source(code, start, end):
        calls.append(code)
        return _frame()
    adapter = PriceAdapter(OHLCVCache(tmp_path), source=fake_source)

    df1 = adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03")
    df2 = adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03")

    assert len(df1) == 3
    assert calls == ["005930"]  # 두 번째는 캐시에서 → source 1회만 호출

def test_force_refresh_bypasses_cache(tmp_path):
    calls = []
    def fake_source(code, start, end):
        calls.append(code); return _frame()
    adapter = PriceAdapter(OHLCVCache(tmp_path), source=fake_source)
    adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03")
    adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03", force=True)
    assert calls == ["005930", "005930"]

def test_refetches_when_cache_does_not_cover_end(tmp_path):
    calls = []
    def src(code, start, end):
        calls.append(end); return _frame()  # _frame() ends 2024-01-03
    adapter = PriceAdapter(OHLCVCache(tmp_path), source=src)
    adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03")   # caches up to 2024-01-03
    adapter.get_ohlcv("005930", "2024-01-01", "2024-06-01")   # 01-03 < 06-01 -> must refetch
    assert len(calls) == 2

def test_serves_cache_when_it_covers_end(tmp_path):
    calls = []
    def src(code, start, end):
        calls.append(1); return _frame()
    adapter = PriceAdapter(OHLCVCache(tmp_path), source=src)
    adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03")
    adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03")   # covered -> no refetch
    assert len(calls) == 1
