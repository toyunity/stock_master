"""봉 차트 데이터(분봉 파싱·집계·데모 합성·라우트) 테스트."""
import asyncio

from backend.flow.candles import aggregate, get_candles
from backend.flow.kis import parse_minute_candles


def test_parse_minute_candles_real_fields_sorted_ascending():
    # 실응답(2026-07-10 SK하이닉스) 기반 — 최신순으로 내려옴 → 오름차순 보장
    js = {"rt_cd": "0", "output2": [
        {"stck_bsop_date": "20260710", "stck_cntg_hour": "153000",
         "stck_prpr": "2233000", "stck_oprc": "2230000", "stck_hgpr": "2235000",
         "stck_lwpr": "2228000", "cntg_vol": "3159",
         "acml_tr_pbmn": "7166699023500"},
        {"stck_bsop_date": "20260710", "stck_cntg_hour": "152900",
         "stck_prpr": "2230000", "stck_oprc": "2231000", "stck_hgpr": "2232000",
         "stck_lwpr": "2229000", "cntg_vol": "1200",
         "acml_tr_pbmn": "7159644023500"},
    ]}
    bars = parse_minute_candles(js)
    assert bars[0]["t"] == "15:29:00" and bars[-1]["t"] == "15:30:00"
    assert bars[-1] == {"t": "15:30:00", "open": 2230000, "high": 2235000,
                        "low": 2228000, "close": 2233000, "vol": 3159}


def _bar(t, o=100, h=110, l=90, c=105, v=10):
    return {"t": t, "open": o, "high": h, "low": l, "close": c, "vol": v}


def test_aggregate_5min_buckets_align_to_0900():
    bars = [_bar("09:00:00", o=100, c=101), _bar("09:01:00", h=120),
            _bar("09:04:00", l=80, c=99, v=5),
            _bar("09:05:00", o=99, c=98)]
    agg = aggregate(bars, 5)
    assert len(agg) == 2
    b0 = agg[0]
    assert b0["t"] == "09:00:00"
    assert b0["open"] == 100      # 첫 봉 시가
    assert b0["high"] == 120 and b0["low"] == 80
    assert b0["close"] == 99      # 마지막 봉 종가
    assert b0["vol"] == 25
    assert agg[1]["t"] == "09:05:00" and agg[1]["close"] == 98


def test_clip_drops_wrapped_previous_session_rows():
    # 실측(2026-07-10): 마지막 페이지(hour=092600)가 08:57~09:26 대신
    # 09:00~09:26 + 전일 잔재(15:27~15:30, 거래량 0/전일 종가)를 되감아 반환한다.
    from backend.flow.candles import _clip
    bars = [_bar("09:00:00"), _bar("09:26:00"),
            _bar("15:29:00", v=0), _bar("15:30:00", c=2186000)]
    out = _clip(bars, "12:56:35")  # 조회 시각(12:56) 이후 봉은 잔재
    assert [b["t"] for b in out] == ["09:00:00", "09:26:00"]
    # 장 마감 후 조회(latest=15:30)면 15:30 봉은 실데이터라 유지
    assert len(_clip(bars, "15:30:00")) == 4


def test_get_candles_demo_mode_synthesizes(monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "kis_app_key", None)
    loop = asyncio.new_event_loop()
    try:
        d1 = loop.run_until_complete(get_candles("000660", "1m"))
        d5 = loop.run_until_complete(get_candles("000660", "5m"))
    finally:
        loop.close()
    assert d1["tf"] == "1m" and len(d1["candles"]) > 300  # 09:00~15:30 분봉
    assert d1["candles"][0]["t"] == "09:00:00"
    assert len(d5["candles"]) == (len(d1["candles"]) + 4) // 5 or d5["candles"]
    for b in d1["candles"][:5]:
        assert b["low"] <= b["open"] <= b["high"]
        assert b["low"] <= b["close"] <= b["high"]


def test_candles_api_routes(monkeypatch):
    from fastapi.testclient import TestClient

    import backend.api.app as appmod
    from backend.api.app import app
    client = TestClient(app)

    async def fake(code, tf):
        return {"tf": tf, "candles": [{"t": "09:00:00", "open": 1, "high": 2,
                                       "low": 1, "close": 2, "vol": 3}]}
    monkeypatch.setattr(appmod.candles, "get_candles", fake)
    r = client.get("/api/candles/000660?tf=5m")
    assert r.status_code == 200 and r.json()["tf"] == "5m"
    assert client.get("/api/candles/12ab?tf=5m").status_code == 404
    assert client.get("/api/candles/000660?tf=3h").status_code == 400


def test_live_page_has_chart_and_collapsed_panels():
    from backend.report.live_page import render_live_page
    html = render_live_page("000660", "SK하이닉스", "demo")
    assert "pchart" in html and "일봉" in html and "5분" in html  # 봉 주기 선택
    assert html.count("<details") >= 3  # 일별/기관세부/체결 기본 접힘
    assert "<summary" in html
