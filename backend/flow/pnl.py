from __future__ import annotations

"""보유 수익 계산 순수 함수. 통화 무관(KR=원, US=$ — 호출부가 통화 일관 보장). 설계 2026-07-17."""


def compute(price, avg, shares):
    if price is None or avg is None or shares is None or avg <= 0:
        return {"pnl": None, "pnl_pct": None}
    pnl = (price - avg) * shares
    if isinstance(avg, int) and isinstance(price, (int, float)) and float(price).is_integer():
        pnl = int(round(pnl))
    return {"pnl": pnl, "pnl_pct": round((price / avg - 1) * 100, 2)}
