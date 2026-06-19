from __future__ import annotations

import pandas as pd
import FinanceDataReader as fdr

OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]

def fetch_ohlcv(code: str, start: str, end: str):
    """FinanceDataReader로 일봉을 받아 표준 컬럼만 반환한다."""
    df = fdr.DataReader(code, start, end)
    df = df[[c for c in OHLCV_COLS if c in df.columns]].copy()
    df.index = pd.to_datetime(df.index)
    return df
