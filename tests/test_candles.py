"""봉 차트 데이터(분봉 파싱·집계·주·월봉·데모 합성·라우트) 테스트."""
import asyncio
import datetime as dt

from backend.flow.candles import (_attach_ma, _attach_macd, _session_window,
                                  aggregate, aggregate_daily, get_candles)
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


# ── 주봉·월봉 ─────────────────────────────────────────────────────

def _day(t, o=100, h=110, l=90, c=105, v=10):  # noqa: E741
    return {"t": t, "open": o, "high": h, "low": l, "close": c, "vol": v}


def test_aggregate_daily_weekly_iso_buckets():
    # 2026-07-31(금, ISO 31주) / 2026-08-03(월, 32주) — 날짜는 이어져도 주가 갈리면 딴 봉
    bars = [_day("2026-07-30", o=100, c=101),
            _day("2026-07-31", h=130, l=80, c=99, v=7),
            _day("2026-08-03", o=99, c=98)]
    agg = aggregate_daily(bars, "1w")
    assert len(agg) == 2
    w0 = agg[0]
    assert w0["t"] == "2026-07-31"                    # 라벨 = 버킷 마지막 거래일
    assert w0["open"] == 100 and w0["close"] == 99    # 시가=첫날, 종가=마지막날
    assert w0["high"] == 130 and w0["low"] == 80      # 구간 극값
    assert w0["vol"] == 17                            # 거래량 합산
    assert agg[1]["t"] == "2026-08-03" and agg[1]["close"] == 98


def test_aggregate_daily_monthly_buckets():
    bars = [_day("2026-07-01", o=100), _day("2026-07-31", c=120, h=140),
            _day("2026-08-03", o=120, c=118)]
    agg = aggregate_daily(bars, "1mo")
    assert [b["t"] for b in agg] == ["2026-07-31", "2026-08-03"]
    assert agg[0]["open"] == 100 and agg[0]["close"] == 120 and agg[0]["high"] == 140
    assert agg[1]["close"] == 118


def test_need_refetch_sees_start_coverage():
    """PriceAdapter의 사각지대 고정 — end 커버리지만 보므로 대시보드가 만든 400일
    캐시도 그대로 반환된다. 이걸 못 거르면 주·월봉이 1.5년치로 조용히 쪼그라든다."""
    import pandas as pd
    from backend.flow.candles import _need_refetch
    start = dt.date(2011, 8, 7)
    short = pd.DataFrame({"Close": [1.0, 1.0]},
                         index=pd.to_datetime(["2026-01-02", "2026-08-06"]))
    assert _need_refetch(short, start) is True        # 400일짜리 → 다시 받아야 한다
    long_ = pd.DataFrame({"Close": [1.0, 1.0]},
                         index=pd.to_datetime(["2011-08-10", "2026-08-06"]))
    assert _need_refetch(long_, start) is False       # 시작까지 덮으면 캐시로 충분
    assert _need_refetch(None, start) is True
    assert _need_refetch(short.iloc[0:0], start) is True


def test_get_candles_weekly_and_monthly(monkeypatch):
    """주·월봉은 장기 일봉을 집계하고 이동평균을 붙여 최근 120봉만 내린다 — 네트워크 0."""
    import backend.flow.candles as cd
    days, cur, i = [], dt.date(2020, 1, 1), 0
    while len(days) < 900:                            # 평일만 — 합성 3.5년
        if cur.weekday() < 5:
            days.append(_day(cur.isoformat(), o=100 + i, c=101 + i))
            i += 1
        cur += dt.timedelta(days=1)
    monkeypatch.setattr(cd, "_long_daily_bars", lambda code: days)
    monkeypatch.setattr(cd, "_kis_live", lambda code: False)   # FDR 집계 경로가 검증 대상(KIS 우선은 별도 테스트)
    loop = asyncio.new_event_loop()
    try:
        w = loop.run_until_complete(cd.get_candles("000660", "1w"))
        m = loop.run_until_complete(cd.get_candles("000660", "1mo"))
    finally:
        loop.close()
    assert w["tf"] == "1w" and len(w["candles"]) == 120   # 181주 → 최근 120주만
    assert m["tf"] == "1mo" and 0 < len(m["candles"]) <= 120
    assert w["candles"][-1]["ma5"] is not None            # 이동평균 부착
    assert w["candles"][5]["vol"] == 50                   # 온전한 한 주 = 거래일 5일 합


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
    assert client.get("/api/candles/000660?tf=1w").status_code == 200
    assert client.get("/api/candles/000660?tf=1mo").status_code == 200
    assert client.get("/api/candles/12ab?tf=5m").status_code == 404
    assert client.get("/api/candles/000660?tf=3h").status_code == 400
    # 월봉이 '1M'이었다면 소문자 정규화 한 번에 1분봉과 겹친다 — '1M'은 영원히 400이어야 한다
    assert client.get("/api/candles/000660?tf=1M").status_code == 400


