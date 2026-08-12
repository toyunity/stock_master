"""거래소별(KRX/NXT) 거래량 분리 — 파서·왜곡 판정 (픽스처는 2026-07-13 실측)."""
import asyncio

import pytest

from backend.flow import exvol
from backend.flow.exvol import distortion, parse_time_acml, parse_vol


def _run(coro, timeout=10.0):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(coro, timeout))
    finally:
        loop.close()


def test_parse_vol_real_fixture():
    js = {"rt_cd": "0", "output": {"stck_prpr": "1845000", "acml_vol": "7951404",
                                   "acml_tr_pbmn": "15488151827500"}}
    assert parse_vol(js) == {"price": 1845000, "vol": 7951404,
                             "pbmn": 15488151827500}
    assert parse_vol({"rt_cd": "1"}) is None


def test_parse_time_acml_takes_latest_tick():
    # FHPST01060000 output2는 최신순 — 첫 행의 누적이 경계 시각 총량(실측 863,404)
    js = {"rt_cd": "0", "output2": [
        {"stck_cntg_hour": "084959", "acml_vol": "863404", "cnqn": "120"},
        {"stck_cntg_hour": "084955", "acml_vol": "863284", "cnqn": "80"}]}
    assert parse_time_acml(js) == 863404
    # 경계 통과 후 행 없음 = 그 시각까지 체결 0건 → 0 (None이면 본장 집계가
    # 하루 종일 막힌다 — 리뷰 확정)
    assert parse_time_acml({"rt_cd": "0", "output2": []}) == 0
    assert parse_time_acml({"rt_cd": "1"}) is None


def test_distortion_warns_on_thin_market_move():
    # 시간외 -1.5% 인데 장후 거래량이 당일의 0.3% → 왜곡 경고
    d = distortion(1_970_000, 2_000_000, 40_000, 13_000_000)
    assert d["tone"] == "warn" and "유동성 부족" in d["text"]
    assert d["move_pct"] == -1.5
    # 같은 변동인데 거래량 동반(5%) → 유의미 변동
    d = distortion(1_970_000, 2_000_000, 650_000, 13_000_000)
    assert d["tone"] == "info"
    # 변동 미미
    d = distortion(1_999_000, 2_000_000, 40_000, 13_000_000)
    assert d["tone"] == "flat"
    assert distortion(None, 2_000_000, 1, 1) is None


def test_boundary_cache_is_bounded():
    """날짜가 키에 들어간 유일한 캐시 — 가동일수에 비례해 무조건 증가한다.
    경계값은 언제든 재조회 가능하므로 상한에 닿으면 통째로 비워도 손실이 없다."""
    class Client:
        async def _get(self, path, tr, params):
            return {"rt_cd": "0", "output2": [{"acml_vol": "863404"}]}

    exvol._boundary.clear()
    try:
        for i in range(250):
            exvol._boundary[("000660", "2026-0%d-01" % (i % 9 + 1), "%06d" % i)] = i
        assert _run(exvol._acml_at(Client(), "000660", "085959")) == 863404
        assert len(exvol._boundary) <= 201
    finally:
        exvol._boundary.clear()


def test_get_split_raises_on_soft_error_and_does_not_cache():
    # 한쪽 다리(J/NX) 소프트 오류 → 반쪽 스냅샷 캐시 금지, 예외 위임(리뷰 확정)
    class HalfFailClient:
        async def _get(self, path, tr, params):
            if params.get("FID_COND_MRKT_DIV_CODE") == "J":
                return {"rt_cd": "1", "msg1": "초당 거래건수 초과"}
            return {"rt_cd": "0", "output": {"stck_prpr": "1843000",
                                             "acml_vol": "5195600",
                                             "acml_tr_pbmn": "1"}}

    exvol._cache.clear()
    with pytest.raises(RuntimeError):
        _run(exvol.get_split(HalfFailClient(), "000660"))
    assert "000660" not in exvol._cache
    exvol._cache.clear()
