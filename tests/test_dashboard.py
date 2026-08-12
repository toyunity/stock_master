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


def test_dashboard_polls_futures_and_renders_fxchip():
    """선물 칩은 지수 칩과 같은 스트립(#market)에 붙는다."""
    html = render_dashboard([_stock()], [{"code": "005930", "name": "삼성전자",
                            "close": 71000, "change": -2.1}], "2026-06-22")
    assert "/api/futures" in html
    assert "fxchip" in html          # 선물 칩 렌더 함수
    # 배지가 실제로 뜨는지(마감/지연 프로듀서가 있는지)는 아래
    # test_dashboard_fxchip_renders_closed_and_stale_badges_not_on_live_chip이 node로 실행 검증한다
    # — ".mbadge" 문자열이 CSS에 있다는 것만으로는 아무것도 만들지 않아도 통과해버린다(리뷰 확정).


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


@_needs_node
def test_dashboard_fxchip_renders_closed_and_stale_badges_not_on_live_chip(tmp_path):
    """마감(o.closed)·지연(o.stale) 배지가 실제로 렌더되고, 라이브 칩(둘 다 없음)엔 안 붙는다 —
    실행 검증(리뷰 확정: 문자열 존재검사(".mbadge" in html)만으론 아무도 stale/closed를
    만들지 않아도 통과해버려 배지가 도달 불가능해도 테스트가 못 잡았다). 둘 다 있으면(예:
    휴장 중 갱신도 실패) 마감이 지연을 덮는다 — 마감 자체가 이미 '라이브 아님'을 말하므로."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = next((s for s in scripts if "cardHtml" in s), None)
    assert main, "메인 스크립트 블록을 찾지 못함"
    fn = _extract_js_function(main, "fxchip")
    harness = fn + """
const out = {
  closed: fxchip({label:'K200선물', price:340.5, rate:-0.3, closed:true}),
  stale: fxchip({label:'나스닥 QQQ', price:487.32, rate:0.1, stale:true}),
  both: fxchip({label:'K200선물', price:340.5, rate:-0.3, closed:true, stale:true}),
  live: fxchip({label:'K200선물', price:340.5, rate:-0.3}),
};
console.log(JSON.stringify(out));
"""
    js = tmp_path / "fxchip_badge_check.js"
    js.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "fxchip 실행 실패:\n" + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert "마감" in out["closed"] and "지연" not in out["closed"]
    assert "지연" in out["stale"] and "마감" not in out["stale"]
    assert "마감" in out["both"] and "지연" not in out["both"]     # 마감이 지연을 덮는다
    assert "마감" not in out["live"] and "지연" not in out["live"]


@_needs_node
def test_dashboard_news_title_cannot_inject_a_placeholder(tmp_path):
    """뉴스 제목이 자리표시자 문자열이어도 치환되면 안 된다 — `.replace()` 체인은 앞서 넣은
    문자열을 뒤 단계가 **다시 스캔**하므로, 데이터를 먼저 넣으면 제목 안의 '__LIB__'에
    400KB 차트 라이브러리가 통째로 주입돼 JSON이 깨지고 메인 스크립트가 전멸한다.

    원천은 한경·연합 RSS다 — 저장소가 통제하지 않는 입력이다(감사 B-F2). 데이터 치환을
    체인 맨 뒤로 옮기면 뒤에 스캔할 단계가 없어 주입이 성립하지 않는다."""
    s = _stock(news=[{"title": "속보 __LIB__ 어쩌구", "link": "https://x/1",
                      "source": "한경", "published": ""}])
    html = render_dashboard([s], [], "2026-06-22")
    # 제목은 원문 그대로, **딱 한 번만** 나와야 한다. 데이터를 맨 뒤로 옮겼으므로 이제
    # 앞선 값들(400KB 라이브러리·패널 JS)이 '__DATA__'를 품고 있으면 거꾸로 데이터가
    # 그 안에 주입된다 — 그때는 미치환 토큰이 남지 않아 개수로만 잡힌다.
    assert html.count("속보 __LIB__ 어쩌구") == 1
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = next((s for s in scripts if "cardHtml" in s), None)
    assert main, "메인 스크립트 블록을 찾지 못함"
    js = tmp_path / "dash_inject.js"
    js.write_text(main, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "제목 주입으로 메인 JS가 깨졌다:\n" + r.stderr


@_needs_node
def test_dashboard_index_chip_marks_server_stale_not_live(tmp_path):
    """/api/market이 갱신에 실패해 옛 값을 주면(stale:true) 지수 칩은 '실시간'이라 우기지 않는다 —
    실행 검증(감사 D-H1: 10시 값이 14시에 '실시간'으로 걸리던 자리).

    벽시계 판정(krIndexLive)만 보던 라벨이 서버가 실은 나이를 우선하는지, 그리고 같은 라벨을
    물려받는 '코스피 온도' 그룹까지 함께 정직해지는지를 본다. 신선한 경우의 라벨은 실행
    시각에 따라 실시간/마감이 갈리므로 둘 중 하나인지만 확인한다(밤에 돌려도 안 깨지게)."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = next((s for s in scripts if "cardHtml" in s), None)
    assert main, "메인 스크립트 블록을 찾지 못함"
    harness = "\n".join(_extract_js_function(main, f)
                        for f in ("krIndexLive", "gadapt", "gdomestic")) + """
let FUT={}, MKT={}, TEMP={items:[{key:'disp',label:'이격도',value:1.2,unit:'%',verdict:'보통'}]};
function fresh(){ const gs=gdomestic();
  return gs.map(function(g){return [g.label, g.items.map(function(x){return x.fresh;})];}); }
MKT={stale:true, kospi:{price:6820.6, rate:-6.37}, kosdaq:{price:791.8, rate:-4.53}};
const staleOut = fresh();
MKT={kospi:{price:6820.6, rate:-6.37}, kosdaq:{price:791.8, rate:-4.53}};
const liveOut = fresh();
console.log(JSON.stringify({stale: staleOut, live: liveOut}));
"""
    js = tmp_path / "gdomestic_stale_check.js"
    js.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "gdomestic 실행 실패:\n" + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    stale = dict((label, fs) for label, fs in out["stale"])
    assert stale["국내 지수"] == ["지연", "지연"], stale
    assert stale["코스피 온도"] == ["지연"], stale        # 같은 봉이므로 함께 지연
    live = dict((label, fs) for label, fs in out["live"])
    assert set(live["국내 지수"]) <= {"실시간", "마감"}, live   # 서버가 안 실으면 벽시계 판정 그대로