def test_live_page_has_chart_and_collapsed_panels():
    from backend.report.live_page import render_live_page
    html = render_live_page("000660", "SK하이닉스", "demo")
    assert "pchart" in html and "일봉" in html and "5분" in html  # 봉 주기 선택
    assert "mchart" in html and "MACD" in html                  # MACD 히스토그램 패널
    assert 'data-tf="1w"' in html and 'data-tf="1mo"' in html    # 주봉·월봉 탭
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


def test_attach_macd_osc_has_ema_warmup_and_follows_trend():
    """MACD(12,26,9) 히스토그램. 앞 33봉은 None이어야 한다 — 프런트의 표본 부족
    가드가 전부 `c[key]!=null`에 걸려 있어, EMA가 1번 봉부터 값을 내면
    워밍업 안 된 막대가 왼쪽 끝에 그려진다(SMA는 None이 공짜라 이 함정이 없었다)."""
    up = _attach_macd([{"close": float(i)} for i in range(1, 61)])
    assert up[32]["osc"] is None
    assert up[33]["osc"] is not None
    assert up[-1]["osc"] > 0                      # 상승 추세 → 0 위
    down = _attach_macd([{"close": float(i)} for i in range(1, 41)]
                        + [{"close": float(40 - i)} for i in range(1, 21)])
    assert down[-1]["osc"] < 0                    # 하락 전환 → 0 아래


def test_get_candles_payload_carries_osc(monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "kis_app_key", None)
    loop = asyncio.new_event_loop()
    try:
        d = loop.run_until_complete(get_candles("000660", "5m"))
    finally:
        loop.close()
    assert "osc" in d["candles"][0]                # 이평선과 같은 페이로드로 함께 내려간다
    assert any(c["osc"] is not None for c in d["candles"])


# ── 자원 수명주기(감사 A2·A3) ─────────────────────────────────────

def test_daily_and_wm_fetch_are_time_capped(monkeypatch):
    """상한 없는 blocking FDR 호출은 기본 스레드풀(14슬롯)을 말린다.

    야후(FDR 배경)가 RST 없이 무응답이 되면 요청도 스레드도 영영 안 끝난다 —
    폴링마다 스레드가 하나씩 매달려 풀이 마르면 옵션 로드·글로벌 지표까지
    시작조차 못 한다(감사 2026-08-12 실측). 상한은 요청만 돌려준다.
    매달린 스레드는 못 돌려받는다(worldidx.py:194-196에 같은 한계가 적혀 있다).
    """
    import time as _t

    import pytest

    import backend.flow.candles as cd
    monkeypatch.setattr(cd, "_FETCH_TIMEOUT", 0.05)
    monkeypatch.setattr(cd, "_daily_candles", lambda code: _t.sleep(0.3) or [])
    monkeypatch.setattr(cd, "_wm_candles", lambda code, tf: _t.sleep(0.3) or [])
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(asyncio.TimeoutError):
            loop.run_until_complete(cd.get_candles("000660", "1d"))
        with pytest.raises(asyncio.TimeoutError):
            loop.run_until_complete(cd.get_candles("000660", "1w"))
    finally:
        loop.close()


def test_long_cache_is_bounded(monkeypatch, tmp_path):
    """주·월봉 원료(일봉 15년)는 종목당 1.9MB다 — 상한이 없으면 스캐너로 종목을
    넘겨보는 것만으로 수십 MB가 재기동 전까지 안 돌아온다(TTL은 신선도만 정할 뿐
    엔트리를 지우지 않는다)."""
    import time as _t

    import pandas as pd

    import backend.flow.candles as cd
    from backend.adapters import prices
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))  # 실캐시 미접촉
    df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0], "Close": [1.5],
                       "Volume": [100]}, index=pd.to_datetime(["2026-08-10"]))
    monkeypatch.setattr(prices.PriceAdapter, "get_ohlcv",
                        lambda self, code, start, end, force=False: df)
    cd._long_cache.clear()
    try:
        for i in range(25):
            cd._long_cache["X%03d" % i] = (_t.time(), [])
        cd._long_daily_bars("005930")
        assert len(cd._long_cache) <= 21
    finally:
        cd._long_cache.clear()


