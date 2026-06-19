from __future__ import annotations

import numpy as np
import pandas as pd
from backend.analysis.indicators import add_indicators
from backend.analysis.backtest import backtest_strategy, BacktestResult


def _wavy_frame(n=300):
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    t = np.arange(n)
    close = pd.Series(150 + 40*np.sin(t/15.0), index=idx)  # 주기적 등락
    return pd.DataFrame({"Open": close, "High": close*1.01, "Low": close*0.99,
                         "Close": close, "Volume": np.full(n, 1000)}, index=idx)


def test_backtest_returns_result_with_metrics():
    df = add_indicators(_wavy_frame())
    res = backtest_strategy(df, "golden_cross")
    assert isinstance(res, BacktestResult)
    assert res.trades >= 0
    assert 0.0 <= res.win_rate <= 1.0
    assert isinstance(res.passed, bool)


def test_zero_trades_does_not_pass():
    df = add_indicators(_wavy_frame())
    res = backtest_strategy(df, "never")  # 신호가 절대 안 나는 전략 → trades 0 → passed False
    assert res.trades == 0
    assert res.passed is False
