from __future__ import annotations

"""Stock Master 웹앱 (FastAPI).

GET / 은 관심종목 일일 리포트를 매 요청마다 새로 렌더해 서빙한다(시세는 캐시,
뉴스는 라이브). 개인 1인용이라 렌더 캐시는 두지 않는다(새로고침=재요청).

아이폰 설치: `python -m backend.cli serve`로 0.0.0.0:8000 바인딩 → 같은 WiFi의
아이폰 사파리에서 http://<맥IP>:8000 접속 → 공유 → '홈 화면에 추가'.
⚠️ http-LAN은 secure context가 아니라 service worker/오프라인/푸시는 불가(https 배포 시 가능).

공개 배포(Tailscale Funnel + SM_AUTH_ENABLED=true) 시 create_app이 인증 게이트
(Google OAuth2 + TOTP)를 장착한다 — backend/api/auth.py. 게이트는 순수 ASGI라 SSE를 깨지 않는다.
"""

import json
import re

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from backend.config import settings as _settings
from backend.cli import build_dashboard
from backend.api import icons
from backend.api import auth as _auth
from backend.flow import candles
from backend.flow import scanner as flow_scanner
from backend.flow import semi
from backend.flow.engine import FlowEngine
from backend.report.live_page import render_live_page
from backend.report.scanner_page import render_scanner_page

_CODE_RE = re.compile(r"^\d{6}$")


def _req_email(request, settings):
    """라우트 계정 해석 — 세션 이메일(로그인)이 있으면 그것, 없으면(인증 비활성) default_account.
    request.session 직접 접근 금지(SessionMiddleware 미설치 시 AssertionError) — scope.get으로 방어."""
    from backend.flow.userstore import default_account
    sess = request.scope.get("session") or {}
    return sess.get("email") or default_account()