# ── NXT 미상장 종목의 분봉(2026-08-10 실사고: 금현물 ETF 411060 차트가 통째로 빔) ──

def _min_row(hhmmss, price, date="20260810"):
    """FHKST03010200 output2 한 행. price=0이면 KIS가 주는 '값 없는 껍데기'."""
    p = str(price)
    return {"stck_bsop_date": date, "stck_cntg_hour": hhmmss, "stck_prpr": p,
            "stck_oprc": p, "stck_hgpr": p, "stck_lwpr": p,
            "cntg_vol": "10" if price else "0"}


class _DivClient:
    """시장구분마다 다른 응답을 주는 가짜 KIS — 네트워크·키 없음.

    `empty_divs`에 든 구분으로 물으면 rt_cd=0 '정상처리'에 값이 0인 행만 준다.
    실제 KIS가 NXT 미상장 종목을 UN으로 물었을 때 하는 짓 그대로다(실측).
    """

    def __init__(self, empty_divs=("UN",), div="UN"):
        self.div, self.empty_divs, self.asked = div, set(empty_divs), []

    async def _get(self, path, tr_id, params):
        d = params["FID_COND_MRKT_DIV_CODE"]
        self.asked.append(d)
        price = 0 if d in self.empty_divs else 27495
        return {"rt_cd": "0", "msg1": "정상처리 되었습니다.",
                "output2": [_min_row("100000", price)]}


def _minutes(client, code="411060", now="10:05:00"):
    import backend.flow.candles as cd
    cd._min_cache.clear()
    cd._krx_only.clear()
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        cd._day_minutes(client, code))


def test_minute_bars_fall_back_to_krx_only_when_unified_is_hollow(monkeypatch):
    """통합(UN)이 값 0인 껍데기만 주면 KRX 전용(J)으로 되물어야 한다.

    KIS가 rt_cd=0 '정상처리'를 주므로 예외로는 절대 못 잡는다 — 값으로 판정한다.
    이게 없으면 금현물 ETF 상세 화면이 빈 차트로 뜬다(2026-08-10 실사고).
    """
    import backend.flow.candles as cd
    monkeypatch.setattr(cd, "_session_window", lambda: ("09:00:00", "200000"))
    monkeypatch.setattr(cd.kst, "now", lambda: dt.datetime(2026, 8, 10, 10, 5))
    monkeypatch.setattr(cd.kst, "today", lambda: dt.date(2026, 8, 10))
    c = _DivClient(empty_divs=("UN",))
    out = _minutes(c)
    assert out and out[-1]["close"] == 27495, out
    assert "J" in c.asked                      # 폴백이 실제로 나갔다


def test_minute_bars_do_not_refetch_when_unified_works(monkeypatch):
    """정상 종목(삼성·하이닉스 등)은 J를 절대 추가 호출하지 않는다 — KIS 호출 낭비 금지."""
    import backend.flow.candles as cd
    monkeypatch.setattr(cd, "_session_window", lambda: ("09:00:00", "200000"))
    monkeypatch.setattr(cd.kst, "now", lambda: dt.datetime(2026, 8, 10, 10, 5))
    monkeypatch.setattr(cd.kst, "today", lambda: dt.date(2026, 8, 10))
    c = _DivClient(empty_divs=())
    out = _minutes(c, code="005930")
    assert out and out[-1]["close"] == 27495
    assert c.asked == ["UN"]                   # 한 번만


def test_krx_only_verdict_is_remembered(monkeypatch):
    """한 번 J로 확정된 종목은 다음 조회에서 곧장 J로 간다 — 빈 UN 조회를 되풀이하지 않게."""
    import backend.flow.candles as cd
    monkeypatch.setattr(cd, "_session_window", lambda: ("09:00:00", "200000"))
    monkeypatch.setattr(cd.kst, "now", lambda: dt.datetime(2026, 8, 10, 10, 5))
    monkeypatch.setattr(cd.kst, "today", lambda: dt.date(2026, 8, 10))
    c = _DivClient(empty_divs=("UN",))
    loop = asyncio.get_event_loop_policy().new_event_loop()
    cd._min_cache.clear()
    cd._krx_only.clear()
    loop.run_until_complete(cd._day_minutes(c, "411060"))
    cd._min_cache.clear()                      # TTL 만료 흉내(기억은 남는다)
    c.asked.clear()
    loop.run_until_complete(cd._day_minutes(c, "411060"))
    assert c.asked == ["J"]                    # UN을 다시 묻지 않는다


