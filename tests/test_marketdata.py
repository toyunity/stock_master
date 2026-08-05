"""대시보드 시장 컨텍스트 조립(marketdata) + 라우트 스모크 — 네트워크 없이 가짜 클라이언트."""
import asyncio
import time

import pandas as pd
import pytest


class _FakeC:
    def __init__(self):
        self.idx_calls = 0
        self.fun_calls = []

    async def index(self, iscd="0001"):
        self.idx_calls += 1
        return {"price": 6820.6, "rate": -6.37} if iscd == "0001" else {"price": 791.8, "rate": -4.53}

    async def fundamentals(self, code):
        self.fun_calls.append(code)
        return None if code == "BAD" else {"per": 10.0, "w52_pos": 58.2}


def _reset_fut_cache(md):
    """futures 칩별(k200/nq) 캐시 슬롯을 모두 콜드 상태로 되돌린다 — 두 헬퍼(_reset/_reset_fut)가
    공유해 한쪽만 고쳐서 다른 쪽이 캐시를 흘리는 일을 막는다."""
    for slot in md._fut_cache.values():
        slot["ts"], slot["data"] = 0.0, None


def _reset(md):
    md._idx_cache["ts"], md._idx_cache["data"] = 0.0, None
    md._fun_cache.clear()
    _reset_fut_cache(md)


def test_get_indices_assembles_and_caches(monkeypatch):
    from backend.api import marketdata as md
    _reset(md)
    c = _FakeC()
    d1 = asyncio.run(md.get_indices(client=c))
    assert d1 == {"kospi": {"price": 6820.6, "rate": -6.37},
                  "kosdaq": {"price": 791.8, "rate": -4.53}}
    assert c.idx_calls == 2                       # 코스피+코스닥 1회씩
    asyncio.run(md.get_indices(client=c))          # 30초 캐시 → 재호출 없음
    assert c.idx_calls == 2


def test_get_fundamentals_maps_skips_failure_and_caches(monkeypatch):
    from backend.api import marketdata as md
    _reset(md)
    c = _FakeC()
    d = asyncio.run(md.get_fundamentals(["A", "BAD"], client=c))
    assert d == {"A": {"per": 10.0, "w52_pos": 58.2}}   # BAD(None)은 생략
    assert sorted(c.fun_calls) == ["A", "BAD"]
    asyncio.run(md.get_fundamentals(["A", "BAD"], client=c))   # 캐시 → 재호출 없음
    assert sorted(c.fun_calls) == ["A", "BAD"]


def test_get_top_view_joins_names_and_caches():
    from backend.api import marketdata as md
    md._topview_cache["ts"], md._topview_cache["data"] = 0.0, None

    class C:
        def __init__(self):
            self.calls = 0
        async def top_view(self):
            self.calls += 1
            return ["005930", "000660"]

    c = C()
    d = asyncio.run(md.get_top_view(client=c))
    assert [x["code"] for x in d] == ["005930", "000660"]
    assert all(x.get("name") for x in d)               # 이름 조인(universe/하드코딩 폴백)
    asyncio.run(md.get_top_view(client=c))             # 60초 캐시
    assert c.calls == 1


def test_get_outlook_assembles_and_caches(monkeypatch):
    from backend.api import marketdata as md
    md._outlook_cache.clear()

    async def fake_signals(code, client):
        return {"session": "us_closed", "is_semi": True,
                "us": {"sox_rate": 2.1, "nasdaq_rate": 1.0, "us_open": False},
                "adr": {"overnight_rate": 2.0}, "flow": {"frgn_net": 1, "orgn_net": 1},
                "momentum": {"rate": 1.0, "overheated": False}}
    monkeypatch.setattr(md, "_gather_signals", fake_signals)

    class C:
        pass
    c = C()
    o = asyncio.run(md.get_outlook("000660", client=c))
    assert o["direction"] == "up" and o["reasons"]
    o2 = asyncio.run(md.get_outlook("000660", client=c))      # 60초 캐시
    assert o2 is o


