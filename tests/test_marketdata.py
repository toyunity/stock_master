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
