from __future__ import annotations
import argparse
import datetime as dt
import logging
import time
from pathlib import Path

from backend.config import settings
from backend.adapters.cache import OHLCVCache
from backend.adapters.prices import PriceAdapter
from backend.analysis.indicators import add_indicators
from backend.signals.rules import evaluate_with_gate
from backend.report.render import render_daily_report, build_daily_report_html
from backend.ingest.rss_source import fetch_news
from backend.ingest.dart_source import fetch_disclosures
from backend.news.match import attach_issues
from backend.news.names import STOCK_NAMES
from backend.report.dashboard import render_dashboard, to_candles, assemble_stock
from backend.market.universe import get_universe, price_map, name_map

log = logging.getLogger(__name__)


def _news_aliases(codes, names=None) -> dict:
    """뉴스 매칭 별칭 — 수동 별칭(STOCK_NAMES, 경계 인식 튜닝됨) 우선,
    없으면 universe 이름 1개 자동 보강(신규 종목 뉴스 영구 0건 방지 — 설계)."""
    return {c: (STOCK_NAMES.get(c)
                or ([names[c]] if names and names.get(c) else []))
            for c in codes}


def _collect_issues(codes, names=None):
    """RSS 뉴스 + DART 공시를 수집해 종목별로 매칭한다.

    수집 실패(네트워크/파싱)는 리포트를 막지 않는다 — 빈 결과로 계속 진행한다.
    DART는 키(SM_DART_API_KEY)가 없으면 내부적으로 빈 리스트를 반환한다(키 없이도 가동).
    """
    try:
        news = fetch_news(settings.news_feeds)
    except Exception:
        log.warning("RSS 뉴스 수집 실패 — 뉴스 없이 진행", exc_info=True)
        news = []
    try:
        disclosures = fetch_disclosures(
            settings.dart_api_key, codes, settings.disclosure_lookback_days
        )
    except Exception:
        log.warning("DART 공시 수집 실패 — 공시 없이 진행", exc_info=True)
        disclosures = []
    return attach_issues(news, disclosures, codes, _news_aliases(codes, names),
                         max_per_stock=settings.news_max_per_stock)


def build_daily_html(codes, cache_dir, source=None, history_days=400,
                     force: bool = False, with_news: bool = True, pwa: bool = False) -> str:
    """가격→지표→신호→(뉴스/공시)→리포트 HTML 문자열. CLI(파일 저장)와 웹앱(서빙) 공용."""
    adapter = PriceAdapter(OHLCVCache(cache_dir), source=source)
    end = dt.date.today()
    start = end - dt.timedelta(days=history_days)
    signals = []
    for code in codes:
        df = adapter.get_ohlcv(code, start.isoformat(), end.isoformat(), force=force)
        df = add_indicators(df)
        signals.append(evaluate_with_gate(df, code))
    issues_by_code = _collect_issues(codes) if with_news else None
    return build_daily_report_html(signals, end.isoformat(), issues_by_code, pwa=pwa)


def _kr_market_open(now=None) -> bool:
    """KRX+NXT 통합 세션(평일, market_div=UN/NX면 프리 08:00~애프터 20:00, J면 09:00~15:30 KST) 여부.
    settings.market_div=UN(기본)이라 NXT 애프터마켓(15:30~20:00)도 '열림'으로 본다 — /api/prices와
    build_dashboard의 실시간 덮어쓰기가 이 시간에도 계속 흐른다(설계, session.py가 단일 정의 소스)."""
    from zoneinfo import ZoneInfo
    from backend.flow.session import is_session_open
    n = now or dt.datetime.now(ZoneInfo("Asia/Seoul"))
    return is_session_open(n, settings.market_div)


async def fetch_live_prices(codes) -> dict:
    """관심종목 현재가(KIS FHKST01010100 주식현재가) → {code:{close,change}}. StockListing은
    EOD·12h 캐시라 장중에도 전일 종가 → 관심종목만 실시간으로. 키 없음/실패 코드는 생략(→ 폴백)."""
    import asyncio
    try:
        from backend.flow.candles import _get_client
        client = _get_client()
    except Exception:
        return {}

    sem = asyncio.Semaphore(5)   # 동시 호출 제한 — 편집 후 최대 10종목 × 12초 폴링
                                 # × 위젯이 겹쳐도 KIS 간헐 500(EGW00201) 방어(설계)

    async def one(c):
        async with sem:
            try:
                p = await client.price(c)
                if p and p.get("price"):
                    return c, {"close": p["price"], "change": p.get("rate")}
            except Exception:
                pass
            return c, None
    res = await asyncio.gather(*[one(c) for c in codes])
    return {c: v for c, v in res if v}


