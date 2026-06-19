import numpy as np
import pandas as pd

from backend.analysis.indicators import add_indicators
from backend.signals.rules import Signal, evaluate


def _frame_from_close(close: pd.Series) -> pd.DataFrame:
    """종가 시리즈로 add_indicators가 기대하는 OHLCV 프레임을 만든다."""
    n = len(close)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(n, 1000),
        },
        index=close.index,
    )


def _golden_cross_frame() -> pd.DataFrame:
    """ma20이 마지막 5봉 안에서 ma60을 상향 돌파하도록 구성한 OHLCV 프레임.

    긴 평탄한 기저(110봉, ma20≈ma60)에 짧은 상승 꼬리(4봉)를 붙이면
    ma20이 ma60보다 빠르게 반응해 꼬리 시작 지점에서 골든크로스가 발생한다.
    꼬리를 4봉으로 짧게 두면 그 교차가 마지막 5봉(iloc[-5:]) 안에 들어온다.
    (REPL 검증: n=114, 교차는 absolute pos 110 = 끝에서 3번째 행 → lookback 통과)
    """
    base, tail, base_val, slope = 110, 4, 100.0, 8.0
    n = base + tail
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    flat = np.full(base, base_val)
    rise = base_val + slope * np.arange(1, tail + 1)
    close = pd.Series(np.concatenate([flat, rise]), index=idx)
    return _frame_from_close(close)


def test_evaluate_returns_signal_dataclass():
    close = pd.Series(
        np.linspace(100, 200, 120),
        index=pd.date_range("2024-01-01", periods=120, freq="D"),
    )
    out = add_indicators(_frame_from_close(close))

    sig = evaluate(out, "005930")

    assert isinstance(sig, Signal)
    assert sig.code == "005930"
    assert sig.action in ("buy", "sell", "hold")
    assert 1 <= sig.confidence <= 5
    assert isinstance(sig.reasons, list)


def test_golden_cross_yields_buy():
    out = add_indicators(_golden_cross_frame())

    # 사전 조건 가드: 골든크로스 이벤트가 실제로 마지막 5봉 안에 있어야 한다.
    ma20, ma60 = out["ma20"], out["ma60"]
    event = (ma20.shift(1) <= ma60.shift(1)) & (ma20 > ma60)
    assert event.iloc[-5:].any(), "골든크로스가 마지막 5봉 안에 없음 — 테스트 데이터 점검 필요"

    sig = evaluate(out, "005930")

    assert sig.action == "buy"
    assert any("골든크로스" in r for r in sig.reasons)
