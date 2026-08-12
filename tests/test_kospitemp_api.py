"""GET /api/kospi-temp — 라우트 계약."""
import asyncio
import datetime as dt

from fastapi.testclient import TestClient

from backend.api.app import app
from backend.flow import candles
from backend.flow import kospitemp as kt
from backend.flow.kst import KST

ITEM_KEYS = {"key", "label", "value", "unit", "verdict"}


class _Fake:
    def __init__(self, closes):
        self.closes = closes

    async def index_daily(self, iscd, date):
        return {"now": None, "days": [{"d": "20260812", "v": v}
                                      for v in self.closes]}


def test_route_returns_the_full_item_shape(monkeypatch):
    kt._cache["ts"], kt._cache["data"] = 0.0, None
    monkeypatch.setattr(kt.kst, "now",
                        lambda: dt.datetime(2026, 8, 12, 12, 50, tzinfo=KST))
    monkeypatch.setattr(candles, "_get_client",
                        lambda: _Fake([100.0, 95.0, 99.0, 94.0, 98.0, 93.0, 97.0]))
    r = TestClient(app).get("/api/kospi-temp")
    assert r.status_code == 200
    d = r.json()
    assert d["items"], "항목이 하나도 없다"
    for it in d["items"]:
        assert set(it) == ITEM_KEYS, it
        assert it["verdict"], "판정 단어 누락 — 프런트가 지어내면 안 되는 값이다"


def test_route_is_200_with_empty_items_when_the_source_dies(monkeypatch):
    """503으로 끊지 않는다 — 그룹 하나가 빠질 뿐 섹션은 떠야 한다."""
    kt._cache["ts"], kt._cache["data"] = 0.0, None

    def _boom():
        raise RuntimeError("KIS 없음")

    monkeypatch.setattr(candles, "_get_client", _boom)
    r = TestClient(app).get("/api/kospi-temp")
    assert r.status_code == 200 and r.json()["items"] == []
