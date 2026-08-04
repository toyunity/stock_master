"""대시보드 시장 컨텍스트 조립(marketdata) + 라우트 스모크 — 네트워크 없이 가짜 클라이언트."""
import asyncio


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


def test_get_stock_read_bundles_outlook_situation_phase(monkeypatch):
    from backend.api import marketdata as md
    md._read_cache.clear()
    md._detail_cache.clear()

    async def fake_signals(code, client):
        return {"is_semi": True, "has_adr": True, "session": "us_closed",
                "us": {"sox_rate": -1.6}, "adr": {"overnight_rate": -0.3},
                "flow": {"frgn_net": -1, "orgn_net": -1},
                "momentum": {"rate": -12.1, "overheated": False}}
    monkeypatch.setattr(md, "_gather_signals", fake_signals)

    class C:
        async def fundamentals(self, code):
            return {"per": 31.0, "w52_pos": 58.0}
        async def financials(self, code):
            return [{"roe": 61.0, "debt": 36.0}]
    r = asyncio.run(md.get_stock_read("000660", client=C()))
    assert r["outlook"]["direction"] == "down"
    assert r["situation"]["sentences"]
    assert r["phase"] in ("장중", "장 종료", "정규장 마감 · 나스닥 DR 거래 중")
    assert r["has_adr"] is True


def test_get_stock_detail_has_concepts_and_has_adr():
    from backend.api import marketdata as md
    md._detail_cache.clear()

    class C:
        async def fundamentals(self, code):
            return {"per": 31.0}
        async def financials(self, code):
            return [{"roe": 61.0, "debt": 36.0}]
    d = asyncio.run(md.get_stock_detail("000660", client=C()))
    assert d["concepts"]["per"]["title"]         # 개념 설명 번들
    assert "has_adr" in d


def test_get_stock_detail_includes_explains():
    """상세에 값 인식형 쉬운말(explains)이 붙는다 — 순수, 네트워크 없음."""
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
    from backend.flow import usquote
    usquote._exch_cache.clear()   # QQQ 거래소 확정 캐시 — 테스트 순서 무관하게 매번 초기화


