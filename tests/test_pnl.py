"""보유 수익 계산 순수 함수 — KR(원 정수)·US($ 소수)·보유 없음·avg null. 설계 2026-07-17."""


def test_pnl_basic():
    from backend.flow.pnl import compute
    assert compute(253500, 230000, 10) == {"pnl": 235000, "pnl_pct": round((253500 / 230000 - 1) * 100, 2)}


def test_pnl_none_when_no_holding():
    from backend.flow.pnl import compute
    assert compute(100, None, 5) == {"pnl": None, "pnl_pct": None}
    assert compute(100, 90, None) == {"pnl": None, "pnl_pct": None}
    assert compute(None, 90, 5) == {"pnl": None, "pnl_pct": None}


def test_pnl_us_float():
    from backend.flow.pnl import compute
    r = compute(189.70, 170.55, 5)
    assert abs(r["pnl"] - (189.70 - 170.55) * 5) < 1e-6
