from __future__ import annotations

"""Stock Master 웹앱 (FastAPI).

GET / 은 관심종목 일일 리포트를 매 요청마다 새로 렌더해 서빙한다(시세는 캐시,
뉴스는 라이브). 개인 1인용이라 렌더 캐시는 두지 않는다(새로고침=재요청).

아이폰 설치: `python -m backend.cli serve`로 0.0.0.0:8000 바인딩 → 같은 WiFi의
아이폰 사파리에서 http://<맥IP>:8000 접속 → 공유 → '홈 화면에 추가'.
⚠️ http-LAN은 secure context가 아니라 service worker/오프라인/푸시는 불가(https 배포 시 가능).
"""

import json
import re

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from backend.config import settings
from backend.cli import build_dashboard
from backend.api import icons
from backend.flow import candles
from backend.flow import scanner as flow_scanner
from backend.flow.engine import FlowEngine
from backend.report.live_page import render_live_page
from backend.report.scanner_page import render_scanner_page

app = FastAPI(title="Stock Master")

_CODE_RE = re.compile(r"^\d{6}$")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = build_dashboard(settings.watchlist, settings.cache_dir,
                           history_days=settings.history_days,
                           with_news=True, pwa=True)
    return HTMLResponse(html)


@app.get("/live/{code}", response_class=HTMLResponse)
def live(code: str):
    """실시간 수급 화면 — KIS 키 있으면 LIVE, 없으면 DEMO(시뮬레이션)."""
    if not _CODE_RE.match(code):
        return HTMLResponse("종목 코드는 6자리 숫자입니다", status_code=404)
    eng = FlowEngine.get(code)
    return HTMLResponse(render_live_page(code, eng.state.name, eng.mode))


@app.get("/api/live/{code}/stream")
async def live_stream(code: str):
    """SSE — 1초마다 수급 전체 스냅샷(JSON)을 push."""
    if not _CODE_RE.match(code):
        return Response(status_code=404)
    eng = FlowEngine.get(code)

    async def gen():
        async for snap in eng.subscribe():
            yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/candles/{code}")
async def candles_api(code: str, tf: str = "5m"):
    """봉 차트 — tf: 1m/5m/15m(당일 분봉, LIVE는 KIS·데모는 합성) | 1d(일봉 120)."""
    if not _CODE_RE.match(code):
        return Response(status_code=404)
    if tf not in candles.TIMEFRAMES:
        return JSONResponse({"error": f"tf는 {'/'.join(candles.TIMEFRAMES)} 중 하나"},
                            status_code=400)
    return JSONResponse(await candles.get_candles(code, tf))


@app.get("/scanner", response_class=HTMLResponse)
def scanner_page():
    """수급 스캐너 — 오늘 수급 특이 종목(외인/기관 가집계 × 거래대금/급등 교차)."""
    return HTMLResponse(render_scanner_page())


@app.get("/api/scanner")
async def scanner_api():
    if not (settings.kis_app_key and settings.kis_app_secret):
        return JSONResponse(
            {"error": "스캐너는 KIS 키가 필요합니다 (.env에 SM_KIS_APP_KEY/SECRET)"},
            status_code=503)
    return JSONResponse(await flow_scanner.fetch_scan())


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/manifest.json")
def manifest():
    return JSONResponse(icons.MANIFEST)


@app.get("/icons/{name}")
def icon(name: str):
    data = icons.get_icon(name)
    if data is None:
        return Response(status_code=404)
    return Response(content=data, media_type="image/png")