@_needs_node
def test_dashboard_index_strip_shows_delay_badge_when_stale(tmp_path):
    """상단 스트립(항상 보이는 면)의 지수 칩도 옛 값이면 '지연' 배지를 단다 — 지수 섹션은
    접힌 <details>라 신선도 줄이 안 보일 수 있다. 선물 칩(fxchip)이 쓰던 배지 그대로."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = next((s for s in scripts if "cardHtml" in s), None)
    harness = _extract_js_function(main, "ix") + """
console.log(JSON.stringify({
  stale: ix({price:6820.6, rate:-6.37}, '코스피', true),
  live:  ix({price:6820.6, rate:-6.37}, '코스피', false),
}));
"""
    js = tmp_path / "ix_badge_check.js"
    js.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "ix 실행 실패:\n" + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert "지연" in out["stale"] and "6,820.6" in out["stale"]
    assert "지연" not in out["live"]


@_needs_node
def test_dashboard_pulse_state_matches_nxt_session_un(tmp_path, monkeypatch):
    """헤더 펄스(marketPulse) — UN(기본, KRX+NXT 통합)에서 NXT 프리·애프터 시간에도
    '장 마감'으로 오표시하지 않는다(2026-07-27 실사용자 리포트: 16:16 NXT 애프터마켓
    거래 중에 장 마감 배지). pulseState(day,hm,h)를 node로 직접 실행해 경계를 표 검증한다
    — /api/prices·build_dashboard를 열어두는 cli._kr_market_open()과 같은 세션 정의를
    쓰므로(session.py), 초록(=live) ⟺ 실시간 데이터가 흐름이 성립해야 한다."""
    from backend.config import settings
    from backend.report.dashboard import render_dashboard
    monkeypatch.setattr(settings, "market_div", "UN")
    html = render_dashboard([], [], "2026-07-27")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = next((s for s in scripts if "cardHtml" in s), None)
    assert main, "메인 스크립트 블록을 찾지 못함"
    fn = _extract_js_function(main, "pulseState")
    assert "장전(NXT)" in fn and "장후(NXT)" in fn   # UN이면 NXT 분기가 실제로 삽입됨
    cases = [
        (2, 7 * 60 + 59, 7), (2, 8 * 60, 8), (2, 9 * 60, 9),
        (2, 15 * 60 + 29, 15), (2, 15 * 60 + 30, 15),
        (2, 19 * 60 + 59, 19), (2, 20 * 60, 20),
        (2, 23 * 60, 23), (2, 3 * 60, 3),
        (0, 11 * 60, 11),   # 일요일 낮
        (0, 23 * 60, 23),   # 일요일 밤 — night 조건(h>=22)엔 요일 가드가 없다(기존 동작 보존,
                            # 이 자체가 선행 버그지만 이번 변경 범위 밖 — 의도적으로 안 건드림을 고정)
    ]
    harness = fn + """
