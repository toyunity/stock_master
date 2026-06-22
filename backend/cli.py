from __future__ import annotations
import argparse
import datetime as dt
import logging

from backend.config import settings
from backend.adapters.cache import OHLCVCache
from backend.adapters.prices import PriceAdapter
from backend.analysis.indicators import add_indicators
from backend.signals.rules import evaluate_with_gate
from backend.report.render import render_daily_report
from backend.ingest.rss_source import fetch_news
from backend.ingest.dart_source import fetch_disclosures
from backend.news.match import attach_issues
from backend.news.names import STOCK_NAMES

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


def generate_report(codes, out_path, cache_dir, source=None, history_days=400,
                    force: bool = False, with_news: bool = True):
    adapter = PriceAdapter(OHLCVCache(cache_dir), source=source)
    end = dt.date.today()
    start = end - dt.timedelta(days=history_days)
    signals = []
    for code in codes:
        df = adapter.get_ohlcv(code, start.isoformat(), end.isoformat(), force=force)
        df = add_indicators(df)
        signals.append(evaluate_with_gate(df, code))
    issues_by_code = _collect_issues(codes) if with_news else None
    return render_daily_report(signals, end.isoformat(), out_path,
                               issues_by_code=issues_by_code)


def main():
    p = argparse.ArgumentParser(prog="stock-master")
    sub = p.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report", help="관심종목 일일 HTML 리포트 생성")
    rp.add_argument("--force", action="store_true", help="캐시 무시하고 새로 받기")
    rp.add_argument("--no-news", action="store_true", help="뉴스/공시 수집 생략")
    sub.add_parser("glossary", help="용어·개념 학습 HTML 생성")
    args = p.parse_args()
    if args.cmd == "report":
        out = generate_report(settings.watchlist, "docs/report-daily.html",
                              settings.cache_dir, history_days=settings.history_days,
                              force=args.force, with_news=not args.no_news)
        print(f"리포트 생성: {out}")
    elif args.cmd == "glossary":
        from backend.report.render import render_glossary_page
        out = render_glossary_page("docs/glossary.html")
        print(f"용어집 생성: {out}")


if __name__ == "__main__":
    main()