def _live_prices(codes) -> dict:
    """build_dashboard(sync)용 래퍼 — 새 이벤트루프로 fetch_live_prices 실행(요청마다 새 AsyncClient라 안전)."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(fetch_live_prices(codes))
    except Exception:
        return {}
    finally:
        loop.close()


def build_dashboard(codes, cache_dir, source=None, history_days=400,
                    force: bool = False, with_news: bool = True, pwa: bool = False,
                    chart_days: int = 120) -> str:
    """대시보드(종목별 차트 + 검색 + 카드) 자기완결 HTML. CLI/웹앱 공용."""
    adapter = PriceAdapter(OHLCVCache(cache_dir), source=source)
    end = dt.date.today()
    start = end - dt.timedelta(days=history_days)
    signals, candles = [], {}
    for code in codes:
        df = adapter.get_ohlcv(code, start.isoformat(), end.isoformat(), force=force)
        signals.append(evaluate_with_gate(add_indicators(df), code))
        candles[code] = to_candles(df, chart_days)
    universe = get_universe(cache_dir)
    nm = name_map(universe)
    issues = _collect_issues(codes, nm) if with_news else {}
    pm = price_map(universe)
    if _kr_market_open():   # 세션 중엔(UN 기본: 프리·정규·NXT 애프터) 관심종목을 KIS 실시간
                             # 현재가로 덮어씀(StockListing=전일 종가)
        pm.update(_live_prices(codes))
    stocks = [assemble_stock(s, issues.get(s.code), candles.get(s.code), pm.get(s.code), nm)
              for s in signals]
    return render_dashboard(stocks, universe, end.isoformat(), pwa=pwa)


def generate_report(codes, out_path, cache_dir, source=None, history_days=400,
                    force: bool = False, with_news: bool = True):
    html = build_daily_html(codes, cache_dir, source=source, history_days=history_days,
                            force=force, with_news=with_news, pwa=False)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main():
    p = argparse.ArgumentParser(prog="stock-master")
    sub = p.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report", help="관심종목 일일 HTML 리포트 생성")
    rp.add_argument("--force", action="store_true", help="캐시 무시하고 새로 받기")
    rp.add_argument("--no-news", action="store_true", help="뉴스/공시 수집 생략")
    sub.add_parser("glossary", help="용어·개념 학습 HTML 생성")
    sh = sub.add_parser("shortbal", help="대차잔고 수동 수집/조회 (T+1 공시, 협회→예탁원 폴백)")
    sh.add_argument("--code", default="000660", help="6자리 종목코드 (기본 SK하이닉스)")
    sh.add_argument("--days", type=int, default=20, help="최근 거래일 수")
    sub.add_parser("collect-options",
                   help="코스피200 옵션 보드 수집(배치) — data/cache/options_<만기>.json에 저장")
    sv = sub.add_parser("serve", help="웹앱 서버 실행(아이폰 등에서 접속)")
    sv.add_argument("--host", default="0.0.0.0", help="기본 0.0.0.0(같은 WiFi 기기 접속 허용)")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true", help="코드 수정 시 자동 재시작(개발용)")
    args = p.parse_args()
    if args.cmd == "report":
        from backend.flow import userstore
        codes = userstore.get_kr_codes(userstore.default_account())   # KR 전용 파이프라인
        html = build_dashboard(codes, settings.cache_dir,
                               history_days=settings.history_days,
                               force=args.force, with_news=not args.no_news)
        out = Path("docs/report-daily.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"대시보드 생성: {out}")
    elif args.cmd == "shortbal":
        import asyncio
        from backend.flow import shortbal
        d = asyncio.run(shortbal.get_history(args.code, settings.cache_dir,
                                             days=args.days))
        if not d["rows"]:
            print("대차잔고: 데이터 없음 (수집 실패 또는 미공시)")
        else:
            print(f"{args.code} 대차잔고 — {d['asof']} 기준 · 출처 {d['source']}")
            for r in d["rows"]:
                chg = f"{r['chg']:+,}주" if r.get("chg") is not None else "–"
                print(f"  {r['date']}  잔고 {r['qty']:>12,}주"
                      f"  전일대비 {chg:>12}  금액 {r['value'] / 1e12:.2f}조")
    elif args.cmd == "collect-options":
        # 옵션 수집 배치 — 웹서버와 분리된 프로세스로 돈다(launchd 일정).
        # 1키1세션(웹소켓)과 무관하다: 이 경로는 REST 전용이라 서버의 실시간 세션을
        # 건드리지 않는다. 공유되는 건 앱키의 초당 호출 한도뿐이고 상한은 코드가 지킨다.
        import asyncio
        import sys as _sys
        from backend.api import marketdata
        from backend.flow import kst
        if not settings.options_enabled:
            print("옵션 수집 꺼짐 (SM_OPTIONS_ENABLED=false) — 아무것도 하지 않음")
            return
        t0 = time.time()
        d = asyncio.run(marketdata.collect_options())
        if not d:
            print("옵션 수집 실패 — 저장 안 함 (마스터/만기/시세 중 하나를 못 받음)")
            _sys.exit(1)
        n = len(d["calls"]) + len(d["puts"])
        s = d["summary"]
        print("[%s] 옵션 수집 완료 — %s(%s) %d종목 · %.0f초 · %.2f건/초 · 실패 %d건"
              % (kst.now().strftime("%m-%d %H:%M:%S"), d["expiry"], d["label"], n,
                 time.time() - t0, n / max(time.time() - t0, 0.001), d["failed"]))
        print("  풋콜 %s · ATM IV %s%% · 풋 벽 %s(지수 ±%s%%) · 오늘 콜 %+d 풋 %+d"
              % (s["pcr"] and round(s["pcr"], 2), s["atm_iv"], s["put_wall"],
                 s["wall_pct"], s["call_chg_sum"], s["put_chg_sum"]))
    elif args.cmd == "glossary":
        from backend.report.render import render_glossary_page
        out = render_glossary_page("docs/glossary.html")
        print(f"용어집 생성: {out}")
    elif args.cmd == "serve":
        import uvicorn
        print(f"📲 웹앱 시작 — 아이폰 사파리에서 http://<맥의IP>:{args.port} 접속 (같은 WiFi)")
        print("   중지: Ctrl+C")
        # timeout_graceful_shutdown: SSE 무한 스트림이 종료 드레인을 영원히 막아
        # 프로세스가 좀비(KIS 웹소켓 세션 점유)로 남는 것을 방지(실측 2026-07-10)
        uvicorn.run("backend.api.app:app", host=args.host, port=args.port,
                    reload=args.reload, timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
