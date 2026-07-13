"""공매도 일별(FHPST04830000) — 파서·당일 잠정 행 제외 (픽스처는 실응답 기반)."""
import asyncio

from backend.flow import shortsale
from backend.flow.shortsale import parse_short_sale


def _run(coro, timeout=10.0):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(coro, timeout))
    finally:
        loop.close()


def _row(date, qty, vol, rlim, close="2180000"):
    return {"stck_bsop_date": date, "ssts_cntg_qty": str(qty),
            "acml_vol": str(vol), "ssts_vol_rlim": rlim,
            "ssts_tr_pbmn": "564882324000", "stck_clpr": close,
            "avrg_prc": "2218400" if int(qty) else "0"}


def test_parse_drops_provisional_today_row():
    # T+1 트랩(실측): 당일 행은 누락이 아니라 공매도 필드 0으로 내려온다 — 제외
    js = {"rt_cd": "0", "output2": [
        _row("20260713", 0, 0, "0.00"),          # 오늘(잠정)
        _row("20260710", 254632, 4827239, "5.27"),
        _row("20260709", 63290, 6261504, "1.01")]}
    rows = parse_short_sale(js, "2026-07-13")
    assert [r["date"] for r in rows] == ["2026-07-09", "2026-07-10"]  # 오름차순
    last = rows[-1]
    assert last["qty"] == 254632 and last["vol"] == 4827239
    assert last["ratio"] == 5.27 and last["close"] == 2180000
    assert parse_short_sale({"rt_cd": "1"}, "2026-07-13") == []


def test_parse_drops_trailing_zero_rows_weekend_and_predawn():
    # 잠정 0행은 날짜가 '오늘'이 아닐 수도 있다(토요일 조회 시 금요일 미공시분,
    # 자정~발표 전) — 꼬리 0행은 '확정 0주' 오인 방지를 위해 제거(리뷰 확정).
    js = {"rt_cd": "0", "output2": [
        _row("20260710", 0, 0, "0.00"),          # 금요일 — 아직 미공시(0 잔존)
        _row("20260709", 63290, 6261504, "1.01"),
        _row("20260708", 0, 5000000, "0.00"),    # 중간의 진짜 0 공매도일은 보존
        _row("20260707", 100000, 4000000, "2.50")]}
    rows = parse_short_sale(js, "2026-07-11")    # 토요일 시점 조회
    assert [r["date"] for r in rows] == ["2026-07-07", "2026-07-08", "2026-07-09"]
    assert rows[1]["qty"] == 0                   # 중간 0행 유지


def test_get_history_soft_error_raises_and_is_not_cached():
    # HTTP 200 + rt_cd≠0(KIS 소프트 오류)을 빈 성공으로 1시간 캐시하면 매분
    # 재시도가 무력화된다(리뷰 확정) — 예외로 위임하고 캐시를 오염시키지 않는다.
    import pytest

    class SoftErrClient:
        async def _get(self, path, tr, params):
            return {"rt_cd": "1", "msg1": "초당 거래건수를 초과하였습니다"}

    shortsale._cache.clear()
    with pytest.raises(RuntimeError):
        _run(shortsale.get_history(SoftErrClient(), "000660"))
    assert "000660" not in shortsale._cache
    shortsale._cache.clear()


def test_get_history_asof_and_cache():
    calls = []

    class FakeClient:
        async def _get(self, path, tr, params):
            calls.append(params["FID_INPUT_DATE_2"])
            return {"rt_cd": "0", "output2": [
                _row("20260710", 254632, 4827239, "5.27")]}

    shortsale._cache.clear()
    d1 = _run(shortsale.get_history(FakeClient(), "000660"))
    d2 = _run(shortsale.get_history(FakeClient(), "000660"))
    assert d1["asof"] == "2026-07-10" and d1 == d2
    assert len(calls) == 1  # 1시간 캐시
    shortsale._cache.clear()
