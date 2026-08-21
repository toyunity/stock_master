"""스캐너 화면 인라인 JS 문법 게이트.

다른 화면엔 전부 있는데(dashboard `node --check`, live/us/패널은 node 실행) 스캐너만
빠져 있었다 — 렌더 결과에 <script> 블록이 4개(자체 103줄 + 탭바·네비로더·PWA)나 들어가는데
문자열 존재 검사만 있었다. 따옴표·이스케이프 하나가 깨지면 블록 전체가 파싱 실패해
화면이 통째로 비는데, 나머지 테스트는 전부 통과한다(2026-07-17 대시보드 실사고와 같은 것).
"""
import json
import re
import shutil
import subprocess

import pytest

from backend.report.scanner_page import render_scanner_page

_needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                 reason="node 미설치 — JS 문법 게이트 생략")


def _extract_js_function(script, name):
    """중괄호 깊이를 세어 함수 소스만 잘라낸다(test_dashboard.py와 같은 관행)."""
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
def test_scanner_inline_js_parses(tmp_path):
    html = render_scanner_page()
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert len(scripts) == 4, "스크립트 블록 수가 바뀌었다(%d) — 게이트 범위 확인" % len(scripts)
    for i, src in enumerate(scripts):
        js = tmp_path / ("scanner_%d.js" % i)
        js.write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        assert r.returncode == 0, "스캐너 인라인 JS 문법 오류(블록 %d):\n%s" % (i, r.stderr)


@_needs_node
def test_scanner_relative_time_next_to_asof(tmp_path):
    """조회 시각(#asof, 절대시각) 옆 #asof-ago(상대시간) — theme.py .ago 규약대로
    대체가 아니라 병기. D.asof는 서버가 주는 'HH:MM:SS'(KST 벽시계, 날짜 없음)라
    오늘 날짜와 합쳐 ago()에 넘겨야 한다 — 실제 실행으로 검증한다."""
    html = render_scanner_page()
    assert 'id="asof-ago"' in html and 'class="ago"' in html
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    main = scripts[0]
    assert "function ago(" in main, "__AGO_JS__가 치환되지 않았다"
    ago_fn = _extract_js_function(main, "ago")
    conv_fn = _extract_js_function(main, "agoFromHms")
    harness = ago_fn + conv_fn + """
const past = new Date(Date.now() - 10*60000);   // 10분 전
const pad = x => String(x).padStart(2,'0');
const hms = pad(past.getHours())+':'+pad(past.getMinutes())+':'+pad(past.getSeconds());
console.log(JSON.stringify({out: agoFromHms(hms), empty: agoFromHms('')}));
"""
    js = tmp_path / "asofago_check.js"
    js.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "agoFromHms 실행 실패:\n" + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["empty"] == "", out
    assert re.search(r"\d+분 전", out["out"]), out
