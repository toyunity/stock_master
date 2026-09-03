from fastapi.testclient import TestClient

import backend.api.app as appmod
from backend.api.app import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_index_serves_report(monkeypatch):
    # 네트워크/시세 없이 라우트만 검증: build_daily_html을 가짜로 대체
    fake = ("<html><head>"
            "<link rel=\"apple-touch-icon\" href=\"/icons/icon-180.png\">"
            "</head><body>005930 리포트</body></html>")
    monkeypatch.setattr(appmod, "build_dashboard", lambda *a, **k: fake)
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "005930" in r.text
    assert "apple-touch-icon" in r.text  # PWA 설치 태그가 살아 전달됨


def test_manifest_is_valid_json():
    r = client.get("/manifest.json")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Stock Master"
    assert data["display"] == "standalone"
    assert any(i["src"] == "/icons/icon-192.png" for i in data["icons"])


def test_icon_returns_png_bytes():
    r = client.get("/icons/icon-180.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG 시그니처
    assert len(r.content) > 100


def test_icon_unknown_size_404():
    assert client.get("/icons/icon-999.png").status_code == 404


def test_bare_routes_do_not_500(tmp_path, monkeypatch):
    """핸들러를 한 번은 실제로 때린다 — 배선을 안 부르면 미정의 이름도 통과한다.

    2026-08-12 실사고: `/api/usprice`의 `marketdata` 미정의(NameError)가 753개
    테스트를 전부 통과했다. 프런트 fetch를 목킹한 테스트(test_us_page_js.py:61)는
    서버 핸들러를 한 번도 안 부르기 때문이다. 여기 세 라우트가 그 구멍이었다.

    KIS 키를 비워 조회 경로는 곧바로 빠지고(_client()→None) **배선만** 남는다 —
    실 KIS 호출 0, 네트워크 0. usprice는 장외면 :173에서 204로 먼저 빠져나가
    :174에 닿지도 않으므로 us_market_open을 True로 눌러야 재현된다."""
    from backend.config import settings
    from backend.flow import adr
    monkeypatch.setattr(settings, "kis_app_key", "")
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(adr, "us_market_open", lambda *a, **k: True)
    # 정규장이고 키가 없으면 = '줄 게 없다' → 204. != 500만 보면 404(배선 미도달)도
    # 통과해버려 이 테스트가 지키려는 것을 못 지킨다.
    assert client.get("/api/usprice/AAPL").status_code == 204
    assert client.get("/api/outlook").status_code == 200
    assert client.get("/api/topview").status_code == 200


def test_options_route_returns_empty_when_no_board_has_been_collected(tmp_path, monkeypatch):
    """수집된 보드가 없으면 빈 dict — 프론트가 섹션을 통째로 숨긴다(에러 토스트 금지).

    **cache_dir를 격리해야 한다.** 안 하면 개발 머신에 실제로 수집된
    data/cache/options_*.json을 읽어 테스트가 환경에 따라 갈린다(2026-08-05에
    실제로 그랬다). 배치 분리 이후 표시 경로는 KIS 키와 무관하므로, 이 테스트가
    확인하는 것은 '키 없음'이 아니라 '수집본 없음'이다."""
    from fastapi.testclient import TestClient

    from backend.api import marketdata as md
    from backend.api.app import create_app
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "options_enabled", True)
    md._opt_mem.update({"mtime": 0.0, "data": None})
    with TestClient(create_app()) as c:
        r = c.get("/api/options")
    md._opt_mem.update({"mtime": 0.0, "data": None})
    assert r.status_code == 200 and r.json() == {}


def test_usprice_serves_outside_regular_hours_when_toss_is_on(tmp_path, monkeypatch):
    """토스가 있으면 정규장 밖에서도 미국 시세를 준다(데이마켓·프리·애프터).

    2026-09-03 실측: 토스 미국 시세는 실시간이고(조회 대비 최소 4.2초) 한국 낮
    시간대의 데이마켓에도 체결이 흐른다. KIS 경로만 있던 시절의 '정규장 밖은 204'
    게이트를 그대로 두면 마스터가 앱을 실제로 보는 시간대에 값이 안 나온다.
    KIS 클라이언트가 None이어도 나와야 한다 — 토스 단독으로 성립하는 경로다."""
    from backend.config import settings
    from backend.flow import adr, usquote
    monkeypatch.setattr(settings, "kis_app_key", "")
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(adr, "us_market_open", lambda *a, **k: False)

    async def fake_price(client, sym):
        assert client is None, "KIS 키가 없으니 client는 None이어야 한다"
        return {"price": 324.56, "change": -0.12, "currency": "USD",
                "exch": None, "src": "toss"}
    monkeypatch.setattr(usquote, "price_us", fake_price)

    from backend.flow import toss
    monkeypatch.setattr(toss, "get_client", lambda: object())
    r = client.get("/api/usprice/AAPL")
    assert r.status_code == 200 and r.json()["src"] == "toss"

    # 토스가 없으면 기존 게이트 그대로 — 정규장 밖은 204.
    monkeypatch.setattr(toss, "get_client", lambda: None)
    assert client.get("/api/usprice/AAPL").status_code == 204
