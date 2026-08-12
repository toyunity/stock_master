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

def test_corrupt_file_reads_as_missing(tmp_path):
    """손상 파일이 예외를 내면 그 종목 차트가 영구 실종된다 — PriceAdapter가
    fetch보다 먼저 캐시를 읽고, 호출부(candles)가 예외를 삼켜 빈 candles를
    1시간 캐시하므로 화면엔 에러도 없이 차트만 없다. None을 주면 곧바로 재수집된다."""
    cache = OHLCVCache(tmp_path)
    (Path(tmp_path) / "005930.parquet").write_bytes(b"not a parquet file")
    assert cache.get("005930") is None

def test_failed_write_keeps_the_previous_file(tmp_path, monkeypatch):
    """쓰다가 죽어도 멀쩡한 캐시를 반쪽 파일로 덮지 않는다(tmp+os.replace) —
    저장소의 다른 쓰기 5곳이 이미 쓰는 관용구다."""
    import pytest
    cache = OHLCVCache(tmp_path)
    cache.put("005930", _frame())

    def half_written(self, path, *a, **kw):
        Path(path).write_bytes(b"half")      # 절단된 채 실패
        raise IOError("디스크 꽉 참")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", half_written)
    with pytest.raises(IOError):
        cache.put("005930", _frame())
    assert cache.get("005930") is not None
