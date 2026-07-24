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


def test_parse_keeps_today_row_when_confirmed_after_close():
    # 마감 후엔 당일 공매도 확정치가 채워진다(2026-07-23 증권사 화면 실측:
    # 272,237주 4.30%). 날짜만 보고 무조건 버리면 오늘분은 영원히 못 본다.
    js = {"rt_cd": "0", "output2": [
        _row("20260723", 272237, 6327408, "4.30", close="1919000"),
        _row("20260722", 91472, 4802637, "1.90")]}
    rows = parse_short_sale(js, "2026-07-23", allow_today=True)
    assert [r["date"] for r in rows] == ["2026-07-22", "2026-07-23"]
    assert rows[-1]["qty"] == 272237 and rows[-1]["ratio"] == 4.30


def test_parse_still_drops_today_row_during_session():
    # 장중엔 당일 행이 0(또는 미확정)이므로 종전대로 제외 — 기본값은 안전측
    js = {"rt_cd": "0", "output2": [
        _row("20260723", 0, 0, "0.00"),
        _row("20260722", 91472, 4802637, "1.90")]}
    assert [r["date"] for r in parse_short_sale(js, "2026-07-23")] == ["2026-07-22"]
    # 허용해도 0행은 꼬리 0 제거가 걸러낸다
    assert [r["date"] for r in parse_short_sale(js, "2026-07-23", allow_today=True)] \
        == ["2026-07-22"]


def _fixed_kst(monkeypatch, hhmm: str, day: str = "2026-07-23"):
    import datetime as _dt

    class _Now:
        def strftime(self, f):
            return hhmm if f == "%H:%M" else hhmm + ":00"

    monkeypatch.setattr(shortsale.kst, "now", lambda: _Now())
    monkeypatch.setattr(shortsale.kst, "today",
                        lambda: _dt.date.fromisoformat(day))


def test_get_history_picks_up_today_after_close(monkeypatch):
    class FakeClient:
        async def _get(self, path, tr, params):
            return {"rt_cd": "0", "output2": [
                _row("20260723", 272237, 6327408, "4.30", close="1919000"),
                _row("20260722", 91472, 4802637, "1.90")]}

    shortsale._cache.clear()
    _fixed_kst(monkeypatch, "13:00")                       # 장중 — 당일 제외
    assert _run(shortsale.get_history(FakeClient(), "000660"))["asof"] == "2026-07-22"
    shortsale._cache.clear()
    _fixed_kst(monkeypatch, "16:20")                       # 마감 후 — 당일 반영
    assert _run(shortsale.get_history(FakeClient(), "000660"))["asof"] == "2026-07-23"
    shortsale._cache.clear()


def test_get_history_retries_soon_while_today_is_pending(monkeypatch):
    # 마감 후 공표 직전에 한 번 조회하면 1시간 캐시가 당일치를 최대 1시간 가둔다
    calls = []

    class LateClient:
        async def _get(self, path, tr, params):
            calls.append(1)
            out = [_row("20260722", 91472, 4802637, "1.90")]
            if len(calls) > 1:                              # 두 번째 조회에 공표
                out.insert(0, _row("20260723", 272237, 6327408, "4.30"))
            return {"rt_cd": "0", "output2": out}

    shortsale._cache.clear()
    _fixed_kst(monkeypatch, "16:05")
    c = LateClient()
    assert _run(shortsale.get_history(c, "000660"))["asof"] == "2026-07-22"
    ts, data = shortsale._cache["000660"]
    shortsale._cache["000660"] = (ts - 400.0, data)         # 400초 경과로 조작
    assert _run(shortsale.get_history(c, "000660"))["asof"] == "2026-07-23"
    assert len(calls) == 2
    # 당일치가 들어온 뒤에는 다시 1시간 캐시
    ts, data = shortsale._cache["000660"]
    shortsale._cache["000660"] = (ts - 400.0, data)
    assert _run(shortsale.get_history(c, "000660"))["asof"] == "2026-07-23"
    assert len(calls) == 2
    shortsale._cache.clear()


def test_get_history_does_not_chase_today_on_weekend(monkeypatch):
    # 주말엔 '당일 확정'이 영원히 안 차므로 짧은 TTL로 재조회하면 헛돈다
    calls = []

    class C:
        async def _get(self, path, tr, params):
            calls.append(1)
            return {"rt_cd": "0", "output2": [
                _row("20260724", 91472, 4802637, "1.90")]}

    shortsale._cache.clear()
    _fixed_kst(monkeypatch, "17:00", day="2026-07-25")     # 토요일 저녁
    c = C()
    _run(shortsale.get_history(c, "000660"))
    ts, data = shortsale._cache["000660"]
    shortsale._cache["000660"] = (ts - 400.0, data)
    _run(shortsale.get_history(c, "000660"))
    assert len(calls) == 1                                  # 1시간 캐시 유지
    shortsale._cache.clear()


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
