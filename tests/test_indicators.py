import numpy as np
import pandas as pd
from backend.analysis.indicators import add_indicators

def _trending_frame(n=120):
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(np.linspace(100, 200, n), index=idx)  # 우상향
    return pd.DataFrame({"Open": close, "High": close * 1.01,
                         "Low": close * 0.99, "Close": close,
                         "Volume": np.full(n, 1000)}, index=idx)

def test_adds_expected_columns():
    out = add_indicators(_trending_frame())
    for col in ["ma20", "ma60", "ma120", "rsi14", "macd", "macd_signal"]:
        assert col in out.columns


def test_ma120_is_120day_average():
    out = add_indicators(_trending_frame(120))          # 정확히 120봉
    last = out["ma120"].iloc[-1]
    assert not np.isnan(last)                            # 120봉 → 마지막 값 산출
    assert abs(last - out["Close"].mean()) < 1e-6        # 120봉 SMA = 전체 평균

def test_uptrend_has_high_rsi():
    out = add_indicators(_trending_frame())
    assert out["rsi14"].iloc[-1] > 60  # 꾸준한 상승 → 높은 RSI
