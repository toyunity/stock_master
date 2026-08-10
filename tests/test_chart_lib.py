"""차트 라이브러리가 **진짜로** 실려 나가는지 — 자리표시자 검사보다 한 걸음 더.

`__LIB__` 사고(2026-08-06) 뒤에 넣은 가드는 '치환 안 된 __PLACEHOLDER__가 남았나'만
본다. 그건 그 사고 하나는 막지만 같은 계열의 나머지를 못 막는다 —
파일이 비었거나, 잘렸거나, 엉뚱한 파일이 들어가도 자리표시자는 안 남기 때문이다.
여기서는 페이지에 박힌 스크립트를 **node로 실제 실행해** createChart가 함수로
튀어나오는지 확인한다. 그게 화면이 정말로 기대하는 계약이다.

node 스모크가 LightweightCharts를 가짜로 주입하는 것과 정반대 방향의 테스트다:
저쪽은 가짜를 넣고 페이지 로직을 보고, 여기선 진짜 라이브러리만 떼어내 본다.
"""
import json
import shutil
import subprocess

import pytest

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 미설치 — JS 실행 스모크 생략")

# 라이브러리 조각을 고르는 표식. 페이지 로직에는 절대 안 나오고(전역을 만드는 쪽은
# 라이브러리뿐), 파일이 잘리면 파일 끝에 있는 이 구문부터 사라진다.
_MARK = "window.LightweightCharts="

_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const lib = scripts.find(s => s.indexOf('window.LightweightCharts=') >= 0);
if (!lib) { console.log(JSON.stringify({error: '라이브러리 조각이 페이지에 없다'})); process.exit(0); }
// 브라우저 전역 최소 스텁. 차트를 만들지 않고 로드만 하므로 이 정도면 충분하다.
// navigator는 **있던 것도 지우고 우리 것으로 덮는다** — node 21+는 전역 navigator를
// 주고 node 20은 안 준다. 그대로 두면 로컬(23)과 CI(20)가 서로 다른 코드를 타서,
// 로컬만 초록이고 CI만 빨간 상황이 생긴다(2026-08-10 실제로 그렇게 깨졌다).
delete globalThis.navigator;
global.window = {};
global.navigator = {userAgent: 'node'};
global.document = {};
try { eval(lib); } catch (e) {
  console.log(JSON.stringify({error: '라이브러리 실행 실패: ' + e.message})); process.exit(0);
}
const L = global.window.LightweightCharts;
console.log(JSON.stringify({
  bytes: lib.length,
  createChart: typeof (L || {}).createChart,
  version: (L && typeof L.version === 'function') ? L.version() : null,
}));
"""

# (이름, 렌더 호출) — __LIB__를 심는 세 화면 전부
_PAGES = ("dashboard", "live", "us")


def _render(name: str) -> str:
    if name == "dashboard":
        from backend.report.dashboard import render_dashboard
        return render_dashboard([], [], "2026-08-10")
    if name == "live":
        from backend.report.live_page import render_live_page
        return render_live_page("005930", "삼성전자", "demo")
    from backend.report.us_page import render_us_page
    return render_us_page("SKHY", "SK하이닉스 DR")


def _probe(tmp_path, name: str) -> dict:
    html = tmp_path / (name + ".html")
    html.write_text(_render(name), encoding="utf-8")
    js = tmp_path / "harness.js"
    js.write_text(_HARNESS, encoding="utf-8")
    p = subprocess.run(["node", str(js), str(html)],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


@needs_node
@pytest.mark.parametrize("page", _PAGES)
def test_chart_library_actually_runs_and_exposes_create_chart(tmp_path, page):
    """페이지에 박힌 라이브러리를 실행해 createChart가 함수로 나와야 한다."""
    got = _probe(tmp_path, page)
    assert "error" not in got, "%s: %s" % (page, got.get("error"))
    assert got["createChart"] == "function", got
    assert got["version"], got            # 버전 문자열이 나와야 진짜 그 라이브러리다
    # 잘린 파일 대비 — 정상은 16만 바이트대다. 자릿수만 확인한다(버전 올리면 변한다).
    assert got["bytes"] > 100_000, got


@pytest.mark.parametrize("page", _PAGES)
def test_page_calls_the_api_we_verified(tmp_path, page):
    """검증한 API가 화면이 실제로 부르는 API여야 한다 — 검사와 사용처가 어긋나면
    라이브러리는 멀쩡한데 화면만 죽는 상태를 통과시킨다."""
    assert "LightweightCharts.createChart" in _render(page)


@pytest.mark.parametrize("page", _PAGES)
def test_library_marker_survives_the_render(page):
    """node 없는 환경에서도 도는 최소 가드 — 치환 자체가 일어났는지."""
    html = _render(page)
    assert _MARK in html, (
        "%s 화면에 차트 라이브러리가 없다(표식 %r 없음). "
        "__LIB__ 치환 누락이거나 lightweight-charts.js가 비었/잘렸을 수 있다. "
        "화면에 남은 __LIB__: %s"
        % (page, _MARK, "있음" if "__LIB__" in html else "없음"))