# ── 주봉 MACD 판정(작업 B) ────────────────────────────────────────

def _wk(oscs):
    """osc 값 배열 → weekly_macd_signal 입력(판정은 osc만 본다)."""
    return [{"osc": v} for v in oscs]


def test_weekly_macd_signal_reads_sign_and_direction():
    """부호(0 위/아래)만으로는 마스터의 질문에 답이 안 된다 — '0 아래인데 얕아지는 중'과
    '0 아래로 깊어지는 중'은 정반대다(질문 2026-08-25: 일봉은 반등인데 주봉은 하향추세).

    실측(000660 주봉 osc, 2026-08-25): 8/14 -110,057 → 8/21 -106,590 → 8/25 -104,781
    = 0 아래지만 2주째 얕아지는 중(8/14가 최저라 그 앞 봉은 더 얕다)."""
    from backend.flow.candles import weekly_macd_signal
    s = weekly_macd_signal(_wk([-95000.0, -110057.0, -106590.0, -104781.0]))
    assert s["tone"] == "info"
    assert "0 아래지만" in s["text"] and "2주째 얕아지는 중" in s["text"]
    assert "-104,781" in s["text"]   # 값도 같이 — 부호만으로는 크기를 못 본다

    deep = weekly_macd_signal(_wk([-50000.0, -80000.0, -110057.0]))
    assert deep["tone"] == "warn"
    assert "0 아래로" in deep["text"] and "깊어지는 중" in deep["text"]

    up = weekly_macd_signal(_wk([1000.0, 5000.0, 42001.0]))
    assert up["tone"] == "good"
    assert "0 위에서" in up["text"] and "두꺼워지는 중" in up["text"]

    fade = weekly_macd_signal(_wk([42001.0, 30000.0]))
    assert fade["tone"] == "warn"
    assert "0 위지만" in fade["text"] and "얇아지는 중" in fade["text"]


def test_weekly_macd_signal_calls_the_turning_week_this_week():
    """방향이 막 바뀐 첫 주를 '1주째'라고 하면 말이 안 된다 — '이번 주 들어'로 읽는다."""
    from backend.flow.candles import weekly_macd_signal
    s = weekly_macd_signal(_wk([-90000.0, -110057.0, -106590.0]))
    assert "이번 주 들어 얕아지는 중" in s["text"]


def test_weekly_macd_signal_holds_when_sample_is_short():
    """표본 부족이면 판정 보류(None) — 이 리포의 다른 판정들과 같은 계약이다
    (short_signal·credit_signal·size_signal). 프런트는 .sig:empty로 배지를 감춘다."""
    from backend.flow.candles import weekly_macd_signal
    assert weekly_macd_signal([]) is None
    assert weekly_macd_signal(_wk([-104781.0])) is None
    # 워밍업(앞 33봉 osc=None)만 있는 신규 상장도 같다
    assert weekly_macd_signal([{"osc": None}] * 40) is None
    assert weekly_macd_signal([{"osc": None}] * 40 + [{"osc": 1.0}]) is None


def test_weekly_macd_signal_keeps_dollar_scale_readable():
    """미국 티커도 같은 FDR 경로라 주봉이 나온다 — osc가 소수점 단위인데 원화식
    0자리 반올림을 쓰면 전부 '0'이 된다(같은 함정 전례: 감시선 원화 전용 반올림)."""
    from backend.flow.candles import weekly_macd_signal
    assert "-0.83" in weekly_macd_signal(_wk([-1.20, -0.83]))["text"]


