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


def _reset(md):
    md._idx_cache["ts"], md._idx_cache["data"] = 0.0, None
    md._fun_cache.clear()


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