const out = [%s].map(function(c){ return pulseState(c[0],c[1],c[2]); });
console.log(JSON.stringify(out));
""" % ",".join("[%d,%d,%d]" % c for c in cases)
    js = tmp_path / "pulse_state_un.js"
    js.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "pulseState 실행 실패:\n" + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    expected = [
        ["closed", "장 마감"], ["live", "장전(NXT)"], ["live", "장중"],
        ["live", "장중"], ["live", "장후(NXT)"],
        ["live", "장후(NXT)"], ["closed", "장 마감"],
        ["night", "야간·미국장"], ["night", "야간·미국장"],
        ["closed", "장 마감"],   # 일요일 11:00 — day 조건에 안 걸리고 night 조건도 안 걸림
        ["night", "야간·미국장"],   # 일요일 23:00 — night 조건이 요일 무관이라 여기선 뜬다
    ]
    assert out == expected, out


@_needs_node
def test_dashboard_pulse_state_j_matches_regular_session_only(tmp_path, monkeypatch):
    """J(KRX만)면 NXT 프리·애프터 분기가 아예 삽입되지 않고, 09:00~15:30(정규장)만 열린다.
    주의: 15:30 정각은 기존 JS(hm<=930, inclusive)에선 '장중'이었지만 이번 변경으로
    Python _kr_market_open()(원래도 exclusive)과 맞추기 위해 hm<930(exclusive)로 바꿨다 —
    J도 이 1분 경계는 바뀐다(그 밖의 모든 경계는 기존과 동일). 회귀가 아니라 두 화면(펄스·
    폴링)이 같은 순간에 서로 다른 상태를 보여주던 기존 불일치를 없앤 것."""
    from backend.config import settings
    from backend.report.dashboard import render_dashboard
    monkeypatch.setattr(settings, "market_div", "J")
    html = render_dashboard([], [], "2026-07-27")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = next((s for s in scripts if "cardHtml" in s), None)
    assert main, "메인 스크립트 블록을 찾지 못함"
    fn = _extract_js_function(main, "pulseState")
    assert "NXT" not in fn
    assert "hm>=540&&hm<930" in fn   # 정규장 경계는 그대로
    cases = [
        (2, 7 * 60 + 59, 7), (2, 8 * 60, 8), (2, 9 * 60, 9),
        (2, 15 * 60 + 29, 15), (2, 15 * 60 + 30, 15),
        (2, 19 * 60 + 59, 19), (2, 20 * 60, 20),
        (2, 23 * 60, 23), (2, 3 * 60, 3),
        (0, 11 * 60, 11),   # 일요일 낮
    ]
    harness = fn + """