def test_get_candles_1w_carries_weekly_signal(monkeypatch):
    """판정은 백엔드가 만든다 — 프런트는 주봉을 한 번 fetch해 문구를 그대로 띄운다."""
    import backend.flow.candles as cd
    bars = [{"t": "2026-08-%02d" % d, "open": 1, "high": 2, "low": 0,
             "close": 1.0, "osc": v}
            for d, v in ((14, -110057.0), (21, -106590.0), (25, -104781.0))]
    monkeypatch.setattr(cd, "_wm_candles", lambda code, tf: bars)
    loop = asyncio.new_event_loop()
    try:
        d = loop.run_until_complete(cd.get_candles("000660", "1w"))
        m = loop.run_until_complete(cd.get_candles("000660", "1mo"))
    finally:
        loop.close()
    assert d["signal"]["tone"] == "info" and "얕아지는 중" in d["signal"]["text"]
    assert m["signal"] is None   # 월봉은 '주봉' 문구를 재활용하지 않는다


# ── 일·주·월봉 KIS 기간별시세(FHKST03010100) — 2026-09-08 실응답 픽스처, FDR 폴백 ──
def _fx(name):
    import json
    from pathlib import Path
    return json.load(open(Path(__file__).parent / "fixtures" / "kis" / f"{name}.json", encoding="utf-8"))


def test_parse_period_candles_real_fixture_ascending():
    from backend.flow.kis import parse_period_candles
    bars = parse_period_candles(_fx("daily_itemchartprice"))
    assert [b["t"] for b in bars] == sorted(b["t"] for b in bars) and bars[0]["t"] == "2026-09-01"
    last = bars[-1]
    assert last["t"] == "2026-09-08" and last["close"] == 1793000 and last["open"] == 1799000
    assert last["high"] == 1889000 and last["low"] == 1777000 and last["vol"] == 4119139
    assert parse_period_candles({"rt_cd": "1"}) == []


def test_kis_bars_pages_backwards_until_enough(monkeypatch):
    import backend.flow.candles as cd
    monkeypatch.setattr(cd, "_KIS_PAGE", 6)     # 픽스처는 6행 — '가득 찬 페이지'의 기준을 맞춘다
    calls = []

    class C:
        async def period_candles(self, code, period, end, start):
            calls.append((period, end, start))
            if len(calls) == 1:
                return _fx("daily_itemchartprice")                      # 09-08 … 09-01
            if len(calls) == 2:
                js = _fx("daily_itemchartprice")
                for i, r in enumerate(js["output2"]):                   # 08-25 … 08-18 로 밀어 두 번째 페이지 흉내
                    r["stck_bsop_date"] = "202608%02d" % (25 - i)
                return js
            return {"rt_cd": "0", "output2": []}
    bars = asyncio.new_event_loop().run_until_complete(cd._kis_bars(C(), "000660", "D", 10))
    assert len(bars) == 12 and [b["t"] for b in bars] == sorted(b["t"] for b in bars)
    assert calls[0][0] == "D" and calls[1][1] == "20260831"           # 다음 페이지 end = 가장 오래된 날짜 − 1일


def test_daily_candles_prefer_kis_and_fall_back_to_fdr(monkeypatch):
    import backend.flow.candles as cd
    from backend.config import settings
    monkeypatch.setattr(settings, "kis_app_key", "k")
    monkeypatch.setattr(settings, "kis_app_secret", "s")
    monkeypatch.setattr(settings, "flow_mode", "")
    cd._daily_cache.clear()
    kis_bars = [_day((dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat(), o=100 + i, c=101 + i)
                for i in range(300)]
    monkeypatch.setattr(cd, "_kis_bars_sync", lambda code, period, want: kis_bars)
    monkeypatch.setattr(cd, "_fdr_daily", lambda code: (_ for _ in ()).throw(AssertionError("FDR 호출됨")))
    out = cd._daily_candles("000660")
    assert len(out) == 120 and out[-1]["close"] == 101 + 299 and out[-1]["ma120"] is not None
    # KIS 실패 → FDR 폴백(키 없는 데모·미국 티커와 같은 경로)
    cd._daily_cache.clear()
    monkeypatch.setattr(cd, "_kis_bars_sync", lambda code, period, want: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(cd, "_fdr_daily", lambda code: kis_bars[:150])
    out = cd._daily_candles("000660")
    assert len(out) == 120 and out[-1]["close"] == 101 + 149
    # 미국 티커는 항상 FDR
    cd._daily_cache.clear()
    monkeypatch.setattr(cd, "_kis_bars_sync", lambda code, period, want: (_ for _ in ()).throw(AssertionError("KIS 호출됨")))
    assert len(cd._daily_candles("NVDA")) == 120
