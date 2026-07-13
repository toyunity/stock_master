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