def test_get_asking_caches():
    from backend.api import marketdata as md
    md._ask_cache.clear()

    class C:
        def __init__(self):
            self.calls = 0
        async def asking_price(self, code):
            self.calls += 1
            return {"total_ask": 61953, "total_bid": 48666, "bid_ratio": 44.0,
                    "asks": [], "bids": []}

    c = C()
    a = asyncio.run(md.get_asking("000660", client=c))
    assert a["bid_ratio"] == 44.0 and a["total_ask"] == 61953
    asyncio.run(md.get_asking("000660", client=c))     # 2초 캐시 → 재호출 없음
    assert c.calls == 1


def test_no_client_returns_empty(monkeypatch):
    """키 없음(_client None) → 지수 None·밸류 {}. 네트워크 미접촉."""
    from backend.config import settings
    from backend.api import marketdata as md
    _reset(md)
    monkeypatch.setattr(settings, "kis_app_key", None)          # 실 .env 키로 새는 것 차단
    assert asyncio.run(md.get_indices(client=None)) is None
    assert asyncio.run(md.get_fundamentals(["A"], client=None)) == {}


def test_routes_smoke_without_key(tmp_path, monkeypatch):
    """키 없으면 /api/market={}, /api/fundamentals={} (200) — 대시보드가 조용히 생략."""
    from fastapi.testclient import TestClient
    from backend.config import Settings, settings as gs
    from backend.api.app import create_app
    from backend.api import marketdata as md
    _reset(md)
    monkeypatch.setattr(gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(gs, "kis_app_key", None)
    monkeypatch.setattr(gs, "default_account", "m@x.com")
    s = Settings(cache_dir=str(tmp_path), flow_mode="demo", default_account="m@x.com",
                 kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    c = TestClient(create_app(s))
    assert c.get("/api/market").status_code == 200 and c.get("/api/market").json() == {}
    assert c.get("/api/fundamentals").status_code == 200 and c.get("/api/fundamentals").json() == {}
    assert c.get("/api/futures").status_code == 200 and c.get("/api/futures").json() == {}
    # 기업 체력: 키 없으면 {} (200) — /live가 섹션을 숨김. 코드 형식은 여전히 검증
    assert c.get("/api/financials/000660").status_code == 200
    assert c.get("/api/financials/000660").json() == {}
    assert c.get("/api/financials/00066").status_code == 404      # 6자리 아님
    assert c.get("/api/financials/abcdef").status_code == 404


class _FakeFut:
    """선물 전광판만 답하는 가짜 클라이언트 — cls_code=""(정규/대형) 실측 shape(A01609/F 202609)."""
    def __init__(self):
        self.calls = 0

    async def futures_board(self, cls_code):
        self.calls += 1
        return [{"code": "A01609", "name": "F 202609", "price": 885.25,
                 "rate": -1.49, "sign": "down", "volume": 141272},
                {"code": "A01612", "name": "F 202612", "price": 889.0,
                 "rate": -1.40, "sign": "down", "volume": 312}]


def _reset_fut(md):
    _reset_fut_cache(md)


def _nq_df(closes):
    """FDR NQ=F 응답 모양의 가짜 DataFrame — Close 컬럼만 있으면 _nq_quote가 충분하다."""
    return pd.DataFrame({"Close": closes})


def _nq_fail(start):
    """나스닥 레그를 결정적으로 실패시키는 스텁 — K200 전용 테스트에 fetch로 넘겨,
    fetch 인자를 빼먹었을 때 실제 FinanceDataReader 네트워크 호출로 새는 것을 막는다."""
    raise RuntimeError("나스닥 fetch 스텁 미지정(K200 전용 테스트)")


def test_get_futures_picks_front_month_and_labels_day_session():
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST
    _reset_fut(md)
    c = _FakeFut()
    d = asyncio.run(md.get_futures(client=c, fetch=_nq_fail,
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["k200"]["code"] == "A01609"           # 거래량 최다
    assert d["k200"]["price"] == 885.25
    assert d["k200"]["label"] == "K200선물"
    assert d["k200"]["session"] == "day"
    assert d["k200"]["closed"] is False            # day 세션엔 마감 배지 없음


def test_get_futures_labels_night_session_and_caches():
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST
    _reset_fut(md)
    c = _FakeFut()
    night = dt.datetime(2026, 7, 30, 21, 0, tzinfo=KST)
    d = asyncio.run(md.get_futures(client=c, fetch=_nq_fail, now=night))
    assert d["k200"]["label"] == "야간선물" and d["k200"]["session"] == "night"
    assert d["k200"]["closed"] is False             # night도 라이브 세션 — 마감 아님
    assert c.calls == 1
    asyncio.run(md.get_futures(client=c, fetch=_nq_fail, now=night))   # 30초 캐시 → 재호출 없음
    assert c.calls == 1


def test_get_futures_marks_closed_during_gap_and_closed_sessions():
    """gap(15:45~18:00)·closed(주말 등) 세션엔 K200 칩에 closed:True(마감 배지)가 얹힌다 —
    직전 종가가 라이브 가격처럼 보이면 안 된다는 리뷰 확정 규칙."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    _reset_fut(md)
    c = _FakeFut()
    gap = dt.datetime(2026, 7, 30, 16, 0, tzinfo=KST)          # 목요일 15:45~18:00
    d = asyncio.run(md.get_futures(client=c, fetch=_nq_fail, now=gap))
    assert d["k200"]["closed"] is True and "stale" not in d["k200"]   # 정상 조회 성공 + 마감 표시

    md._fut_cache["k200"]["ts"] = 0.0                           # TTL 만료시켜 세션 재판정 강제
    weekend = dt.datetime(2026, 8, 1, 10, 0, tzinfo=KST)        # 토요일 = closed
    d2 = asyncio.run(md.get_futures(client=c, fetch=_nq_fail, now=weekend))
    assert d2["k200"]["closed"] is True


def test_get_futures_keeps_last_value_on_failure():
    """K200 조회 실패(raise)는 직전 성공값을 유지하고 stale:True(지연 배지)를 얹는다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _Boom(_FakeFut):
        async def futures_board(self, cls_code):
            raise RuntimeError("KIS 500")

    _reset_fut(md)
    md._fut_cache["k200"]["ts"], md._fut_cache["k200"]["data"] = 0.0, {"price": 1.0}
    d = asyncio.run(md.get_futures(client=_Boom(), fetch=_nq_fail,
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["k200"]["price"] == 1.0            # 직전값 유지(칩이 사라지지 않음)
    assert d["k200"]["stale"] is True            # 갱신 실패 표시(지연 배지)
    assert "nq" not in d                         # nq도 콜드 상태로 실패(fetch 스텁이 raise)


def test_get_futures_stale_fallback_relabels_across_session_boundary():
    """실패 폴백은 TTL과 달리 원인이 계속되는 한 무기한 이어질 수 있다 — 주간에 캐시된 값을
    그대로 얼려 야간에 서빙하면 '주간선물' 라벨이 야간 세션에 붙는 회귀가 난다(어드바이저
    리뷰 확정). 폴백에서도 session/label을 현재 세션 기준으로 다시 매긴다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _Boom(_FakeFut):
        async def futures_board(self, cls_code):
            raise RuntimeError("KIS 500")

    _reset_fut(md)
    md._fut_cache["k200"]["ts"], md._fut_cache["k200"]["data"] = 0.0, {
        "code": "A01609", "price": 340.5, "session": "day", "label": "K200선물"}
    night = dt.datetime(2026, 7, 30, 21, 0, tzinfo=KST)
    d = asyncio.run(md.get_futures(client=_Boom(), fetch=_nq_fail, now=night))
    assert d["k200"]["label"] == "야간선물" and d["k200"]["session"] == "night"
    assert d["k200"]["price"] == 340.5 and d["k200"]["stale"] is True


def test_get_futures_includes_nasdaq_futures_chip():
    """QQQ ETF 프록시를 걷어내고 FinanceDataReader NQ=F(나스닥100 선물)로 교체한 경로 —
    fetch 훅으로 실제 FDR 호출 없이 주입한다. $ 접두 없음(선물은 지수 포인트 표기)."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    calls = []

    def fetch(start):
        calls.append(start)
        return _nq_df([28237.75, 28404.25])

    _reset_fut(md)
    c = _FakeFut()
    d = asyncio.run(md.get_futures(client=c, fetch=fetch,
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert calls, "fetch가 호출되지 않았다"
    rate = (28404.25 - 28237.75) / 28237.75 * 100
    assert d["nq"] == {"label": "나스닥 선물", "price": 28404.25, "rate": rate}
    assert "currency" not in d["nq"]          # $ 접두 제거 — fxchip()은 currency=='USD'일 때만 붙인다


def test_get_futures_nasdaq_skips_nan_hole_from_fdr():
    """FDR이 실제로 내보내는 결측(all-NaN) 행 — 휴장이 아닌 거래일에도 나온다(실측).
    NaN 행을 현재가로 오채택하지 않고 건너뛴다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    def fetch(start):
        return _nq_df([28317.0, float("nan"), 28930.0])

    _reset_fut(md)
    d = asyncio.run(md.get_futures(client=_FakeFut(), fetch=fetch,
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["nq"]["price"] == 28930.0
    assert d["nq"]["rate"] == pytest.approx((28930.0 - 28317.0) / 28317.0 * 100)


def test_get_futures_nasdaq_rate_none_when_no_previous_valid_close():
    """유효 종가가 현재가 하나뿐이면(예: 첫 조회, 나머지 전부 NaN) rate:None — 0.00%로
    꾸며내지 않는다. fxchip()이 이를 대시로 렌더한다(dashboard.py, node 실행검증은
    test_dashboard.py에 있음 — 여기선 marketdata가 실제로 None을 넘기는지만 본다)."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    def fetch(start):
        return _nq_df([float("nan"), float("nan"), 28930.0])

    _reset_fut(md)
    d = asyncio.run(md.get_futures(client=_FakeFut(), fetch=fetch,
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["nq"]["price"] == 28930.0
    assert d["nq"]["rate"] is None


def test_get_futures_nasdaq_failure_keeps_k200_chip():
    """나스닥(NQ=F) 조회 실패는 그 칩만 죽는다 — K200 칩은 항상 살아남는다(콜드 상태의 nq)."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    def boom(start):
        raise RuntimeError("FDR 네트워크 오류")

    _reset_fut(md)
    d = asyncio.run(md.get_futures(client=_FakeFut(), fetch=boom,
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["k200"]["code"] == "A01609"
    assert d["k200"]["price"] == 885.25
    assert "nq" not in d


def test_get_futures_k200_failure_does_not_block_nq_chip():
    """CRITICAL(리뷰) — K200 전광판이 raise해도 나스닥(NQ=F) 칩은 항상 시도된다.
    이전엔 두 early-return이 _nq_quote 호출 자체를 막아, 콜드 캐시 상태에서(예: 주말 재기동
    직후) K200이 실패하면 나스닥까지 같이 죽었다(/api/futures가 {} 통째 반환)."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _C:
        async def futures_board(self, cls_code):
            raise RuntimeError("KIS 500")

    def fetch(start):
        return _nq_df([28237.75, 28404.25])

    _reset_fut(md)
    md._fut_cache["k200"]["ts"], md._fut_cache["k200"]["data"] = 0.0, {"code": "A01609", "price": 1.0}
    d = asyncio.run(md.get_futures(client=_C(), fetch=fetch,
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["nq"]["price"] == 28404.25                                # K200 실패와 무관하게 산다
    assert d["k200"]["price"] == 1.0 and d["k200"]["stale"] is True    # K200은 직전값 + 지연 배지


def test_get_futures_front_month_none_does_not_block_nq_chip():
    """전광판 응답에 행은 있어도 전부 미체결(price=0)이면 pick_front_month가 None을 반환한다 —
    이 갈래가 이전엔 테스트가 없었다(리뷰가 지목한 미검증 분기). 이때도 나스닥은 살아야 한다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _C:
        async def futures_board(self, cls_code):
            return [{"code": "A01609", "name": "F 202609", "price": 0.0,
                     "rate": 0.0, "sign": "", "volume": 0}]

    def fetch(start):
        return _nq_df([28237.75, 28404.25])

    _reset_fut(md)
    d = asyncio.run(md.get_futures(client=_C(), fetch=fetch,
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert "k200" not in d               # 콜드 + 쓸 행 없음 → 보여줄 게 없다(꾸며낼 값 없음)
    assert d["nq"]["price"] == 28404.25


def test_get_futures_nq_failure_after_good_value_keeps_cache_and_marks_stale():
    """나스닥이 한 번 성공한 뒤 실패하면 직전값 + stale:True(지연 배지)를 남긴다 — 캐시 히트로
    재시도조차 안 일어나면 이 테스트는 아무것도 검증하지 못하므로 ts를 강제로 만료시킨다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    def good(start):
        return _nq_df([28237.75, 28404.25])

    def boom(start):
        raise RuntimeError("FDR 네트워크 오류")

    _reset_fut(md)
    now = dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)
    d1 = asyncio.run(md.get_futures(client=_FakeFut(), fetch=good, now=now))
    assert d1["nq"]["price"] == 28404.25 and "stale" not in d1["nq"]

    md._fut_cache["nq"]["ts"] = 0.0            # TTL 캐시 히트를 피해 실제로 재시도시킨다
    d2 = asyncio.run(md.get_futures(client=_FakeFut(), fetch=boom, now=now))
    rate = (28404.25 - 28237.75) / 28237.75 * 100
    assert d2["nq"] == {"label": "나스닥 선물", "price": 28404.25, "rate": rate, "stale": True}
    assert d2["k200"]["code"] == "A01609" and "stale" not in d2["k200"]   # K200은 여전히 라이브


def test_get_futures_both_cold_and_failing_returns_empty():
    """K200·나스닥 둘 다 콜드 상태로 실패하면 빈 dict — 보여줄 값 자체가 없다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _Boom:
        async def futures_board(self, cls_code):
            raise RuntimeError("KIS 500")

    def boom(start):
        raise RuntimeError("FDR 네트워크 오류")

    _reset_fut(md)
    d = asyncio.run(md.get_futures(client=_Boom(), fetch=boom,
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d == {}


def test_get_futures_nasdaq_uses_short_ttl_regardless_of_korean_session():
    """나스닥(NQ=F)은 한국 세션에 묶인 ttl(비활성 300초)이 아니라 항상 30초로 갱신한다 —
    나스닥 선물은 거의 24시간 움직이므로 한국 장 마감/휴장과 무관하다. K200은 그대로
    세션별 ttl(이 테스트의 토요일=closed → 300초)을 따른다 — 둘의 TTL이 분리돼 있는지가
    핵심이므로 같은 캐시 나이(60초 = 30초보다 늙었지만 300초보다는 젊음)에서 나스닥만
    재조회되고 K200은 캐시를 그대로 쓰는지로 판별한다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    calls = []

    def fetch(start):
        calls.append(start)
        return _nq_df([28237.75, 28404.25])

    _reset_fut(md)
    weekend = dt.datetime(2026, 8, 1, 10, 0, tzinfo=KST)   # 토요일 = K200 세션 closed → ttl=300s
    c = _FakeFut()
    d1 = asyncio.run(md.get_futures(client=c, fetch=fetch, now=weekend))
    assert d1["k200"]["closed"] is True
    assert len(calls) == 1 and c.calls == 1

    age = 60.0   # 30초(나스닥 ttl)보다 늙었지만 300초(K200 idle ttl)보다는 젊다
    md._fut_cache["nq"]["ts"] = time.time() - age
    md._fut_cache["k200"]["ts"] = time.time() - age
    d2 = asyncio.run(md.get_futures(client=c, fetch=fetch, now=weekend))
    assert len(calls) == 2               # 나스닥은 30초 TTL을 넘겨 재조회됐다
    assert c.calls == 1                  # K200은 300초 TTL 안이라 전광판을 다시 부르지 않았다
    assert d2["nq"]["price"] == 28404.25
    assert d2["k200"]["price"] == 885.25


# ── 기업 체력(밸류 + 재무) — /live 차트 위 접힘 패널 ──

def test_get_stock_detail_assembles_and_caches():
    from backend.api import marketdata as md
    md._detail_cache.clear()

    class C:
        def __init__(self):
            self.calls = 0
        async def fundamentals(self, code):
            self.calls += 1
            return {"per": 31.24, "w52_pos": 58.2}
        async def financials(self, code):
            return [{"period": "2026-03", "roe": 61.16, "debt": 35.56}] * 6

    c = C()
    d = asyncio.run(md.get_stock_detail("000660", client=c))
    assert d["valuation"] == {"per": 31.24, "w52_pos": 58.2}
    assert len(d["financials"]) == 4 and d["financials"][0]["roe"] == 61.16   # 최근 4분기로 컷
    asyncio.run(md.get_stock_detail("000660", client=c))                       # 캐시
    assert c.calls == 1


def test_get_stock_detail_includes_explains_and_concepts():
    """숫자와 함께 값 인식형 쉬운말·개념 설명이 붙는다 — 순수, 네트워크 없음."""
    from backend.api import marketdata as md
    md._detail_cache.clear()

    class C:
        async def fundamentals(self, code):
            return {"per": 31.24, "pbr": 10.55, "w52_pos": 58.0}
        async def financials(self, code):
            return [{"period": "2026-03", "roe": 61.0, "debt": 36.0}]
    d = asyncio.run(md.get_stock_detail("000660", client=C()))
    assert "비싼 편" in d["explains"]["per"]
    assert "잘 버는" in d["explains"]["roe"]
    assert "적은 편" in d["explains"]["debt"]
    assert d["concepts"]["per"]["title"] and d["concepts"]["debt"]["body"]
    # 제거된 섹션의 잔재(오늘현황·내일예상·초보가이드·장단계)를 다시 끌고 오지 않는다
    assert set(d) == {"valuation", "financials", "explains", "concepts"}


def test_get_stock_detail_survives_failure_with_last_good():
    """조회 실패 시 직전 성공값 유지, 첫 조회부터 실패면 빈 dict(패널이 숨음)."""
    from backend.api import marketdata as md
    md._detail_cache.clear()

    class Boom:
        async def fundamentals(self, code):
            raise RuntimeError("KIS down")
        async def financials(self, code):
            return []
    assert asyncio.run(md.get_stock_detail("000660", client=Boom())) == {}

    class OK:
        async def fundamentals(self, code):
            return {"per": 12.0}
        async def financials(self, code):
            return [{"period": "2026-03", "roe": 8.0, "debt": 40.0}]
    good = asyncio.run(md.get_stock_detail("000660", client=OK()))
    md._detail_cache["000660"] = (0.0, good)          # TTL 만료 강제
    assert asyncio.run(md.get_stock_detail("000660", client=Boom())) == good


def test_get_stock_detail_omits_missing_metrics():
    """재무·밸류가 비면 explains 키가 아예 없다 — 모르는 값을 0으로 지어내지 않는다."""
    from backend.api import marketdata as md
    md._detail_cache.clear()

    class Empty:
        async def fundamentals(self, code):
            return None
        async def financials(self, code):
            return []
    d = asyncio.run(md.get_stock_detail("000660", client=Empty()))
    assert d["valuation"] is None and d["financials"] == []
    assert d["explains"] == {}


# ── T9 야간선물 실시간(H0MFCNT0) ──────────────────────────────────────────
class _FakeBus:
    """wsbus.WsSession 대역 — 등록/해제만 기록한다(소켓 미접촉)."""

    def __init__(self):
        self.started, self.regs, self.unregs = 0, [], []

    def start(self):
        self.started += 1

    async def register(self, tr_id, tr_key, handler):
        self.regs.append((tr_id, tr_key))

    async def unregister(self, tr_id, tr_key, handler):
        self.unregs.append((tr_id, tr_key))


def _install_bus(monkeypatch, md, bus):
    from backend.flow import wsbus
    monkeypatch.setattr(wsbus.WsSession, "get", classmethod(lambda cls, c: bus))
    md._night_reg = None
    md._night_tick = None


def _night(h=21):
    import datetime as dt
    from backend.flow.kst import KST
    return dt.datetime(2026, 7, 30, h, 0, tzinfo=KST)


def test_get_futures_prefers_ws_tick_at_night(monkeypatch):
    """야간엔 실시간 틱이 있으면 그것을, 없으면 REST 값을 쓴다."""
    from backend.api import marketdata as md
    _reset_fut(md)
    _install_bus(monkeypatch, md, _FakeBus())
    md._night_tick = {"price": 883.4, "rate": -0.2}
    d = asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail, now=_night()))
    assert d["k200"]["price"] == 883.4 and d["k200"]["rate"] == -0.2

    _reset_fut(md)
    _install_bus(monkeypatch, md, _FakeBus())
    d = asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail, now=_night()))
    assert d["k200"]["price"] == 885.25          # REST 폴백


def test_get_futures_registers_night_ws_only_at_night(monkeypatch):
    """주간엔 H0MFCNT0을 등록하지 않는다 — 야간 세션에만 존재하는 시세다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST
    _reset_fut(md)
    bus = _FakeBus()
    _install_bus(monkeypatch, md, bus)
    asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail,
                               now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert bus.regs == []

    _reset_fut(md)
    asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail, now=_night()))
    assert bus.regs == [("H0MFCNT0", "A01609")]     # 최근월물 코드로 등록
    assert bus.started == 1


def test_night_ws_registration_is_idempotent_across_polls(monkeypatch):
    """대시보드가 30초마다 부른다 — 매번 다시 등록하면 안 된다."""
    from backend.api import marketdata as md
    _reset_fut(md)
    bus = _FakeBus()
    _install_bus(monkeypatch, md, bus)
    for _ in range(3):
        md._fut_cache["k200"]["ts"] = 0.0            # TTL 만료시켜 매번 재조회
        asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail, now=_night()))
    assert bus.regs == [("H0MFCNT0", "A01609")] and bus.unregs == []


def test_night_ws_reregisters_when_the_contract_rolls(monkeypatch):
    """월물이 바뀌면 이전 등록을 해제하고 새 코드로 건다 — 안 그러면 만기 지난
    종목을 계속 듣고 화면은 영영 안 움직인다."""
    from backend.api import marketdata as md
    _reset_fut(md)
    bus = _FakeBus()
    _install_bus(monkeypatch, md, bus)
    asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail, now=_night()))

    class _Rolled(_FakeFut):
        async def futures_board(self, cls_code):
            rows = await super().futures_board(cls_code)
            for r in rows:
                r["code"] = "A01612" if r["code"] == "A01609" else r["code"]
            return rows

    _reset_fut(md)
    md._night_tick = None
    asyncio.run(md.get_futures(client=_Rolled(), fetch=_nq_fail, now=_night()))
    assert bus.unregs == [("H0MFCNT0", "A01609")]
    assert bus.regs[-1] == ("H0MFCNT0", "A01612")


def test_on_night_tick_stores_only_parseable_records():
    """핑퐁·잘린 프레임이 최신 틱을 0으로 덮어쓰면 안 된다."""
    from backend.api import marketdata as md
    md._night_tick = None
    md._on_night_tick(["101W09", "210131"])          # 짧은 레코드
    assert md._night_tick is None
    md._on_night_tick(["101W09", "210131", "-1.80", "5", "-0.20", "883.40",
                       "885.00", "886.10", "882.05", "3", "141272", "1250000000",
                       "884.10", "-0.70", "-0.08", "0", "0", "0", "170400"])
    assert md._night_tick == {"price": 883.40, "rate": -0.20}
    md._on_night_tick(["101W09", "210131"])          # 다시 짧은 레코드
    assert md._night_tick == {"price": 883.40, "rate": -0.20}   # 직전값 유지
    md._night_tick = None


def test_night_ws_failure_does_not_kill_the_chip(monkeypatch):
    """웹소켓 등록이 실패해도 칩은 REST 값으로 살아야 한다 — 실시간은 덤이다."""
    from backend.api import marketdata as md
    _reset_fut(md)

    class _BoomBus(_FakeBus):
        async def register(self, tr_id, tr_key, handler):
            raise RuntimeError("승인키 만료")

    _install_bus(monkeypatch, md, _BoomBus())
    d = asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail, now=_night()))
    assert d["k200"]["price"] == 885.25 and d["k200"]["label"] == "야간선물"


def test_night_tick_applies_on_cache_hit_too(monkeypatch):
    """TTL 캐시 히트에도 최신 틱을 얹어야 한다.

    안 그러면 실시간을 달아 놓고도 화면은 30초에 한 번만 움직인다 — 웹소켓을
    등록한 이유가 절반 사라진다. 세션·마감 배지를 캐시 히트마다 재판정하는
    것과 같은 이유다."""
    from backend.api import marketdata as md
    _reset_fut(md)
    _install_bus(monkeypatch, md, _FakeBus())
    asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail, now=_night()))

    md._night_tick = {"price": 901.55, "rate": 1.75}     # 캐시 만료 없이 틱만 도착
    d = asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail, now=_night()))
    assert d["k200"]["price"] == 901.55 and d["k200"]["rate"] == 1.75
    md._night_tick = None


def test_night_registration_recovers_within_a_poll_after_session_flip(monkeypatch):
    """gap(15:45~18:00) 캐시가 살아 있는 채로 18:00을 넘어도 등록이 늦지 않아야 한다.

    gap의 TTL은 300초라, 캐시 히트 경로에서 등록을 안 하면 야간 개장 후 최대
    5분 동안 실시간이 안 붙는다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST
    _reset_fut(md)
    bus = _FakeBus()
    _install_bus(monkeypatch, md, bus)
    asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail,
                               now=dt.datetime(2026, 7, 30, 17, 0, tzinfo=KST)))
    assert bus.regs == []                                 # gap엔 등록 안 함

    d = asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail, now=_night()))
    assert d["k200"]["label"] == "야간선물"
    assert bus.regs == [("H0MFCNT0", "A01609")]           # 캐시 히트여도 곧바로 등록


def test_cached_chip_relabels_across_session_boundary():
    """캐시 히트에도 라벨·세션을 재판정한다(실시간 여부와 무관한 회귀).

    gap의 TTL은 300초라 17:58에 담긴 캐시가 18:01에 그대로 나온다 — 그때
    '야간선물'이어야 할 라벨이 'K200선물'로 남아 있으면 사용자는 지금 보는 값이
    주간 종가인지 야간 시세인지 알 수 없다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST
    _reset_fut(md)
    md._fut_cache["k200"]["ts"] = time.time()            # 갓 담긴 캐시
    md._fut_cache["k200"]["data"] = {"code": "A01609", "name": "F 202609",
                                     "price": 885.25, "rate": -1.4,
                                     "session": "gap", "label": "K200선물"}
    d = asyncio.run(md.get_futures(client=_FakeFut(), fetch=_nq_fail,
                                   now=dt.datetime(2026, 7, 30, 12, 0, tzinfo=KST)))
    assert d["k200"]["label"] == "K200선물" and d["k200"]["session"] == "day"
    assert d["k200"]["closed"] is False
