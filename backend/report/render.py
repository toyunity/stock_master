from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from backend.education import glossary, lessons as lessons_mod

_ACTION_KO = {"buy": "매수 관심", "sell": "매도 고려", "hold": "관망"}
_TEMPLATES = Path(__file__).parent / "templates"


def _bt_view(bt):
    if bt is None:
        return None
    payoff = "∞" if bt.payoff == float("inf") else f"{bt.payoff:.2f}"
    return {"win_rate": f"{bt.win_rate * 100:.0f}", "trades": bt.trades,
            "payoff": payoff, "mdd": f"{bt.max_drawdown * 100:.1f}"}


def _issues_view(issues):
    """관심종목 1개의 매칭 이슈를 템플릿용 dict로 변환.

    뉴스·공시가 모두 없으면(또는 issues가 None) None을 반환해 섹션을 렌더하지 않는다.
    저작권 보호상 제목/이름/링크/시각/출처만 노출하며 본문은 다루지 않는다.
    """
    if not issues:
        return None
    news = issues.get("news") or []
    disc = issues.get("disclosures") or []
    if not news and not disc:
        return None
    return {
        "disclosures": [
            {"report_name": d.report_name,
             "date": f"{d.rcept_dt[:4]}-{d.rcept_dt[4:6]}-{d.rcept_dt[6:8]}",
             "link": d.link}
            for d in disc
        ],
        "news": [
            {"title": n.title, "link": n.link, "source": n.source,
             "published": n.published.strftime("%m-%d %H:%M") if n.published else ""}
            for n in news
        ],
    }


def render_glossary_page(out_path) -> Path:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True)
    tmpl = env.get_template("glossary.html.j2")
    terms = [{"key": t.key, "short": t.short, "long": t.long} for t in glossary.all_terms()]
    lessons_view = [{"title": l.title, "body": l.body} for l in lessons_mod.LESSONS]
    html = tmpl.render(terms=terms, lessons=lessons_view)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def build_daily_report_html(signals, date: str, issues_by_code=None, pwa: bool = False) -> str:
    """일일 리포트 HTML 문자열을 만든다(파일 미저장).

    CLI는 이 문자열을 파일로 쓰고, 웹앱(API)은 그대로 응답으로 서빙한다.
    pwa=True면 템플릿이 manifest/apple-touch-icon/새로고침 버튼을 포함한다(아이폰 설치용)."""
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True)
    tmpl = env.get_template("daily.html.j2")
    view = [{"code": s.code, "action": s.action,
             "action_ko": _ACTION_KO[s.action], "confidence": s.confidence,
             "reasons": s.reasons, "advice": s.advice,
             "backtest": _bt_view(s.backtest),
             "issues": _issues_view(issues_by_code.get(s.code) if issues_by_code else None)}
            for s in signals]
    all_reason_text = " ".join(r for s in signals for r in s.reasons)
    glossary_view = [{"key": t.key, "short": t.short, "long": t.long}
                     for t in glossary.terms_in(all_reason_text)]
    lessons_view = [{"title": l.title, "body": l.body} for l in lessons_mod.LESSONS]
    return tmpl.render(signals=view, date=date, glossary_terms=glossary_view,
                       lessons=lessons_view, pwa=pwa)


def render_daily_report(signals, date: str, out_path, issues_by_code=None) -> Path:
    html = build_daily_report_html(signals, date, issues_by_code)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