def test_get_futures_picks_front_month_and_labels_day_session():
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST
    _reset_fut(md)
    c = _FakeFut()
    d = asyncio.run(md.get_futures(client=c, now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
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
    d = asyncio.run(md.get_futures(client=c, now=night))
    assert d["k200"]["label"] == "야간선물" and d["k200"]["session"] == "night"
    assert d["k200"]["closed"] is False             # night도 라이브 세션 — 마감 아님
    assert c.calls == 1
    asyncio.run(md.get_futures(client=c, now=night))   # 30초 캐시 → 재호출 없음
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
    d = asyncio.run(md.get_futures(client=c, now=gap))
    assert d["k200"]["closed"] is True and "stale" not in d["k200"]   # 정상 조회 성공 + 마감 표시

    md._fut_cache["k200"]["ts"] = 0.0                           # TTL 만료시켜 세션 재판정 강제
    weekend = dt.datetime(2026, 8, 1, 10, 0, tzinfo=KST)        # 토요일 = closed
    d2 = asyncio.run(md.get_futures(client=c, now=weekend))
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
    d = asyncio.run(md.get_futures(client=_Boom(),
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["k200"]["price"] == 1.0            # 직전값 유지(칩이 사라지지 않음)
    assert d["k200"]["stale"] is True            # 갱신 실패 표시(지연 배지)
    assert "nq" not in d                         # nq도 콜드 상태로 실패(_Boom엔 _get 없음)


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
    d = asyncio.run(md.get_futures(client=_Boom(), now=night))
    assert d["k200"]["label"] == "야간선물" and d["k200"]["session"] == "night"
    assert d["k200"]["price"] == 340.5 and d["k200"]["stale"] is True


def test_get_futures_includes_nasdaq_qqq_chip():
    """CME 선물 실시간 시세는 계좌에 유료 구독이 필요해(G3 실측 EGW00550) QQQ ETF로 대신한다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _C(_FakeFut):
        def __init__(self):
            super().__init__()
            self.nq_params = None

        async def _get(self, path, tr_id, params):
            # price_us가 예외를 통째로 삼키므로(거래소 순회 실패 흡수) assert를 이 안에 두면
            # 실패가 조용히 None으로 바뀌어 엉뚱한 곳(KeyError 등)에서 터진다 — 밖에서 검증한다.
            self.nq_params = params
            return {"rt_cd": "0", "output": {"last": "487.32", "rate": " 0.42",
                                             "sign": "2", "tvol": "1"}}

    _reset_fut(md)
    c = _C()
    d = asyncio.run(md.get_futures(client=c,
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert c.nq_params["SYMB"] == "QQQ"
    assert d["nq"] == {"label": "나스닥 QQQ", "price": 487.32, "rate": 0.42,
                       "currency": "USD"}


def test_get_futures_nasdaq_rate_none_on_preopen_rollover():
    """sign '0'(미국 프리오픈 일자 롤오버)은 rate=None — 0.42%처럼 꾸며내지 않는다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _C(_FakeFut):
        async def _get(self, path, tr_id, params):
            return {"rt_cd": "0", "output": {"last": "487.32", "rate": " 0.00",
                                             "sign": "0", "tvol": "1"}}

    _reset_fut(md)
    d = asyncio.run(md.get_futures(client=_C(),
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["nq"]["price"] == 487.32
    assert d["nq"]["rate"] is None


def test_get_futures_nasdaq_failure_keeps_k200_chip():
    """나스닥(QQQ) 조회 실패는 그 칩만 죽는다 — K200 칩은 항상 살아남는다(콜드 상태의 nq)."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _Boom(_FakeFut):
        async def _get(self, path, tr_id, params):
            raise RuntimeError("KIS 500")

    _reset_fut(md)
    d = asyncio.run(md.get_futures(client=_Boom(),
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["k200"]["code"] == "A01609"
    assert d["k200"]["price"] == 885.25
    assert "nq" not in d


def test_get_futures_k200_failure_does_not_block_nq_chip():
    """CRITICAL(리뷰) — K200 전광판이 raise해도 나스닥(QQQ) 칩은 항상 시도된다.
    이전엔 두 early-return이 _nq_quote 호출 자체를 막아, 콜드 캐시 상태에서(예: 주말 재기동
    직후) K200이 실패하면 QQQ까지 같이 죽었다(/api/futures가 {} 통째 반환)."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _C:
        async def futures_board(self, cls_code):
            raise RuntimeError("KIS 500")

        async def _get(self, path, tr_id, params):
            return {"rt_cd": "0", "output": {"last": "487.32", "rate": " 0.42",
                                             "sign": "2", "tvol": "1"}}

    _reset_fut(md)
    md._fut_cache["k200"]["ts"], md._fut_cache["k200"]["data"] = 0.0, {"code": "A01609", "price": 1.0}
    d = asyncio.run(md.get_futures(client=_C(),
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["nq"]["price"] == 487.32                                  # K200 실패와 무관하게 산다
    assert d["k200"]["price"] == 1.0 and d["k200"]["stale"] is True    # K200은 직전값 + 지연 배지


def test_get_futures_front_month_none_does_not_block_nq_chip():
    """전광판 응답에 행은 있어도 전부 미체결(price=0)이면 pick_front_month가 None을 반환한다 —
    이 갈래가 이전엔 테스트가 없었다(리뷰가 지목한 미검증 분기). 이때도 QQQ는 살아야 한다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _C:
        async def futures_board(self, cls_code):
            return [{"code": "A01609", "name": "F 202609", "price": 0.0,
                     "rate": 0.0, "sign": "", "volume": 0}]

        async def _get(self, path, tr_id, params):
            return {"rt_cd": "0", "output": {"last": "487.32", "rate": " 0.42",
                                             "sign": "2", "tvol": "1"}}

    _reset_fut(md)
    d = asyncio.run(md.get_futures(client=_C(),
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert "k200" not in d               # 콜드 + 쓸 행 없음 → 보여줄 게 없다(꾸며낼 값 없음)
    assert d["nq"]["price"] == 487.32


def test_get_futures_nq_failure_after_good_value_keeps_cache_and_marks_stale():
    """QQQ가 한 번 성공한 뒤 실패하면 직전값 + stale:True(지연 배지)를 남긴다 — 캐시 히트로
    재시도조차 안 일어나면 이 테스트는 아무것도 검증하지 못하므로 ts를 강제로 만료시킨다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _Good(_FakeFut):
        async def _get(self, path, tr_id, params):
            return {"rt_cd": "0", "output": {"last": "487.32", "rate": " 0.42",
                                             "sign": "2", "tvol": "1"}}

    class _NqBoom(_FakeFut):
        async def _get(self, path, tr_id, params):
            raise RuntimeError("KIS 500")

    _reset_fut(md)
    now = dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)
    d1 = asyncio.run(md.get_futures(client=_Good(), now=now))
    assert d1["nq"]["price"] == 487.32 and "stale" not in d1["nq"]

    md._fut_cache["nq"]["ts"] = 0.0            # TTL 캐시 히트를 피해 실제로 재시도시킨다
    d2 = asyncio.run(md.get_futures(client=_NqBoom(), now=now))
    assert d2["nq"] == {"label": "나스닥 QQQ", "price": 487.32, "rate": 0.42,
                        "currency": "USD", "stale": True}
    assert d2["k200"]["code"] == "A01609" and "stale" not in d2["k200"]   # K200은 여전히 라이브


def test_get_futures_both_cold_and_failing_returns_empty():
    """K200·QQQ 둘 다 콜드 상태로 실패하면 빈 dict — 보여줄 값 자체가 없다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _Boom:
        async def futures_board(self, cls_code):
            raise RuntimeError("KIS 500")

        async def _get(self, path, tr_id, params):
            raise RuntimeError("KIS 500")

    _reset_fut(md)
    d = asyncio.run(md.get_futures(client=_Boom(),
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d == {}
