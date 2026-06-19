from pathlib import Path
from backend.signals.rules import Signal
from backend.report.render import render_daily_report
from backend.analysis.backtest import BacktestResult

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


def test_render_shows_backtest_metrics(tmp_path):
    sig = Signal(code="005930", action="buy", confidence=4, reasons=["골든크로스"], advice=True,
                 backtest=BacktestResult("golden_cross", 12, 0.75, 1.8, 0.06, passed=True))
    out = tmp_path / "r.html"
    render_daily_report([sig], "2026-06-19", out)
    html = out.read_text(encoding="utf-8")
    assert "백테스트 성과" in html
    assert "승률 75%" in html
    assert "12거래" in html
