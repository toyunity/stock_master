"""신용융자 잔고(FHPST04760000) — 파서·강제청산 판정 (픽스처는 실응답 기반)."""
import asyncio

from backend.flow import credit
from backend.flow.credit import credit_signal, parse_credit


def _run(coro, timeout=10.0):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(coro, timeout))
    finally:
        loop.close()


def _row(date, qty, close, **kw):
    r = {"deal_date": date, "stlm_date": date,
         "whol_loan_rmnd_stcn": str(qty), "whol_loan_rmnd_amt": "521917008",
         "whol_loan_rmnd_rate": "0.45", "whol_loan_new_stcn": "635725",
         "whol_loan_rdmp_stcn": "585894", "stck_prpr": str(close)}
    r.update(kw)
    return r


def test_parse_credit_real_fixture_value_from_close_not_amt():
    # 실측 2026-07-08 행 — 금액은 단위 불명인 amt 대신 주수×종가로 산출
    js = {"rt_cd": "0", "output": [
        _row("20260708", 3296400, 2076000),
        _row("20260707", 3246469, 2140000)]}  # 응답은 최신순
    rows = parse_credit(js)
    assert [r["date"] for r in rows] == ["2026-07-07", "2026-07-08"]  # 오름차순
    last = rows[-1]
    assert last["qty"] == 3296400 and last["ratio"] == 0.45
    assert last["value"] == 3296400 * 2076000  # amt(단위 불명) 미사용
    assert last["chg"] == 3296400 - 3246469
    assert rows[0]["chg"] is None
    assert parse_credit({"rt_cd": "1"}) == []


def _rows(*specs):
    """specs: (qty, close) 오름차순 → parse_credit 결과 형태."""
    out = []
    for i, (qty, close) in enumerate(specs):
        out.append({"date": f"2026-07-{7 + i:02d}", "qty": qty, "ratio": 0.4,
                    "new": 0, "rdmp": 0, "close": close, "value": qty * close,
                    "chg": (qty - specs[i - 1][0]) if i else None})
    return out


def test_credit_signal_forced_liquidation_day_after_crash():
    # 전일 -4% 급락 → 당일 잔고 -2% 급감 = 강제청산 소화 진행(스펙 판정)
    sig = credit_signal(_rows((3_300_000, 2_200_000),
                              (3_310_000, 2_110_000),   # -4.1% 급락일
                              (3_240_000, 2_130_000)))  # 잔고 -2.1%
    assert "강제청산" in sig["text"] and sig["tone"] == "info"


def test_credit_signal_quadrants():
    up = credit_signal(_rows((3_000_000, 2_000_000), (3_100_000, 1_990_000)))
    assert up["tone"] == "warn"          # 하락에도 신용 증가 — 연료 축적
    repay = credit_signal(_rows((3_000_000, 2_000_000), (2_950_000, 2_010_000)))
    assert repay["tone"] == "good"       # 신용 상환
    flat = credit_signal(_rows((3_000_000, 2_000_000), (3_001_000, 2_005_000)))
    assert flat["tone"] == "flat"
    assert credit_signal([]) is None
    assert credit_signal(_rows((3_000_000, 2_000_000))) is None  # 하루뿐


def test_get_history_soft_error_raises_and_is_not_cached():
    # HTTP 200 + rt_cd≠0을 빈 성공으로 캐시하지 않는다(리뷰 확정) — 다음 주기 재시도
    import pytest

    class SoftErrClient:
        async def _get(self, path, tr, params):
            return {"rt_cd": "2", "msg1": "TIME LIMIT"}

    credit._cache.clear()
    with pytest.raises(RuntimeError):
        _run(credit.get_history(SoftErrClient(), "000660"))
    assert "000660" not in credit._cache
    credit._cache.clear()


def test_get_history_uses_hour_cache(monkeypatch):
    calls = []

    class FakeClient:
        async def _get(self, path, tr, params):
            calls.append(tr)
            return {"rt_cd": "0", "output": [_row("20260710", 3296400, 2076000)]}

    credit._cache.clear()
    d1 = _run(credit.get_history(FakeClient(), "000660"))
    d2 = _run(credit.get_history(FakeClient(), "000660"))
    assert d1["rows"] and d1 == d2
    assert calls == ["FHPST04760000"]  # 두 번째는 캐시
    credit._cache.clear()
