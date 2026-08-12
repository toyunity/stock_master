"""스캐너 화면 인라인 JS 문법 게이트.

다른 화면엔 전부 있는데(dashboard `node --check`, live/us/패널은 node 실행) 스캐너만
빠져 있었다 — 렌더 결과에 <script> 블록이 4개(자체 103줄 + 탭바·네비로더·PWA)나 들어가는데
문자열 존재 검사만 있었다. 따옴표·이스케이프 하나가 깨지면 블록 전체가 파싱 실패해
화면이 통째로 비는데, 나머지 테스트는 전부 통과한다(2026-07-17 대시보드 실사고와 같은 것).
"""
import re
import shutil
import subprocess

import pytest

from backend.report.scanner_page import render_scanner_page

_needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                 reason="node 미설치 — JS 문법 게이트 생략")


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
