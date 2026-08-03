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
    """편집 UI 마커 — 검색 ＋담기(addStock/addUS)·관리 리스트 저장(saveItems, items 계약)이 존재하고,
    카드의 삭제버튼(구 delStock/wdel)은 관리 리스트로 이전돼 카드에서 제거됐다(Task 14)."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    for marker in ("saveItems", "addStock", "addUS", "wadd"):
        assert marker in html, marker + " 누락"
    # 카드 편집버튼 제거 — 삭제/순서변경/보유는 관리 리스트가 담당(카드는 순서만 반영)
    assert "delStock(" not in html, "카드 삭제 핸들러(delStock)가 남아있음 — 관리 리스트로 이전해야 함"
    assert 'class="wdel"' not in html, "카드 삭제버튼(wdel)이 남아있음"
    assert 'body:JSON.stringify({codes})' not in html, "구 {codes} 저장 계약 잔존(현재 서버는 400)"


def test_dashboard_manage_list_button_fallback():
    """관리 리스트(Task 14) — 검색창 위 컨테이너 + 행별 핸들·▲▼·×·[보유] 버튼 폴백이 항상 렌더되고
    핸들러가 정의된다(드래그 없이도 순서변경·삭제·보유편집 동작)."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    assert 'id="manage"' in html                       # 관리 리스트 컨테이너
    assert html.index('id="manage"') < html.index('class="search"')  # 검색창 위
    for fn in ("loadItems", "renderManage", "moveItem", "delItem", "editHold", "saveHold"):
        assert fn in html, fn + " 핸들러 누락"
    assert "⠿" in html                                 # 드래그 핸들 자리(버튼 폴백은 별개로 항상 동작)


def test_dashboard_search_detects_us_ticker():
    """검색 US 티커 감지(Task 13) — 대문자 티커 입력 시 '담기(US)' 제안 JS + 담기 핸들러 마커."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    for marker in ("addUS", "(US)"):
        assert marker in html, marker + " 누락"


def test_dashboard_drag_swipe_enhancement():
    """드래그 순서변경·스와이프 삭제(Task 15) — Pointer Events 향상이 편집 블록(renderManage와
    같은 <script>)에 얹히고 try/catch로 감싸, 향상 코드가 런타임 실패해도 ▲▼·× 버튼 폴백이
    유지된다(progressive enhancement). 같은 블록이라야 test_dashboard_inline_js_parses의
    node --check 파스 게이트가 드래그 JS까지 덮어 파스 오류 시에도 폴백이 지켜진다."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    edit = next((s for s in scripts if "renderManage" in s), "")
    main = next((s for s in scripts if "cardHtml" in s), "")
    assert edit and main, "편집/메인 블록 분리 실패"
    # Pointer Events 드래그/스와이프 마커 — 편집 블록 안에(메인 블록 오염 금지)
    for marker in ("pointerdown", "pointermove", "pointerup", "setPointerCapture"):
        assert marker in edit, marker + " 누락(편집 블록)"
        assert marker not in main, marker + " 가 메인 블록으로 새어나감"
    # 향상 초기화를 try/catch로 격리 — 런타임 실패 시 버튼 폴백 유지.
    # 드래그 초기화(setPointerCapture)를 실제로 감싸는지 고정(기존 loadItems try/catch와 구분).
    assert re.search(r"try\s*\{[\s\S]*setPointerCapture[\s\S]*\}\s*catch\s*\(", edit), \
        "드래그 초기화가 try/catch로 감싸이지 않음(향상 실패 시 버튼 폴백 유지 불가)"
    # 커밋 경로 재사용 — 스와이프=삭제(delItem·최소1개 가드), 드롭=순서저장(saveItems)
    for fn in ("delItem", "saveItems", "moveItem"):
        assert fn in edit, fn + " 누락(버튼 폴백/커밋 경로)"


import json
import shutil
import subprocess

import pytest

_needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                 reason="node 미설치 — JS 실행 스모크 생략")


@_needs_node
def test_dashboard_inline_js_parses(tmp_path):
    """대시보드 인라인 JS 문법 스모크(2026-07-17 실사고) — 메인 블록 + 편집(관리 리스트) 블록
    둘 다 node --check. onclick 이스케이프가 깨지면 스크립트 전체가 파싱 실패 → 섹션이 전부
    안 뜬다. 편집 로직은 별도 <script>로 분리돼 드래그/스와이프(Task 15)가 죽어도 격리된다."""
    html = render_dashboard([_stock()], [{"code": "005930", "name": "삼성전자"}],
                            "2026-06-22")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = next((s for s in scripts if "cardHtml" in s), None)
    edit = next((s for s in scripts if "renderManage" in s), None)
    assert main, "메인 스크립트 블록을 찾지 못함"
    assert edit, "편집(관리 리스트) 스크립트 블록을 찾지 못함"
    assert main != edit, "편집 블록이 메인 블록과 분리되지 않음(별도 <script> 필요)"
    for fname, src in (("dash_main.js", main), ("dash_edit.js", edit)):
        js = tmp_path / fname
        js.write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        assert r.returncode == 0, fname + " 인라인 JS 문법 오류:\n" + r.stderr


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


def test_dashboard_polls_futures_and_has_stale_badge_style():
    """선물 칩은 지수 칩과 같은 스트립(#market)에 붙고, '지연' 배지 스타일을 갖는다."""
    html = render_dashboard([_stock()], [{"code": "005930", "name": "삼성전자",
                            "close": 71000, "change": -2.1}], "2026-06-22")
    assert "/api/futures" in html
    assert "fxchip" in html          # 선물 칩 렌더 함수
    assert ".mbadge" in html         # 지연 배지 CSS


def _extract_js_function(script, name):
    """중괄호 깊이를 세어 함수 소스만 잘라낸다(정규식만으로는 중첩 {}에서 깨짐)."""
    start = script.index("function " + name + "(")
    brace = script.index("{", start)
    depth, i = 0, brace
    for i in range(brace, len(script)):
        if script[i] == "{":
            depth += 1
        elif script[i] == "}":
            depth -= 1
            if depth == 0:
                break
    return script[start:i + 1]


@_needs_node
def test_dashboard_fxchip_null_rate_renders_dash_not_fake_zero(tmp_path):
    """rate:null(나스닥 QQQ 프리오픈 롤오버 등)을 '0.00%(보합)'로 꾸미지 않는다 — 실행 검증.

    문자열 존재 검사가 아니라 렌더된 실제 HTML 대시보드 소스에서 fxchip 함수 본문을 그대로
    잘라내 node로 실행해 확인한다(test_live_page_js.py와 같은 관행). 진짜 0.00%(rate===0,
    보합)는 그대로 표시돼야 한다 — 둘을 구분 못 하면 회귀다."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = next((s for s in scripts if "cardHtml" in s), None)
    assert main, "메인 스크립트 블록을 찾지 못함"
    fn = _extract_js_function(main, "fxchip")
    harness = fn + """
const out = {
  nullRate: fxchip({label:'나스닥 QQQ', price:687.99, rate:null}),
  zeroRate: fxchip({label:'테스트', price:100, rate:0}),
};
console.log(JSON.stringify(out));
"""
    js = tmp_path / "fxchip_check.js"
    js.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "fxchip 실행 실패:\n" + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert "–" in out["nullRate"] and "0.00%" not in out["nullRate"], out["nullRate"]
    assert "0.00%" in out["zeroRate"], out["zeroRate"]     # 진짜 보합은 그대로
