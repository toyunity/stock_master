import re

import pandas as pd

from backend.signals.rules import Signal
from backend.report.dashboard import render_dashboard, assemble_stock, to_candles


def _stock(**kw):
    base = {"code": "005930", "name": "삼성전자", "action": "hold", "action_ko": "관망",
            "confidence": 1, "advice": False, "reasons": ["신호 없음"], "backtest": None,
            "close": 71000, "change": -2.1, "news": [], "disclosures": [],
            "candles": [{"time": "2026-06-19", "open": 70, "high": 72, "low": 69, "close": 71}]}
    base.update(kw)
    return base


def test_render_dashboard_is_self_contained():
    html = render_dashboard([_stock()], [{"code": "005930", "name": "삼성전자",
                            "close": 71000, "change": -2.1}], "2026-06-22")
    assert not re.search(r'(src|href)="https?://', html)   # 외부 리소스 로드 없음
    assert "LightweightCharts" in html and "createChart" in html  # 차트 lib inline
    assert '"candles"' in html and "삼성전자" in html       # 데이터 inline
    assert "투자 유의" in html                              # 고지문


def test_render_dashboard_escapes_script_close_in_data():
    s = _stock(news=[{"title": "</script><b>BOOM</b>", "link": "https://x/1",
                      "source": "s", "published": ""}])
    html = render_dashboard([s], [], "2026-06-22")
    assert "</script><b>BOOM" not in html   # 스크립트 조기 종료 차단(<\\/ 로 치환)
    assert "BOOM" in html                    # 데이터 자체는 보존


def test_pwa_head_only_when_pwa():
    p = render_dashboard([], [], "2026-06-22", pwa=True)
    n = render_dashboard([], [], "2026-06-22", pwa=False)
    for m in ("apple-touch-icon", "/manifest.json", "새로고침"):
        assert m in p and m not in n


def test_to_candles_ascending_unique():
    idx = pd.to_datetime(["2026-06-03", "2026-06-01", "2026-06-02", "2026-06-03"])
    df = pd.DataFrame({"Open": [1, 2, 3, 4], "High": [1, 2, 3, 4],
                       "Low": [1, 2, 3, 4], "Close": [1, 2, 3, 4]}, index=idx)
    c = to_candles(df, days=10)
    times = [x["time"] for x in c]
    assert times == sorted(times) and len(times) == len(set(times))  # 오름차순 + 유니크
    assert len(c) == 3  # 중복 06-03 1개로


def test_assemble_stock_shape():
    sig = Signal(code="005930", action="buy", confidence=3, reasons=["골든크로스"], advice=True)
    s = assemble_stock(sig, {"news": [], "disclosures": []},
                       [{"time": "2026-06-01", "open": 1, "high": 1, "low": 1, "close": 1}],
                       {"close": 71000, "change": -2.1})
    assert s["name"] == "삼성전자" and s["close"] == 71000
    assert s["action_ko"] == "매수 관심" and s["candles"][0]["time"] == "2026-06-01"


def test_dashboard_has_watchlist_edit_ui():
    """편집 UI 마커 — 검색 ＋담기 / 카드 －삭제 / 저장 JS가 템플릿에 존재.
    tests/test_dashboard.py의 기존 import(render_dashboard)와 _stock() 헬퍼를 재사용한다."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    for marker in ("saveWatch", "addStock", "delStock", "wadd", "wdel"):
        assert marker in html, marker + " 누락"


def test_dashboard_search_detects_us_ticker():
    """검색 US 티커 감지(Task 13) — 대문자 티커 입력 시 '담기(US)' 제안 JS + 담기 핸들러 마커."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    for marker in ("addUS", "(US)"):
        assert marker in html, marker + " 누락"


import shutil
import subprocess

import pytest

_needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                 reason="node 미설치 — JS 실행 스모크 생략")


@_needs_node
def test_dashboard_inline_js_parses(tmp_path):
    """대시보드 인라인 JS 문법 스모크(2026-07-17 실사고). onclick의 따옴표 이스케이프가
    깨지면 스크립트 전체가 파싱 실패 → 카드·검색·반도체 섹션이 전부 안 뜬다.
    문자열 존재 검사로는 못 잡으므로 node --check로 실제 파싱을 검증한다."""
    html = render_dashboard([_stock()], [{"code": "005930", "name": "삼성전자"}],
                            "2026-06-22")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = next((s for s in scripts if "cardHtml" in s), None)
    assert main, "메인 스크립트 블록을 찾지 못함"
    js = tmp_path / "dash_main.js"
    js.write_text(main, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "대시보드 인라인 JS 문법 오류:\n" + r.stderr


def test_nav_loader_on_all_pages():
    # 페이지 전환 로딩 바(2026-07-13 요청) — 세 페이지 모두 포함돼야 한다
    from backend.report.scanner_page import render_scanner_page
    from backend.report.live_page import render_live_page
    for html in (render_dashboard([], [], "2026-07-13"),
                 render_scanner_page(),
                 render_live_page("000660", "SK하이닉스", "live")):
        assert "navload" in html
        assert "pageshow" in html      # bfcache 복귀 시 잔상 제거
        assert "metaKey" in html       # Cmd/Ctrl+클릭(새 탭)엔 바를 켜지 않음
    from backend.report.dashboard import _NAV_LOADER
    # bfcache 무력화 리스너 금지(리뷰) — 설명 주석은 허용, 등록 구문만 금지
    assert "addEventListener('beforeunload'" not in _NAV_LOADER
