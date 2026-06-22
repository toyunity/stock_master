from __future__ import annotations

"""Stock Master 웹앱 (FastAPI).

GET / 은 관심종목 일일 리포트를 매 요청마다 새로 렌더해 서빙한다(시세는 캐시,
뉴스는 라이브). 개인 1인용이라 렌더 캐시는 두지 않는다(새로고침=재요청).

아이폰 설치: `python -m backend.cli serve`로 0.0.0.0:8000 바인딩 → 같은 WiFi의
아이폰 사파리에서 http://<맥IP>:8000 접속 → 공유 → '홈 화면에 추가'.
⚠️ http-LAN은 secure context가 아니라 service worker/오프라인/푸시는 불가(https 배포 시 가능).
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response

from backend.config import settings
from backend.cli import build_daily_html
from backend.api import icons

app = FastAPI(title="Stock Master")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = build_daily_html(settings.watchlist, settings.cache_dir,
                            history_days=settings.history_days,
                            with_news=True, pwa=True)
    return HTMLResponse(html)


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
