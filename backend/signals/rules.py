from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Signal:
    code: str
    action: str               # "buy" | "sell" | "hold"
    confidence: int           # 1~5
    reasons: list[str] = field(default_factory=list)
    advice: bool = False      # 백테스트 게이트 통과 시 True (S2에서 설정)


def _crossed_up(short, long_, lookback: int = 5) -> bool:
    """최근 lookback 봉 안에서 단기선이 장기선을 상향 돌파(신선한 골든크로스)."""
    event = (short.shift(1) <= long_.shift(1)) & (short > long_)
    return bool(event.iloc[-lookback:].any())


def _crossed_down(short, long_, lookback: int = 5) -> bool:
    """최근 lookback 봉 안에서 단기선이 장기선을 하향 돌파(신선한 데드크로스)."""
    event = (short.shift(1) >= long_.shift(1)) & (short < long_)
    return bool(event.iloc[-lookback:].any())


def evaluate(df, code: str) -> Signal:
    """지표가 채워진 DataFrame을 받아 매매 신호를 산출한다."""
    buy, sell = [], []
    ma20, ma60, rsi = df["ma20"], df["ma60"], df["rsi14"]

    if _crossed_up(ma20, ma60):
        buy.append("20일선이 60일선을 상향 돌파(골든크로스)")
    if _crossed_down(ma20, ma60):
        sell.append("20일선이 60일선을 하향 돌파(데드크로스)")
    last_rsi = rsi.iloc[-1]
    if last_rsi < 30:
        buy.append(f"RSI {last_rsi:.0f} (과매도 — 반등 가능 참고)")
    if last_rsi > 70:
        sell.append(f"RSI {last_rsi:.0f} (과매수 — 과열 주의)")

    if len(buy) >= len(sell) and buy:
        action, reasons = "buy", buy
    elif sell:
        action, reasons = "sell", sell
    else:
        action, reasons = "hold", ["뚜렷한 신호 없음 — 관망"]

    confidence = max(1, min(5, len(reasons)))
    return Signal(code=code, action=action, confidence=confidence, reasons=reasons)
