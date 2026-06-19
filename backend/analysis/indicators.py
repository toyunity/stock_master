from __future__ import annotations

import pandas as pd
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV DataFrame에 지표 컬럼을 추가해 반환한다(원본 비파괴)."""
    out = df.copy()
    close = out["Close"]
    out["ma20"] = SMAIndicator(close=close, window=20).sma_indicator()
    out["ma60"] = SMAIndicator(close=close, window=60).sma_indicator()
    out["rsi14"] = RSIIndicator(close=close, window=14).rsi()
    macd = MACD(close=close)
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    return out
