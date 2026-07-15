"""ADR/DR 환산 모듈 — 파서·미국 장시간 판정 (픽스처는 2026-07-13 실응답 기반)."""
import datetime as dt
from zoneinfo import ZoneInfo

from backend.flow.adr import (parse_fx_chart, parse_naver_fx,
                              parse_naver_world, parse_overseas_detail,
                              us_market_open)

_ET = ZoneInfo("America/New_York")


def test_parse_overseas_detail_real_fixture():
    js = {"rt_cd": "0", "output": {"rsym": "DNASSKHYV", "last": "168.0100",
                                   "base": "149.0000", "curr": "USD",
                                   "tvol": "107674661", "t_xprc": "252889",
                                   "t_rate": "1505.20"}}
    d = parse_overseas_detail(js)
    assert d == {"last": 168.01, "base": 149.0}


def test_parse_overseas_detail_uncovered_symbol_is_silent_empty():
    # 미커버 심볼(예: 죽은 HXSCL)은 rt_cd=0인데 필드가 전부 빈 문자열(실측) — None
    js = {"rt_cd": "0", "output": {"rsym": "", "last": "", "base": ""}}
    assert parse_overseas_detail(js) is None
    assert parse_overseas_detail({"rt_cd": "1", "output": {}}) is None
    assert parse_overseas_detail({}) is None


def test_adr_map_uses_live_ticker_not_stale_skhyv():
    # 2026-07-15 실사고: KIS가 'SKHYV'를 상장일 값($168.01·거래량 0·OHLC 0)에 얼려둔
    # 스테일/오종목으로 제공 → 실거래 티커는 'SKHY'(EXCD=NAS·거래량 수천만, base=전일종가
    # $152.35로 stockanalysis와 일치). 잘못된 티커로의 회귀를 막는다.
    from backend.config import settings
    assert settings.adr_map.get("000660") == "SKHY"
    assert "SKHYV" not in settings.adr_map.values()


def test_parse_fx_chart_real_fixture():
    js = {"rt_cd": "0", "output1": {"hts_kor_isnm": "원/달러(KMB)",
                                    "ovrs_nmix_prpr": "1504.8000"}}
    assert parse_fx_chart(js) == 1504.8
    assert parse_fx_chart({"rt_cd": "0", "output1": {}}) is None
    assert parse_fx_chart({"rt_cd": "1"}) is None


def test_parse_naver_world_comma_and_datas_wrapper():
    js = {"pollingInterval": 70000, "datas": [{
        "closePrice": "1,680.01", "compareToPreviousClosePrice": "19.01",
        "marketStatus": "CLOSE", "localTradedAt": "2026-07-10T16:00:00-04:00"}]}
    d = parse_naver_world(js)
    assert d["last"] == 1680.01 and d["market_status"] == "CLOSE"
    assert abs(d["base"] - 1661.0) < 1e-9  # 전일 종가 = 현재가 - 대비
    assert parse_naver_world({"datas": []}) is None


def test_parse_naver_fx():
    assert parse_naver_fx({"result": {"closePrice": "1,504.40"}}) == 1504.4
    assert parse_naver_fx({"result": {}}) is None


def test_us_market_open_boundaries():
    # 평일 정규장 09:30~16:00 ET — zoneinfo가 DST 처리
    def et(h, m, day=10):  # 2026-07-10 금요일
        return dt.datetime(2026, 7, day, h, m, tzinfo=_ET)
    assert us_market_open(et(9, 30)) is True
    assert us_market_open(et(15, 59)) is True
    assert us_market_open(et(9, 29)) is False
    assert us_market_open(et(16, 0)) is False
    assert us_market_open(et(12, 0, day=11)) is False  # 토요일


# ── 애프터장(시간외) 반영 — 2026-07-15 프로브(overMarketPriceInfo) 기반 ──
def test_parse_naver_world_after_hours_overmarket():
    js = {"datas": [{
        "closePrice": "193.92", "compareToPreviousClosePrice": "41.57",
        "marketStatus": "CLOSE",
        "overMarketPriceInfo": {"tradingSessionType": "AFTER_MARKET",
                                "overMarketStatus": "CLOSE", "overPrice": "185.99",
                                "fluctuationsRatio": "-4.09"}}]}
    d = parse_naver_world(js)
    assert d["last"] == 193.92          # 정규장 종가(변함없음)
    assert d["over_price"] == 185.99    # 애프터장 체결가
    assert d["over_session"] == "AFTER_MARKET" and d["over_status"] == "CLOSE"
    # 시간외 필드가 없으면 over_price 키 미포함(기존 픽스처 하위호환)
    d2 = parse_naver_world({"datas": [{"closePrice": "100",
                                       "compareToPreviousClosePrice": "1",
                                       "marketStatus": "OPEN"}]})
    assert "over_price" not in d2


class _FakeKis:
    async def _get(self, path, tr, params):
        if tr == "HHDFS76200200":      # KIS 정규장 last(시간외 미포함)
            return {"rt_cd": "0", "output": {"last": "193.92", "base": "152.35"}}
        return {"rt_cd": "0", "output1": {"ovrs_nmix_prpr": "1487.80"}}   # 환율


def test_get_quote_prefers_after_hours_when_regular_closed(monkeypatch):
    import asyncio
    from backend.flow import adr as A
    A._cache.clear()
    monkeypatch.setattr(A, "us_market_open", lambda *a, **k: False)   # 정규장 마감

    async def fake_naver(url):
        return {"datas": [{"closePrice": "193.92",
                           "compareToPreviousClosePrice": "41.57", "marketStatus": "CLOSE",
                           "overMarketPriceInfo": {"tradingSessionType": "AFTER_MARKET",
                                                   "overMarketStatus": "OPEN",
                                                   "overPrice": "185.99"}}]}
    monkeypatch.setattr(A, "_naver_json", fake_naver)
    r = asyncio.get_event_loop().run_until_complete(A.get_quote(_FakeKis(), "000660"))
    assert r["usd"] == 185.99          # 애프터장 체결가가 반영됨(정규장 종가 193.92 아님)
    assert r["base_usd"] == 193.92     # base = 정규장 종가
    assert r["session"] == "after" and r["src"] == "naver-ext" and r["us_open"] is False


def test_get_quote_uses_kis_during_regular_hours(monkeypatch):
    import asyncio
    from backend.flow import adr as A
    A._cache.clear()
    monkeypatch.setattr(A, "us_market_open", lambda *a, **k: True)    # 정규장 중
    naver_calls = {"n": 0}

    async def fake_naver(url):
        naver_calls["n"] += 1
        return {"datas": []}
    monkeypatch.setattr(A, "_naver_json", fake_naver)
    r = asyncio.get_event_loop().run_until_complete(A.get_quote(_FakeKis(), "000660"))
    assert r["usd"] == 193.92 and r["session"] == "regular" and r["src"] == "kis"
    assert naver_calls["n"] == 0       # 정규장 중엔 네이버 호출 생략(KIS 실시간)