async def live_stream(code: str):
    """SSE — 1초마다 수급 전체 스냅샷(JSON)을 push. 모듈 레벨(설정 불요)이라
    라우트가 위임하고 테스트가 제너레이터를 직접 구동할 수 있다."""
    if not _CODE_RE.match(code):
        return Response(status_code=404)
    eng = FlowEngine.get(code)

    async def gen():
        async for snap in eng.subscribe():
            yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def create_app(settings=None) -> FastAPI:
    """앱 팩토리 — settings 주입 가능(테스트에서 인증 활성 앱 구성). 기본은 모듈 settings.
    auth_enabled면 인증 게이트를 장착(크리덴셜 없으면 기동 거부, fail-closed)."""
    settings = settings if settings is not None else _settings
    # 위젯 토큰 fail-closed — 약한 토큰(짧은 문자열)이 공개 Funnel의 유일 방어선이
    # 되는 것을 기동 시점에 차단(auth.install의 fail-closed와 같은 철학).
    if settings.widget_token and len(settings.widget_token) < 20:
        raise RuntimeError(
            "SM_WIDGET_TOKEN이 너무 짧습니다(최소 20자) — "
            'python3 -c "import secrets; print(secrets.token_urlsafe(32))" 로 생성하세요')
    app = FastAPI(title="Stock Master")

    @app.on_event("shutdown")
    async def _stop_engines():
        """종료 시 웹소켓을 클로즈 프레임과 함께 정리 — 좀비 세션(KIS 'ALREADY' 거부의
        원인, 실측 2026-07-10)을 남기지 않는다."""
        for eng in list(FlowEngine._registry.values()):
            try:
                await eng.shutdown()
            except Exception:
                pass

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        from backend.flow import userstore
        html = build_dashboard(userstore.get_kr_codes(_req_email(request, settings)),
                               settings.cache_dir, history_days=settings.history_days,
                               with_news=True, pwa=True)
        return HTMLResponse(html)

    @app.get("/live/{code}", response_class=HTMLResponse)
    def live(code: str, request: Request):
        """실시간 수급 화면 — KIS 키 있으면 LIVE, 없으면 DEMO(시뮬레이션)."""
        if not _CODE_RE.match(code):
            return HTMLResponse("종목 코드는 6자리 숫자입니다", status_code=404)
        eng = FlowEngine.get(code)
        return HTMLResponse(render_live_page(code, eng.state.name, eng.mode,
                                             _req_email(request, settings)))

    @app.get("/api/live/{code}/stream")
    async def _live_stream(code: str):
        return await live_stream(code)

    @app.get("/api/candles/{code}")
    async def candles_api(code: str, tf: str = "5m"):
        """봉 차트 — tf: 1m/5m/15m(당일 분봉, LIVE는 KIS·데모는 합성) | 1d(일봉 120)."""
        if not _CODE_RE.match(code):
            return Response(status_code=404)
        if tf not in candles.TIMEFRAMES:
            return JSONResponse({"error": f"tf는 {'/'.join(candles.TIMEFRAMES)} 중 하나"},
                                status_code=400)
        return JSONResponse(await candles.get_candles(code, tf))

    @app.get("/api/watchlist")
    def watchlist_get(request: Request):
        """관심종목 목록(계정별) — items[{code,market,shares,avg,name}]. 이름은 KR=universe, US=티커명.
        US 이름은 임시(semi.US_NAMES) — Task 12의 usquote.us_name으로 교체 예정."""
        from backend.flow import userstore
        from backend.flow.semi import US_NAMES
        from backend.market.universe import get_cached, name_map
        from backend.news.names import resolve_name
        nm = name_map(get_cached())
        email = _req_email(request, settings)
        items = [dict(i, name=(resolve_name(i["code"], nm) if i["market"] == "KR"
                               else US_NAMES.get(i["code"], i["code"])))
                 for i in userstore.get_watchlist(email)]
        return JSONResponse({"items": items})

    @app.post("/api/watchlist")
    async def watchlist_set(request: Request):
        """관심종목 저장(계정별 전체 교체) — body {"items":[{code,market,shares,avg}]}.
        검증 실패 400(사용자 메시지). 구 계약 {"codes":[...]}은 items 부재로 400."""
        from backend.flow import userstore
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "본문(JSON)을 읽을 수 없어요"}, status_code=400)
        items = body.get("items") if isinstance(body, dict) else None
        if items is None:
            return JSONResponse({"error": "items 배열이 필요해요"}, status_code=400)
        try:
            saved = userstore.set_watchlist(_req_email(request, settings), items)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"items": saved})

    @app.get("/api/watch/{code}")
    def watch_get(code: str, request: Request):
        """감시선(참조선) 조회(계정별) — 파일 저장값 우선, 없으면 마스터만 config 폴백."""
        if not _CODE_RE.match(code):
            return Response(status_code=404)
        from backend.flow import userstore
        return JSONResponse({"lines": userstore.get_lines(_req_email(request, settings), code)})

    @app.post("/api/watch/{code}")
    async def watch_set(code: str, request: Request):
        """감시선 저장(계정별) — body {"lines":[{"price":num,"label":str}, ...]}.
        검증 실패 400(사용자 메시지), 성공 시 정규화된 {"lines": [...]}."""
        if not _CODE_RE.match(code):
            return Response(status_code=404)
        from backend.flow import userstore
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "본문(JSON)을 읽을 수 없어요"}, status_code=400)
        lines = body.get("lines") if isinstance(body, dict) else None
        try:
            saved = userstore.set_lines(_req_email(request, settings), code, lines)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"lines": saved})

    @app.get("/scanner", response_class=HTMLResponse)
    def scanner_page():
        """수급 스캐너 — 오늘 수급 특이 종목(외인/기관 가집계 × 거래대금/급등 교차)."""
        return HTMLResponse(render_scanner_page())

    @app.get("/widget-setup", response_class=HTMLResponse)
    def widget_setup_page(request: Request):
        """위젯 설치 페이지 — 게이트 뒤(공개 아님). 계정별 토큰·스크립트를 사파리에서 복사.
        토큰원 = userstore.ensure_token(요청자 계정)(유저파일 단일원, env 정적토큰 아님).
        base_url은 프록시 헤더 우선(Funnel이 X-Forwarded-Proto: https를 붙임)."""
        from backend.flow import userstore
        from backend.report.widget_setup import render_widget_setup
        email = _req_email(request, settings)
        if not email:
            return HTMLResponse("계정을 확인할 수 없어요 — 로그인 후 다시 시도하세요",
                                status_code=503)
        token = userstore.ensure_token(email)
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", request.url.netloc)
        return HTMLResponse(render_widget_setup(token, "%s://%s" % (scheme, host)))

    @app.post("/widget-setup/rotate")
    def widget_setup_rotate(request: Request):
        """위젯 토큰 재발급 — 요청자(_req_email) 계정의 토큰만 회전(계정 격리). 회전 즉시
        구 토큰 사망(email_for_token→None) → 유출 시 대응 경로. 새 토큰을 JSON으로 반환."""
        from backend.flow import userstore
        email = _req_email(request, settings)
        if not email:
            return JSONResponse({"error": "계정을 확인할 수 없어요"}, status_code=503)
        return JSONResponse({"token": userstore.rotate_token(email)})

    @app.get("/api/scanner")
    async def scanner_api():
        if not (settings.kis_app_key and settings.kis_app_secret):
            return JSONResponse(
                {"error": "스캐너는 KIS 키가 필요합니다 (.env에 SM_KIS_APP_KEY/SECRET)"},
                status_code=503)
        return JSONResponse(await flow_scanner.fetch_scan())

    @app.get("/api/semi")
    async def semi_api():
        """반도체 동향(메모리 중심) — 미국(SOX·나스닥)+국내 시세 요약, 60초 캐시."""
        return JSONResponse(await semi.get_overview())

    @app.get("/api/prices")
    async def prices_api(request: Request):
        """관심종목 실시간 현재가 — 대시보드 카드가 폴링. 장중에만 KIS 조회(장외/주말은 open:false).
        KR 파이프라인이라 계정 watchlist의 KR 코드만 조회(US는 여기 경로 없음)."""
        from backend.cli import _kr_market_open, fetch_live_prices
        from backend.flow import userstore
        if not _kr_market_open():
            return JSONResponse({"open": False, "prices": {}})
        codes = userstore.get_kr_codes(_req_email(request, settings))
        return JSONResponse({"open": True, "prices": await fetch_live_prices(codes)})

    @app.get("/api/widget")
    async def widget_api(request: Request):
        """아이폰 위젯 시세 — 인증은 AuthGate(Bearer)가 이미 끝냄(핸들러 인증 코드 0줄).
        KIS 단일 소스, 장외에도 직전 세션 종가+등락률(설계 2026-07-16).

        계정 해석: 게이트가 Bearer→계정을 검증해 넣은 scope['state']['widget_email']이
        유일 해석원(default_account 폴백 금지 — 교차계정 유출 차단). 인증 비활성(로컬)일 때만
        게이트가 없어 _req_email(→default_account)로 폴백한다(그 경로엔 위젯 토큰이 없음)."""
        from backend.api.widget import widget_data
        from backend.flow import userstore
        email = (request.scope.get("state") or {}).get("widget_email")
        if not email:
            email = _req_email(request, settings)
        codes = userstore.get_kr_codes(email)
        data = await widget_data(codes)
        if data is None:
            return JSONResponse({"error": "시세를 가져올 수 없어요 (KIS 키 또는 캐시 필요)"},
                                status_code=503)
        return JSONResponse(data)

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

    if settings.auth_enabled:
        _auth.install(app, settings)
    return app


app = create_app()
