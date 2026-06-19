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


def test_render_includes_glossary_for_terms_in_reasons(tmp_path):
    from backend.signals.rules import Signal
    sig = Signal(code="005930", action="buy", confidence=3,
                 reasons=["20일선이 60일선을 상향 돌파(골든크로스)"], advice=False)
    out = tmp_path / "r.html"
    render_daily_report([sig], "2026-06-19", out)
    html = out.read_text(encoding="utf-8")
    assert "오늘 리포트에 나온 용어" in html
    assert "상승 추세로의 전환 신호" in html   # 골든크로스 long 설명이 들어감
    assert "기초 개념" in html                  # lessons 섹션
    assert "손절" in html                       # 손절 lesson 제목/내용

def test_render_has_no_glossary_section_when_no_known_terms(tmp_path):
    from backend.signals.rules import Signal
    sig = Signal(code="005930", action="hold", confidence=1, reasons=["아무 용어 없음"], advice=False)
    out = tmp_path / "r2.html"
    render_daily_report([sig], "2026-06-19", out)
    html = out.read_text(encoding="utf-8")
    # 등장 용어가 없으면 용어 섹션 헤더는 생략, 단 기초 개념(lessons)은 항상 표시
    assert "오늘 리포트에 나온 용어" not in html
    assert "기초 개념" in html
