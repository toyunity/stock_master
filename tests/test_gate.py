import numpy as np
import pandas as pd
from unittest.mock import patch
from backend.analysis.indicators import add_indicators
from backend.analysis.backtest import BacktestResult
from backend.signals.rules import evaluate, evaluate_with_gate

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


def _golden_cross_frame():
    base = [100.0] * 110
    tail = [100.0 + 8.0 * (k + 1) for k in range(4)]
    close = pd.Series(base + tail)
    idx = pd.date_range("2023-01-01", periods=len(close), freq="D")
    close.index = idx
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(len(close), 1000)}, index=idx)


def test_advice_true_when_buy_and_backtest_passes():
    df = add_indicators(_golden_cross_frame())
    assert evaluate(df, "005930").action == "buy"  # precondition: frame yields a buy
    mock = BacktestResult("golden_cross", 10, 0.8, 2.0, 0.05, passed=True)
    with patch("backend.signals.rules.backtest_strategy", return_value=mock):
        sig = evaluate_with_gate(df, "005930")
    assert sig.advice is True
    assert sig._backtest_passed is True


def test_advice_false_when_buy_but_backtest_fails():
    df = add_indicators(_golden_cross_frame())
    mock = BacktestResult("golden_cross", 2, 0.0, 0.0, 0.0, passed=False)
    with patch("backend.signals.rules.backtest_strategy", return_value=mock):
        sig = evaluate_with_gate(df, "005930")
    assert sig.advice is False
