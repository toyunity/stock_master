from __future__ import annotations
import argparse
import datetime as dt
from pathlib import Path

from backend.config import settings
from backend.adapters.cache import OHLCVCache
from backend.adapters.prices import PriceAdapter
from backend.analysis.indicators import add_indicators
from backend.signals.rules import evaluate
from backend.report.render import render_daily_report

def generate_report(codes, out_path, cache_dir, source=None, history_days=400):
    adapter = PriceAdapter(OHLCVCache(cache_dir), source=source)
    end = dt.date.today()
    start = end - dt.timedelta(days=history_days)
    signals = []
    for code in codes:
        df = adapter.get_ohlcv(code, start.isoformat(), end.isoformat())
        df = add_indicators(df)
        signals.append(evaluate(df, code))
    return render_daily_report(signals, end.isoformat(), out_path)

def main():
    p = argparse.ArgumentParser(prog="stock-master")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report", help="관심종목 일일 HTML 리포트 생성")
    args = p.parse_args()
    if args.cmd == "report":
        out = generate_report(settings.watchlist, "docs/report-daily.html",
                              settings.cache_dir, history_days=settings.history_days)
        print(f"리포트 생성: {out}")

if __name__ == "__main__":
    main()