const out = [%s].map(function(c){ return pulseState(c[0],c[1],c[2]); });
console.log(JSON.stringify(out));
""" % ",".join("[%d,%d,%d]" % c for c in cases)
    js = tmp_path / "pulse_state_j.js"
    js.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "pulseState 실행 실패:\n" + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    expected = [
        ["closed", "장 마감"], ["closed", "장 마감"], ["live", "장중"],
        ["live", "장중"], ["closed", "장 마감"],
        ["closed", "장 마감"], ["closed", "장 마감"],
        ["night", "야간·미국장"], ["night", "야간·미국장"],
        ["closed", "장 마감"],
    ]
    assert out == expected, out


def test_dashboard_has_collapsed_options_section_hidden_by_default():
    """옵션 섹션은 접힌 채로, 데이터가 오기 전엔 숨어 있어야 한다 —
    빈 섹션이 '옵션 데이터 없음'처럼 자리를 차지하면 안 된다."""
    from backend.report.dashboard import render_dashboard
    html = render_dashboard([], [], "2026-08-05")
    assert 'id="optsec"' in html
    assert 'style="display:none"' in html.split('id="optsec"')[1][:120]
    assert "<details" in html.split('id="optsec"')[0][-80:]
    assert "open" not in html.split('id="optsec"')[1].split(">")[0]   # 기본 접힘
    assert 'id="opt-chg"' in html and 'id="opt-oi"' in html
    # 증감 차트가 누적보다 **위**에 온다 — 오늘의 신호가 주인공이다
    assert html.index('id="opt-chg"') < html.index('id="opt-oi"')
    assert "loadOptions" in html


def test_dashboard_has_collapsed_vkospi_section_that_is_not_open():
    """VKOSPI 섹션은 **기본 접힘**이고, 펼치기 전엔 조회하지 않는다(지연 로딩).

    다른 섹션(반도체 동향 등)은 즉시 로드지만 이건 다르다 — 안 펼치면 KIS 호출 0건이
    이 설계의 약속이다."""
    from backend.report.dashboard import render_dashboard
    html = render_dashboard([], [], "2026-08-05")
    assert 'id="volsec"' in html
    head = html.split('id="volsec"')[1].split(">")[0]
    assert "open" not in head                       # 기본 접힘
    assert 'id="vk-chart"' in html and 'id="vk-now"' in html
    assert "loadVkospi" in html
    # 최상위에서 즉시 부르는 줄이 없어야 한다. 다른 로더는 `loadSemi(); setInterval(...)`
    # 처럼 줄 맨 앞에서 바로 부른다 — 이건 토글 핸들러 안에서만 불려야 한다.
    # (실제 보장은 tests/test_vol_panel_js.py가 fetch 횟수로 잰다. 여기선 값싼 대조.)
    assert "\nloadVkospi();" not in html
    assert "addEventListener('toggle'" in html


def test_every_dashboard_section_starts_collapsed():
    """홈 진입 시 섹션은 전부 접혀 있어야 한다(사용자 요청 2026-08-05).

    <details>의 열림 상태는 새로고침에 안 남는다 — 마크업에 open이 있으면 매번
    다시 펼쳐진다. 섹션이 넷으로 늘어난 뒤로는 펼친 채로 두면 관심종목 카드가
    화면 한참 아래로 밀린다. 새 섹션을 추가할 때도 이 불변식을 지킨다."""
    import re

    from backend.report.dashboard import render_dashboard
    html = render_dashboard([], [], "2026-08-05")
    tags = re.findall(r"<details[^>]*>", html)
    assert tags, "섹션이 하나도 없다"
    opened = [t for t in tags if re.search(r"\bopen\b", t)]
    assert opened == [], "펼친 채로 시작하는 섹션이 있다: %s" % opened


@_needs_node
def test_dashboard_pulse_shows_relative_time_of_last_market_fetch(tmp_path):
    """헤더 시장상태 펄스(#mkpulse/#mktxt) 옆 #mkago — /api/market이 마지막으로 성공한
    시점을 ago()로 보여준다(theme.py .ago 규약: 절대시각(.fresh)의 대체재가 아니라
    "지금도 살아 있는가"를 말하는 병기). 아직 한 번도 안 받았으면 빈 문자열."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    assert 'id="mkago"' in html and 'class="ago" id="mkago"' in html
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = next((s for s in scripts if "cardHtml" in s), None)
    assert main, "메인 스크립트 블록을 찾지 못함"
    assert "function ago(" in main, "__AGO_JS__가 치환되지 않았다"
    ago_fn = _extract_js_function(main, "ago")
    paint_fn = _extract_js_function(main, "paintMkAgo")
    harness = ago_fn + paint_fn + """
let _lastMarketAt = null;
const els = {mkago: {textContent: ''}};
global.document = {getElementById: id => els[id] || null};
paintMkAgo();
const before = els.mkago.textContent;
_lastMarketAt = Date.now() - 5000;
paintMkAgo();
const after = els.mkago.textContent;
console.log(JSON.stringify({before, after}));
"""
    js = tmp_path / "mkago_check.js"
    js.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "paintMkAgo 실행 실패:\n" + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["before"] == "", out
    assert out["after"] not in ("", "undefined"), out
