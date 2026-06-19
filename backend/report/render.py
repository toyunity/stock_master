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


def render_daily_report(signals, date: str, out_path) -> Path:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True)
    tmpl = env.get_template("daily.html.j2")
    view = [{"code": s.code, "action": s.action,
             "action_ko": _ACTION_KO[s.action], "confidence": s.confidence,
             "reasons": s.reasons, "advice": s.advice,
             "backtest": _bt_view(s.backtest)} for s in signals]
    all_reason_text = " ".join(r for s in signals for r in s.reasons)
    glossary_view = [{"key": t.key, "short": t.short, "long": t.long}
                     for t in glossary.terms_in(all_reason_text)]
    lessons_view = [{"title": l.title, "body": l.body} for l in lessons_mod.LESSONS]
    html = tmpl.render(signals=view, date=date,
                       glossary_terms=glossary_view, lessons=lessons_view)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
