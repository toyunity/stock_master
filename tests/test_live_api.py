"""/live 페이지 + SSE 스트림 라우트 테스트 (데모 모드)."""
import json

from fastapi.testclient import TestClient

from backend.api.app import app

client = TestClient(app)


def test_live_page_serves_html(monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "kis_app_key", None)
    r = client.get("/live/000660")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "000660" in r.text and "SK하이닉스" in r.text
    assert "EventSource" in r.text          # SSE 연결 코드
    assert "DEMO" in r.text                 # 모드 배지
    assert "투자 유의" in r.text            # §16 고지
    assert "잠정" in r.text                 # 신선도 라벨
    assert "기관 세부" in r.text            # 연기금/투신 등 세부 패널
    assert "개인+기타" in r.text            # 장중 개인 역산(합계 0 원리) 표시
    assert "nextSlot" in r.text             # 다음 잠정치 발표 슬롯 예고
    assert "apple-touch-icon" in r.text     # PWA 헤더 유지


def test_live_page_rejects_bad_code():
    assert client.get("/live/12ab").status_code == 404
    assert client.get("/live/1234567").status_code == 404


def test_sse_stream_first_snapshot(monkeypatch):
    # 무한 SSE는 TestClient(중간 닫기 시 행)·ASGITransport(전체 버퍼링) 모두 부적합 —
    # 라우트의 스트림 제너레이터를 직접 구동해 첫 이벤트를 검증한다.
    # (실제 HTTP 전송은 uvicorn 기동 후 curl로 별도 e2e 검증.)
    import asyncio

    from backend.api.app import live_stream
    from backend.config import settings
    from backend.flow.engine import FlowEngine
    monkeypatch.setattr(settings, "kis_app_key", None)

    async def first_chunk():
        resp = await live_stream("000660")
        assert resp.media_type == "text/event-stream"
        it = resp.body_iterator
        chunk = await it.__anext__()
        await it.aclose()
        await FlowEngine.get("000660").shutdown()
        return chunk

    loop = asyncio.new_event_loop()
    try:
        chunk = loop.run_until_complete(asyncio.wait_for(first_chunk(), 10))
    finally:
        loop.close()
    assert chunk.startswith("data: ") and chunk.endswith("\n\n")
    snap = json.loads(chunk[len("data: "):])
    assert snap["code"] == "000660"
    assert snap["mode"] == "demo"
    for key in ("market", "tape", "program", "estimate", "daily", "status"):
        assert key in snap


def test_sse_stream_rejects_bad_code():
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        from backend.api.app import live_stream
        resp = loop.run_until_complete(live_stream("12ab"))
    finally:
        loop.close()
    assert resp.status_code == 404


def test_dashboard_cards_link_to_live():
    from backend.report.dashboard import render_dashboard
    stock = {"code": "005930", "name": "삼성전자", "action": "hold",
             "action_ko": "관망", "confidence": 3, "advice": False,
             "reasons": [], "backtest": None, "close": 278000.0, "change": 0.18,
             "news": [], "disclosures": [], "candles": []}
    html = render_dashboard([stock], [], "2026-07-10", pwa=True)
    assert "/live/" in html  # 카드 종목명 → 실시간 수급 화면 딥링크
