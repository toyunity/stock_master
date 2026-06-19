import pandas as pd
import backend.ingest.fdr_source as src

def test_fetch_ohlcv_normalizes_columns(monkeypatch):
    raw = pd.DataFrame(
        {"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5],
         "Volume": [100], "Change": [0.01]},
        index=pd.to_datetime(["2024-01-02"]))
    monkeypatch.setattr(src.fdr, "DataReader", lambda code, start, end: raw)

    out = src.fetch_ohlcv("005930", "2024-01-01", "2024-01-03")
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert isinstance(out.index, pd.DatetimeIndex)
