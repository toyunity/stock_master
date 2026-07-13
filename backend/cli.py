from __future__ import annotations
import argparse
import datetime as dt
import logging
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
from backend.market.universe import get_universe, price_map

log = logging.getLogger(__name__)


def _collect_issues(codes):
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
    return attach_issues(news, disclosures, codes, STOCK_NAMES,
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
    issues = _collect_issues(codes) if with_news else {}
    universe = get_universe(cache_dir)
    pm = price_map(universe)
    stocks = [assemble_stock(s, issues.get(s.code), candles.get(s.code), pm.get(s.code))
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
    sv = sub.add_parser("serve", help="웹앱 서버 실행(아이폰 등에서 접속)")
    sv.add_argument("--host", default="0.0.0.0", help="기본 0.0.0.0(같은 WiFi 기기 접속 허용)")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true", help="코드 수정 시 자동 재시작(개발용)")
    args = p.parse_args()
    if args.cmd == "report":
        html = build_dashboard(settings.watchlist, settings.cache_dir,
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
