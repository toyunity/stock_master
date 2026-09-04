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
from backend.flow import worldidx
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


async def _verify_new_us_tickers(email, items):
    """신규 US 티커만 price_us로 존재 확인(설계 §6·에러표). 통과면 None, 없으면 사용자 메시지(400).

    - 재정렬·삭제·보유변경(기존 US 티커)은 재검증 안 함 — 매 저장마다 KIS 재호출·outage 시
      재정렬 불가를 막는다(신규분 diff = incoming − 저장된 US 집합).
    - KIS 미설정(로컬/데모)이면 검증 생략(통과) — 프로덕션 마스터 KIS에서만 강제.
    - 모듈 경유 호출(usquote.price_us / candles._get_client)이라 테스트가 모킹 가능·실 KIS 0."""
    if not isinstance(items, list):
        return None
    from backend.flow import userstore
    existing = {i["code"] for i in userstore.get_watchlist(email)
                if i.get("market") == "US"}
    new_us, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            continue
        code = str(it.get("code", "")).strip().upper()
        if userstore.market_of(code) == "US" and code not in existing and code not in seen:
            seen.add(code)
            new_us.append(code)
    if not new_us:
        return None
    if not _settings.kis_app_key:      # 로컬/데모 — 존재확인 불가, 통과
        return None
    from backend.flow import usquote
    try:
        client = candles._get_client()
    except Exception:
        return None
    for c in new_us:
        try:
            q = await usquote.price_us(client, c)
        except Exception:
            q = None
        if not q or not q.get("price"):
            return "티커를 찾을 수 없어요(NAS/NYS/AMS): %s" % c
    return None


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
    # 계정별 저장소 마이그레이션 — 전역 watchlist·watch_lines·env 위젯토큰을 마스터 계정으로
    # 1회 승격(멱등). 미호출 시 마스터 아이폰 위젯이 기존 env 토큰으로 401(하위호환 파손).
    from backend.flow.userstore import migrate_globals as _migrate_globals
    _migrate_globals()
    app = FastAPI(title="Stock Master")

    @app.on_event("shutdown")
    async def _stop_engines():
        """종료 시 웹소켓을 클로즈 프레임과 함께 정리 — 좀비 세션(KIS 'ALREADY' 거부의
        원인, 실측 2026-07-10)을 남기지 않는다. 엔진은 등록만 반납하고, 연결 자체를
        닫는 건 공유 세션(wsbus)의 몫이므로 엔진을 모두 세운 뒤 마지막에 닫는다."""
        from backend.flow import wsbus
        for eng in list(FlowEngine._registry.values()):
            try:
                await eng.shutdown()
            except Exception:
                pass
        try:
            await wsbus.WsSession.close_all()
        except Exception:
            pass

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        from backend.flow import userstore
        # 카드 목록만 KR+US를 함께 쓴다(get_dash_items). /api/fundamentals·outlook·prices는
        # KIS 국내 TR이라 여전히 get_kr_codes다.
        html = build_dashboard(userstore.get_dash_items(_req_email(request, settings)),
                               settings.cache_dir, history_days=settings.history_days,
                               with_news=True, pwa=True)
        return HTMLResponse(html)

    @app.get("/live/{code}", response_class=HTMLResponse)
    def live(code: str, request: Request):
        """상세 화면 — 국내는 실시간 수급, 미국은 가격·감시선 전용(설계 2026-08-06).

        경로를 나누지 않고 여기서 가른다. `/us/{sym}`를 따로 두면 감시선 편집기·
        인증 게이트·뒤로가기를 두 벌 유지하게 된다. 판정은 userstore.market_of
        하나로 — 관심종목 저장이 쓰는 규칙과 같아야 "저장은 됐는데 화면은 404"가 안 난다."""
        from backend.flow import userstore
        market = userstore.market_of(code)
        if market == "US":
            from backend.report.us_page import render_us_page
            from backend.flow.usquote import us_name
            return HTMLResponse(render_us_page(code.upper(), us_name(code.upper()),
                                               _req_email(request, settings)))
        if market != "KR":
            return HTMLResponse("종목 코드는 6자리 숫자(국내) 또는 티커(미국)입니다",
                                status_code=404)
        eng = FlowEngine.get(code)
        return HTMLResponse(render_live_page(code, eng.state.name, eng.mode,
                                             _req_email(request, settings)))

    @app.get("/api/usprice/{sym}")
    async def us_price_api(sym: str):
        """미국 현재가 — **정규장 중에만** 준다(장외엔 204 No Content).

        장외에도 부르면 화면이 열릴 때마다 KIS 해외 TR이 나간다. 장이 닫혀 있으면
        일봉 종가가 최신이고 그게 차트와도 일치하므로, 조회할 이유 자체가 없다."""
        from backend.api import marketdata
        from backend.flow import adr, toss, userstore, usquote
        if userstore.market_of(sym) != "US":
            return Response(status_code=404)
        # 토스가 있으면 **세션 게이트를 걸지 않는다** — 미국 시세가 데이마켓·프리·
        # 애프터에도 실시간으로 온다(2026-09-03 실측: 조회 대비 최소 4.2초). 한국 낮이
        # 미국 데이마켓이라, 정규장 게이트를 그대로 두면 마스터가 앱을 실제로 보는
        # 시간대에 값이 안 나온다. KIS 클라이언트가 None이어도 토스 단독으로 성립한다.
        # 토스가 없을 땐 기존 게이트 그대로 — KIS 해외 시세는 정규장 밖에서 스테일하다.
        client = marketdata._client()
        if toss.get_client() is None and not (adr.us_market_open() and client):
            return Response(status_code=204)
        try:
            q = await usquote.price_us(client, sym.upper())
        except Exception:
            q = None
        return JSONResponse(q or {}, status_code=200 if q else 204)

    @app.get("/api/live/{code}/stream")
    async def _live_stream(code: str):
        return await live_stream(code)

    @app.get("/api/candles/{code}")
    async def candles_api(code: str, tf: str = "5m"):
        """봉 차트 — tf: 1m/5m/15m/60m(당일 분봉, LIVE는 KIS·데모는 합성) |
        1d/1w/1mo(일·주·월봉 120, FDR 경로).

        일·주·월봉은 FDR 경로라 미국 티커도 된다. **분봉은 KIS 국내 TR 전용**이라
        미국은 400으로 거절한다 — 빈 배열로 얼버무리면 '데이터가 없는 날'과 '이
        시장엔 아예 없다'가 화면에서 구분되지 않는다."""
        from backend.flow import userstore
        # 대문자 정규화 — market_of는 내부에서 대문자로 봐 소문자도 통과시키는데,
        # 여기서부터는 코드가 **파일명**(<code>.parquet)·dict 키로 쓰인다. 안 맞추면
        # aapl.parquet / AAPL.parquet 두 벌이 생긴다(국내는 숫자라 무영향).
        code = code.upper()
        market = userstore.market_of(code)
        if market is None:
            return Response(status_code=404)
        if market == "US" and tf not in ("1d", "1w", "1mo"):
            return JSONResponse({"error": "미국 종목은 일·주·월봉만 제공해요 — "
                                          "분봉은 국내 전용입니다"}, status_code=400)
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
        email = _req_email(request, settings)
        # 신규 US 티커는 저장 전 price_us로 존재확인(없으면 400) — 기존 US는 재검증 안 함.
        err = await _verify_new_us_tickers(email, items)
        if err:
            return JSONResponse({"error": err}, status_code=400)
        try:
            saved = userstore.set_watchlist(email, items)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"items": saved})

    @app.get("/api/watch/{code}")
    def watch_get(code: str, request: Request):
        """감시선(참조선) 조회(계정별) — 파일 저장값 우선, 없으면 마스터만 config 폴백.
        국내·미국 공용(가격 정밀도는 userstore가 코드로 판정해 가른다)."""
        from backend.flow import userstore
        code = code.upper()          # 저장 키 통일 — /api/watch/aapl 로 넣고 AAPL로 못 찾는 것 방지
        if userstore.market_of(code) is None:
            return Response(status_code=404)
        return JSONResponse({"lines": userstore.get_lines(_req_email(request, settings), code)})

    @app.post("/api/watch/{code}")
    async def watch_set(code: str, request: Request):
        """감시선 저장(계정별) — body {"lines":[{"price":num,"label":str}, ...]}.
        검증 실패 400(사용자 메시지), 성공 시 정규화된 {"lines": [...]}."""
        from backend.flow import userstore
        code = code.upper()          # 저장 키 통일(watch_get과 같은 이유)
        if userstore.market_of(code) is None:
            return Response(status_code=404)
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
        import os
        # no-store — 스크립트가 바뀌면 사파리가 옛 페이지를 서빙해 옛 스크립트를 복사하는 것 방지.
        return HTMLResponse(render_widget_setup(token, "%s://%s" % (scheme, host),
                                                apk_available=os.path.isfile(settings.android_apk_path)),
                            headers={"Cache-Control": "no-store"})

    @app.post("/widget-setup/rotate")
    def widget_setup_rotate(request: Request):
        """위젯 토큰 재발급 — 요청자(_req_email) 계정의 토큰만 회전(계정 격리). 회전 즉시
        구 토큰 사망(email_for_token→None) → 유출 시 대응 경로. 새 토큰을 JSON으로 반환."""
        from backend.flow import userstore
        email = _req_email(request, settings)
        if not email:
            return JSONResponse({"error": "계정을 확인할 수 없어요"}, status_code=503)
        return JSONResponse({"token": userstore.rotate_token(email)})

    @app.get("/widget-setup/android.apk")
    def widget_setup_apk():
        """갤럭시 위젯 APK — 게이트 뒤(test_auth PROTECTED). 파일은 `make android`가 data/android/에 둔다.
        APK에 비밀은 없지만(주소·토큰은 런타임 입력) '모든 경로 잠금' 불변식 때문에 공개 예외로 두지
        않는다(설계 2026-09-04). 교체는 8000 재기동 없이 파일만 바꾸면 된다."""
        import os
        from fastapi.responses import FileResponse
        p = settings.android_apk_path
        if not (p and os.path.isfile(p)):
            return JSONResponse({"error": "APK가 없어요 — 맥에서 `make android`로 빌드하세요"}, status_code=404)
        return FileResponse(p, media_type="application/vnd.android.package-archive",
                            filename="StockMasterWidget.apk", headers={"Cache-Control": "no-store"})

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

    @app.get("/api/worldidx")
    async def worldidx_api():
        """글로벌 지표 — 미국채(2Y/10Y/30Y)·원자재(WTI·금)·해외지수(S&P500·나스닥·VIX).

        원천이 셋이라 실패도 셋으로 나뉜다 — 죽은 원천의 그룹만 빠지고 나머지는 그대로
        200으로 나간다. 전부 죽으면 groups=[]이고, 그건 에러가 아니라 '섹션을 감추라'는
        신호다(빈 껍데기 금지). 키 없음도 여기서 막지 않는다 — 503으로 끊으면 KIS와
        무관한 재무부·원자재까지 같이 죽는다.

        캐시·쿨다운은 worldidx가 원천별로 들고 있어 라우트는 그대로 위임만 한다."""
        return JSONResponse(await worldidx.get_worldidx())

    @app.get("/api/prices")
    async def prices_api(request: Request):
        """관심종목 실시간 현재가 — 대시보드 카드가 폴링. 세션 중에만 KIS 조회
        (UN 기본: 프리 08:00~애프터 20:00 KST, NXT 포함 — 그 밖/주말은 open:false).
        KR 파이프라인이라 계정 watchlist의 KR 코드만 조회(US는 여기 경로 없음)."""
        from backend.cli import _kr_market_open, fetch_live_prices
        from backend.flow import userstore
        if not _kr_market_open():
            return JSONResponse({"open": False, "prices": {}})
        codes = userstore.get_kr_codes(_req_email(request, settings))
        return JSONResponse({"open": True, "prices": await fetch_live_prices(codes)})

    @app.get("/api/market")
    async def market_api():
        """시장 지수(코스피·코스닥) — 대시보드 상단 컨텍스트. 장외에도 직전값(캐시). 키없음이면 {}."""
        from backend.api import marketdata
        return JSONResponse(await marketdata.get_indices() or {})

    @app.get("/api/kospi-temp")
    async def kospi_temp_api():
        """코스피 온도 — 지수값이 최근 흐름에서 어디쯤인지(이격도·EMA 이격·하락폭).

        판정 단어까지 서버가 실어 내린다. 프런트가 임계값을 들고 있으면 판정 기준이
        두 군데로 갈라진다(unit·rate_unit·basis_kind를 데이터에 실은 것과 같은 이유).

        실패하면 items=[]로 200이다 — 그룹 하나가 빠질 뿐 섹션은 떠야 한다."""
        from backend.flow import kospitemp
        return JSONResponse(await kospitemp.get_temp())

    @app.get("/api/vkospi")
    async def vkospi_api():
        """코스피200 변동성지수 — 현재값 + 최근 100거래일. 섹션을 펼칠 때만 호출된다.
        키없음/실패면 {} — 프론트가 섹션을 숨긴다."""
        from backend.api import marketdata
        return JSONResponse(await marketdata.get_vkospi() or {})

    @app.get("/api/futures")
    async def futures_api():
        """지수 선물 칩 2종 — K200(주간↔야간 세션 전환) + 나스닥100 대용 QQQ ETF.
        칩별 독립 캐시·독립 실패(한쪽이 죽어도 다른 쪽은 그대로 응답). 키없음이면 {},
        일부만 실패하면 그 칩만 빠진 dict."""
        from backend.api import marketdata
        return JSONResponse(await marketdata.get_futures() or {})

    @app.get("/api/options")
    async def options_api():
        """코스피200 옵션 보드 — 행사가별 미결제·당일증감 + 요약 숫자.
        한 회차가 수 분이라 서버가 백그라운드로 모으고 여기선 직전값을 곧바로 준다.
        키없음/콜드면 {} — 프론트가 섹션을 숨긴다."""
        from backend.api import marketdata
        return JSONResponse(await marketdata.get_options() or {})

    @app.get("/api/fundamentals")
    async def fundamentals_api(request: Request):
        """관심종목 밸류지표(PER/PBR/52주 위치) — 대시보드 카드 칩. 느리게 변해 별도 저빈도 조회."""
        from backend.api import marketdata
        from backend.flow import userstore
        codes = userstore.get_kr_codes(_req_email(request, settings))
        return JSONResponse(await marketdata.get_fundamentals(codes))

    @app.get("/api/financials/{code}")
    async def financials_api(code: str):
        """단일 종목 기업 체력(PER·PBR·52주·ROE·부채) + 쉬운말 — /live 접힘 패널. 6자리 코드만."""
        from backend.api import marketdata
        if not _CODE_RE.match(code):
            return Response(status_code=404)
        return JSONResponse(await marketdata.get_stock_detail(code))

    @app.get("/api/outlook")
    async def outlook_api(request: Request):
        """관심종목 내일 예상(경량 배지) — 대시보드가 fetch. code→{direction,reason}."""
        from backend.api import marketdata
        from backend.flow import userstore
        codes = userstore.get_kr_codes(_req_email(request, settings))
        return JSONResponse(await marketdata.get_outlook_brief(codes))

    @app.get("/api/topview")
    async def topview_api():
        """조회상위(인기 종목) — 발굴. 스캐너가 fetch. 코드만 오는 걸 universe로 이름 조인."""
        from backend.api import marketdata
        return JSONResponse({"items": await marketdata.get_top_view()})

    @app.get("/api/asking/{code}")
    async def asking_api(code: str):
        """호가 사다리(매도벽·매수받침·매수세%) — /live REST 폴링(실시간 WS 세션 회피). 6자리만."""
        from backend.api import marketdata
        if not _CODE_RE.match(code):
            return Response(status_code=404)
        return JSONResponse(await marketdata.get_asking(code))

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
        # 위젯은 KR+US를 함께 싣는 유일 표면(§4) — 전체 items로 조립(KR 파이프라인 분리 불변식과 별개).
        data = await widget_data(email, userstore.get_watchlist(email))
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
