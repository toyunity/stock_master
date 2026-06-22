import datetime as dt
from pathlib import Path
from backend.signals.rules import Signal
from backend.report.render import render_daily_report
from backend.analysis.backtest import BacktestResult
from backend.news.models import NewsItem, Disclosure

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


def test_render_includes_matched_news_and_disclosures(tmp_path):
    sig = Signal(code="005930", action="buy", confidence=3, reasons=["골든크로스"], advice=True)
    news = NewsItem(title="삼성전자 신제품 발표", summary="요약", link="https://news.example/1",
                    published=dt.datetime(2026, 6, 19, 9, 30), source="한국경제")
    disc = Disclosure(corp_name="삼성전자", stock_code="005930", report_name="주요사항보고서",
                      rcept_no="20260619000123", rcept_dt="20260619",
                      link="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260619000123")
    issues = {"005930": {"news": [news], "disclosures": [disc]}}
    out = tmp_path / "r.html"
    render_daily_report([sig], "2026-06-19", out, issues_by_code=issues)
    html = out.read_text(encoding="utf-8")
    assert "관련 이슈" in html
    assert "매매 권유 아님" in html          # 비권유 라벨
    assert "주요사항보고서" in html           # 공시 report_name
    assert "삼성전자 신제품 발표" in html      # 뉴스 title
    assert "https://news.example/1" in html   # 뉴스 link
    assert disc.link in html                   # 공시 link
    assert "DART" in html                      # 출처 고지
    assert "한국경제" in html                  # 뉴스 source
    assert "2026-06-19" in html                # 공시 날짜 변환
    assert "06-19 09:30" in html               # 뉴스 시각 변환
    assert 'rel="noopener"' in html


def test_render_escapes_news_title_xss(tmp_path):
    sig = Signal(code="005930", action="buy", confidence=2, reasons=["골든크로스"], advice=True)
    news = NewsItem(title="<script>alert('x')</script>", summary="s",
                    link="https://news.example/x", published=None, source="언론사")
    issues = {"005930": {"news": [news], "disclosures": []}}
    out = tmp_path / "r.html"
    render_daily_report([sig], "2026-06-19", out, issues_by_code=issues)
    html = out.read_text(encoding="utf-8")
    assert "<script>" not in html              # raw 태그가 출력되면 안 됨
    assert "&lt;script&gt;" in html            # 이스케이프된 형태로 출력


def test_render_no_issues_section_when_none_or_empty(tmp_path):
    sig = Signal(code="005930", action="hold", confidence=1, reasons=["신호 없음"], advice=False)
    # issues_by_code=None (기본): 이슈 섹션 없음, 크래시 없음
    out1 = tmp_path / "none.html"
    render_daily_report([sig], "2026-06-19", out1)
    assert "관련 이슈" not in out1.read_text(encoding="utf-8")
    # 빈 이슈(뉴스/공시 모두 빈 리스트): 섹션 없음
    out2 = tmp_path / "empty.html"
    render_daily_report([sig], "2026-06-19", out2,
                        issues_by_code={"005930": {"news": [], "disclosures": []}})
    assert "관련 이슈" not in out2.read_text(encoding="utf-8")


def test_build_html_pwa_head_only_when_pwa_true():
    from backend.report.render import build_daily_report_html
    sig = Signal(code="005930", action="hold", confidence=1, reasons=["신호 없음"], advice=False)
    pwa = build_daily_report_html([sig], "2026-06-22", pwa=True)
    plain = build_daily_report_html([sig], "2026-06-22", pwa=False)
    # 아이폰 설치용 태그·새로고침 버튼은 pwa=True일 때만
    for marker in ("apple-touch-icon", "/manifest.json", "새로고침", "apple-mobile-web-app-capable"):
        assert marker in pwa, marker
        assert marker not in plain, marker


def test_render_glossary_page_has_all_terms(tmp_path):
    from backend.education import glossary
    from backend.report.render import render_glossary_page
    out = tmp_path / "g.html"
    render_glossary_page(out)
    html = out.read_text(encoding="utf-8")
    for t in glossary.all_terms():
        assert t.key in html
    assert "상승 추세로의 전환 신호" in html   # 골든크로스 long 포함
    assert "기초 개념" in html                  # lessons 섹션
    assert "손절" in html
