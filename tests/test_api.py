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
