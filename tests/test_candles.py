"""봉 차트 데이터(분봉 파싱·집계·데모 합성·라우트) 테스트."""
import asyncio

from backend.flow.candles import _attach_ma, _session_window, aggregate, get_candles
from backend.flow.kis import parse_minute_candles


def test_session_window_formats(monkeypatch):
    """_session_window()가 session.py(단일 정의 소스)에서 파생한 KIS 문자열 포맷을 유지하는지
    고정(pin) — 시작은 'HH:MM:SS', 마감은 'HHMMSS'(KIS 기준시각 페이지네이션이 요구, 실측).
    2026-08 NXT 애프터마켓 대응 리팩터가 이 포맷을 깨면 /live 당일 분봉 조회가 조용히 실패한다."""
    from backend.config import settings
    monkeypatch.setattr(settings, "market_div", "UN")
    assert _session_window() == ("08:00:00", "200000")
    monkeypatch.setattr(settings, "market_div", "NX")
    assert _session_window() == ("08:00:00", "200000")
    monkeypatch.setattr(settings, "market_div", "J")
    assert _session_window() == ("09:00:00", "153000")


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


def test_parse_minute_candles_drops_other_day_rows():
    # 실사고(2026-07-13 21:53): 마감 후 조회에서 KIS가 금요일 19:5x 봉(2,20만원대)을
    # 같은 시각 라벨로 간헐 혼입 — 월요일 −16% 차트 꼬리가 급반등처럼 보였다.
    # date를 주면 다른 날짜 행 제거, 날짜 필드 없는 행은 보존(하위 호환).
    js = {"rt_cd": "0", "output2": [
        {"stck_bsop_date": "20260713", "stck_cntg_hour": "195900",
         "stck_prpr": "1828000", "stck_oprc": "1829000", "stck_hgpr": "1829000",
         "stck_lwpr": "1828000", "cntg_vol": "32799"},
        {"stck_bsop_date": "20260710", "stck_cntg_hour": "195900",   # 금요일 잔재
         "stck_prpr": "2201000", "stck_oprc": "2202000", "stck_hgpr": "2202000",
         "stck_lwpr": "2200000", "cntg_vol": "23218"},
        {"stck_cntg_hour": "195800", "stck_prpr": "1829000",          # 날짜 필드 없음
         "stck_oprc": "1829000", "stck_hgpr": "1830000",
         "stck_lwpr": "1828000", "cntg_vol": "21766"},
    ]}
    bars = parse_minute_candles(js, "20260713")
    assert [b["close"] for b in bars] == [1829000, 1828000]  # 금요일 행 제거
    assert len(parse_minute_candles(js)) == 3                # date 미지정=기존 동작


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


def test_to_candles_includes_volume():
    import pandas as pd
    from backend.report.dashboard import to_candles
    df = pd.DataFrame({"Open": [1, 2], "High": [2, 3], "Low": [0, 1],
                       "Close": [1.5, 2.5], "Volume": [100, 200]},
                      index=pd.to_datetime(["2026-07-14", "2026-07-15"]))
    out = to_candles(df, 10)
    assert out[0]["vol"] == 100 and out[-1]["vol"] == 200   # 일봉 거래량 실림
    # Volume 컬럼 없으면 vol 키 미포함(하위호환)
    assert "vol" not in to_candles(df.drop(columns=["Volume"]), 10)[0]


def test_attach_ma_includes_5_and_10():
    bars = [{"close": float(i)} for i in range(1, 13)]  # 1..12
    out = _attach_ma(bars)
    # ma5: 앞 4개 None, 5번째(idx4)부터 값. 종가 1~5 평균 = 3.0, 6~10(idx9) 평균 = 8.0
    assert out[0]["ma5"] is None and out[3]["ma5"] is None
    assert out[4]["ma5"] == 3.0
    assert out[9]["ma5"] == 8.0
    # ma10: 10번째(idx9)부터. 종가 1~10 평균 = 5.5
    assert out[8]["ma10"] is None
    assert out[9]["ma10"] == 5.5
    # 기존 키 유지
    assert "ma20" in out[0] and "ma60" in out[0] and "ma120" in out[0]
