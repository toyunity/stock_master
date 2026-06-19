import numpy as np
import pandas as pd
from backend.analysis.indicators import add_indicators
from backend.signals.rules import evaluate_with_gate

def _frame(n=300):
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    t = np.arange(n)
    close = pd.Series(150 + 40*np.sin(t/15.0), index=idx)
    return pd.DataFrame({"Open": close, "High": close*1.01, "Low": close*0.99,
                         "Close": close, "Volume": np.full(n, 1000)}, index=idx)

def test_advice_only_when_backtest_passes():
    df = add_indicators(_frame())
    sig = evaluate_with_gate(df, "005930")
    # buy 신호이면서 백테스트 통과해야만 advice=True
    if sig.action == "buy":
        assert sig.advice == sig._backtest_passed
    else:
        assert sig.advice is False
