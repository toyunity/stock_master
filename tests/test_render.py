from pathlib import Path
from backend.signals.rules import Signal
from backend.report.render import render_daily_report

def test_render_writes_html_with_signals(tmp_path):
    sigs = [Signal(code="005930", action="buy", confidence=3,
                   reasons=["골든크로스"], advice=True)]
    out = tmp_path / "r.html"
    render_daily_report(sigs, "2026-06-19", out)
    html = out.read_text(encoding="utf-8")
    assert "005930" in html
    assert "골든크로스" in html
    assert "참고용" in html  # 고지문 포함
    assert "매수" in html    # action_ko 변환
