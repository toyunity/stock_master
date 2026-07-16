from __future__ import annotations

"""MCP 도구 — Stock Master 엔진 데이터를 노출.

전송(transport) 독립: 로컬 stdio(Claude Desktop)든 향후 HTTP(Cowork)든 같은 함수.
모든 출력에는 '참고용·매매 권유 아님' 취지를 유지한다(무자문 설계)."""

import datetime as dt
import json

from backend.config import settings
from backend.adapters.cache import OHLCVCache
from backend.adapters.prices import PriceAdapter
from backend.analysis.indicators import add_indicators
from backend.signals.rules import evaluate_with_gate
from backend.report.dashboard import assemble_stock, to_candles
from backend.market.universe import get_universe, price_map
from backend.news.names import display_name
from backend.flow.watchlist import get_watchlist

_DISCLAIMER = "※ 모든 정보는 참고용이며 매매 권유가 아닙니다. 투자 책임은 본인에게 있습니다."


def _adapter():
    return PriceAdapter(OHLCVCache(settings.cache_dir))


def _date_range():
    end = dt.date.today()
    return (end - dt.timedelta(days=settings.history_days)).isoformat(), end.isoformat()


def _analyze(codes, with_news=True, chart_days=120):
    """[assembled_stock_dict] — 대시보드와 같은 조립을 재사용. chart_days로 캔들 길이 조절."""
    from backend.cli import _collect_issues  # 뉴스/공시 수집(그레이스풀) 재사용
    from backend.market.universe import name_map
    adapter = _adapter()
    start, end = _date_range()
    uni = get_universe(settings.cache_dir)
    pm = price_map(uni)
    nm = name_map(uni)
    issues = _collect_issues(list(codes), nm) if with_news else {}
    rows = []
    for code in codes:
        df = adapter.get_ohlcv(code, start, end)
        sig = evaluate_with_gate(add_indicators(df), code)
        rows.append(assemble_stock(sig, issues.get(code), to_candles(df, chart_days),
                                   pm.get(code), nm))
    return rows


def _price_str(s):
    if s.get("close") is None:
        return ""
    chg = s.get("change")
    chg_s = f" ({chg:+.2f}%)" if chg is not None else ""
    return f"{s['close']:,.0f}원{chg_s}"


def _fmt_stock(s, *, full=False):
    head = f"• {s['name']}({s['code']}) — {s['action_ko']} {_price_str(s)} · 신뢰도 {s['confidence']}/5"
    if s.get("advice"):
        head += " [검증됨]"
    lines = [head]
    for r in s["reasons"]:
        lines.append(f"    - {r}")
    if s.get("backtest"):
        b = s["backtest"]
        lines.append(f"    백테스트: 승률 {b['win_rate']}% · {b['trades']}거래 · 손익비 {b['payoff']} · MDD {b['mdd']}%")
    disc = s.get("disclosures") or []
    if disc:
        n = len(disc) if full else min(3, len(disc))
        lines.append("    공시: " + "; ".join(d["report_name"] for d in disc[:n]))
    news = s.get("news") or []
    if news:
        n = len(news) if full else min(3, len(news))
        lines.append("    뉴스: " + "; ".join(x["title"] for x in news[:n]))
    return "\n".join(lines)


def watchlist_summary() -> str:
    """관심종목 전체의 오늘 분석 요약(신호·현재가·근거·뉴스/공시)."""
    rows = _analyze(get_watchlist(), with_news=True)
    body = "\n".join(_fmt_stock(s) for s in rows)
    return f"📊 관심종목 분석 ({dt.date.today().isoformat()})\n{body}\n\n{_DISCLAIMER}"


def dashboard_data() -> str:
    """관심종목 전체의 차트·신호·현재가·뉴스/공시 데이터(JSON) — 대시보드 아티팩트 생성용.

    Claude가 이 데이터로 인터랙티브 대시보드/캔들차트 아티팩트를 한 번에 만들 수 있다.
    각 종목: code,name,action_ko,confidence,advice,reasons,backtest,close,change,
    news,disclosures,candles(최근 120일 time/open/high/low/close)."""
    rows = _analyze(get_watchlist(), with_news=True, chart_days=60)
    return json.dumps({"date": dt.date.today().isoformat(),
                       "disclaimer": _DISCLAIMER, "stocks": rows}, ensure_ascii=False)


def stock_detail(code: str) -> str:
    """특정 종목(6자리 코드)의 상세 분석(신호·근거·백테스트·뉴스/공시)."""
    code = str(code).strip()
    rows = _analyze([code], with_news=True)
    if not rows:
        return f"{code} 분석 불가"
    return f"📈 {display_name(code)} 상세\n{_fmt_stock(rows[0], full=True)}\n\n{_DISCLAIMER}"


def search_stocks(query: str, limit: int = 20) -> str:
    """전체 KRX 종목을 이름/코드로 검색(현재가·등락률 포함)."""
    q = str(query).strip().lower()
    if not q:
        return "검색어를 입력하세요."
    uni = get_universe(settings.cache_dir)
    hits = [u for u in uni if q in u["name"].lower() or q in u["code"]][:limit]
    if not hits:
        return f"'{query}' 검색 결과 없음"
    out = []
    for u in hits:
        px = f" {u['close']:,.0f}원 ({u['change']:+.2f}%)" if u.get("close") is not None else ""
        out.append(f"• {u['name']}({u['code']}){px}")
    return f"🔎 '{query}' 검색 ({len(hits)}건)\n" + "\n".join(out)


def chart_data(code: str) -> str:
    """특정 종목의 최근 120일 캔들(JSON: time/open/high/low/close) — 차트 시각화용."""
    code = str(code).strip()
    adapter = _adapter()
    start, end = _date_range()
    df = adapter.get_ohlcv(code, start, end)
    return json.dumps({"code": code, "name": display_name(code),
                       "candles": to_candles(df, 120)}, ensure_ascii=False)
