"""탭바 자동숨김 JS 실행 스모크 — node로 실제 돌려 방향과 안전장치를 못박는다.

스크린샷으로는 못 잡는다: 하니스 CDP가 캡처 직전 `#tabbar{display:none}`을 주입하고,
숨김이 transform이라 정지 화면엔 흔적이 없다. 그래서 스크롤 이벤트를 직접 먹인다.
"""
import json
import shutil
import subprocess

import pytest

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 미설치 — JS 실행 스모크 생략")

_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(s => s.indexOf('SHOW_ON') >= 0);
if (!code) { console.log(JSON.stringify({error: '자동숨김 스크립트 없음'})); process.exit(0); }

function classList(){
  const set = new Set();
  return {
    add: c => set.add(c), remove: c => set.delete(c), contains: c => set.has(c),
    toggle: (c, f) => { if (f === undefined) f = !set.has(c);
                        if (f) set.add(c); else set.delete(c); return f; },
  };
}
const bar = {id: 'tabbar', classList: classList()};
let onScroll = null, onShow = null;
const docEl = {scrollHeight: 5000};
global.document = {
  getElementById: id => (id === 'tabbar' ? bar : null),
  documentElement: docEl,
};
global.window = {
  pageYOffset: 0, innerHeight: 800,
  requestAnimationFrame: f => f(),
  addEventListener: (t, f) => { if (t === 'scroll') onScroll = f;
                                if (t === 'pageshow') onShow = f; },
};
eval(code);
if (!onScroll) { console.log(JSON.stringify({error: 'scroll 리스너 미등록'})); process.exit(0); }

const log = [];
function to(y, label){ global.window.pageYOffset = y; onScroll({}); log.push([label, bar.classList.contains('hid')]); }

to(200, '아래로 200');          // 내림 → 나온다
to(150, '위로 50');             // 올림 → 숨는다
to(154, '위로 뒤 미세 +4');      // 데드존 미만 → 그대로 숨은 채
to(300, '다시 아래로');          // 내림 → 다시 나온다
to(280, '위로 20');             // 올림 → 숨는다
onShow && onShow({});           // bfcache 복귀
log.push(['pageshow 복귀', bar.classList.contains('hid')]);

// 스크롤이 안 생기는 짧은 페이지: 어떤 방향으로도 숨으면 안 된다
docEl.scrollHeight = 820;       // innerHeight 800 + 60 이하
global.window.pageYOffset = 0; onScroll({});
to(10, '짧은 페이지 아래로');
to(0, '짧은 페이지 위로');

// 고무줄(오버스크롤) 구간은 방향으로 치지 않는다
docEl.scrollHeight = 5000;
global.window.pageYOffset = 400; onScroll({});   // 기준점 잡기
bar.classList.remove('hid');
to(-40, '상단 고무줄');
to(9999, '하단 고무줄');

console.log(JSON.stringify({log}));
"""


def _run(tmp_path):
    from backend.report.theme import TABBAR
    html = tmp_path / "tabbar.html"
    html.write_text("<html><body>" + TABBAR + "</body></html>", encoding="utf-8")
    js = tmp_path / "harness.js"
    js.write_text(_HARNESS, encoding="utf-8")
    p = subprocess.run(["node", str(js), str(html)],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert "error" not in out, out["error"]
    return dict(out["log"])


@needs_node
def test_tabbar_hides_on_scroll_up_and_shows_on_scroll_down(tmp_path):
    """마스터 지정 방향: 내리면 나오고 올리면 숨는다(흔한 앱과 반대)."""
    got = _run(tmp_path)
    assert got["아래로 200"] is False
    assert got["위로 50"] is True
    assert got["다시 아래로"] is False
    assert got["위로 20"] is True


@needs_node
def test_tabbar_ignores_jitter_and_overscroll(tmp_path):
    """데드존 미만 흔들림과 고무줄 구간은 방향으로 치지 않는다 — 아이폰에서 깜빡임 방지."""
    got = _run(tmp_path)
    assert got["위로 뒤 미세 +4"] is True       # 숨은 상태 유지(+4px로 안 튀어나옴)
    assert got["상단 고무줄"] is False          # 숨기지 않음
    assert got["하단 고무줄"] is False


@needs_node
def test_tabbar_never_hides_on_unscrollable_page(tmp_path):
    """짧은 페이지에서 숨으면 되돌릴 스크롤이 없어 내비게이션이 영영 사라진다."""
    got = _run(tmp_path)
    assert got["짧은 페이지 아래로"] is False
    assert got["짧은 페이지 위로"] is False


@needs_node
def test_tabbar_returns_on_bfcache_restore(tmp_path):
    got = _run(tmp_path)
    assert got["pageshow 복귀"] is False


def test_autohide_ships_on_every_page_with_a_tabbar():
    """TABBAR를 심는 모든 페이지가 실제로 이 스크립트를 달고 나가는지 — 한 곳에서
    만든 문자열이 네 페이지에 인라인되므로 치환 누락은 렌더 결과로만 잡힌다."""
    from backend.report.dashboard import render_dashboard
    from backend.report.live_page import render_live_page
    from backend.report.scanner_page import render_scanner_page
    from backend.report.us_page import render_us_page
    pages = {
        "dashboard": render_dashboard([], [], "2026-08-07", pwa=True),
        "scanner": render_scanner_page(),
        "live": render_live_page("000660", "SK하이닉스", "live"),
        "us": render_us_page("SKHY", "SK하이닉스 DR"),
    }
    for name, html in pages.items():
        assert 'id="tabbar"' in html, name
        assert "SHOW_ON" in html, name          # 자동숨김 스크립트
        assert "#tabbar.hid" in html, name      # 숨김 CSS
        assert "__TABBAR__" not in html, name   # 치환 누락


def test_tabbar_hide_uses_transform_not_display():
    """display:none/높이 변경으로 숨기면 body 패딩이 흔들려 본문이 튄다."""
    from backend.report.theme import TABBAR
    hid = [ln for ln in TABBAR.splitlines() if ln.startswith("#tabbar.hid")]
    assert len(hid) == 1, TABBAR
    assert "translateY" in hid[0]
    assert "display" not in hid[0] and "height" not in hid[0]
