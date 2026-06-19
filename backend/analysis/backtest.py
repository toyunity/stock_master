from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BacktestResult:
    strategy: str
    trades: int
    win_rate: float
    payoff: float          # 평균이익/평균손실
    max_drawdown: float    # 0~1
    passed: bool


def _entry_signals(df, strategy: str):
    """전략별 매수 진입 시점(불리언 시리즈)을 반환."""
    if strategy == "golden_cross":
        s, l = df["ma20"], df["ma60"]
        return (s.shift(1) <= l.shift(1)) & (s > l)
    if strategy == "rsi_oversold":
        return df["rsi14"] < 30
    return df["Close"] < 0  # "never": 항상 False


def backtest_strategy(df, strategy: str, hold_days: int = 10,
                      min_trades: int = 5, min_win_rate: float = 0.5) -> BacktestResult:
    """진입 후 hold_days 뒤 종가로 청산하는 단순 백테스트."""
    entries = _entry_signals(df, strategy).fillna(False)
    close = df["Close"].reset_index(drop=True)
    rets = []
    idxs = [i for i, v in enumerate(entries.values) if v]
    for i in idxs:
        j = i + hold_days
        if j < len(close):
            rets.append((close[j] - close[i]) / close[i])
    trades = len(rets)
    if trades == 0:
        return BacktestResult(strategy, 0, 0.0, 0.0, 0.0, passed=False)
    wins = [r for r in rets if r > 0]
    losses = [-r for r in rets if r < 0]
    win_rate = len(wins) / trades
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 1e-9
    payoff = avg_win / avg_loss if avg_loss else 0.0
    # 단순 자본곡선 MDD
    equity, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        equity *= (1 + r); peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak)
    passed = trades >= min_trades and win_rate >= min_win_rate
    return BacktestResult(strategy, trades, win_rate, payoff, mdd, passed)
