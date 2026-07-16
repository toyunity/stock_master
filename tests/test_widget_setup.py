"""위젯 설치 페이지 — 토큰은 페이지에만(게이트 뒤), 스크립트 본문엔 절대 없음.

스크립트는 node --check로 문법 스모크(test_live_page_js.py 선례 — 문자열 존재
검사로는 SyntaxError로 위젯 전체가 죽는 사고를 못 잡는다)."""
import re
import shutil
import subprocess

import pytest

TOKEN = "t" * 32
BASE = "https://example.ts.net"

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 미설치 — JS 문법 스모크 생략")


def _page():
    from backend.report.widget_setup import render_widget_setup
    return render_widget_setup(TOKEN, BASE)


def _script():
    """페이지에서 스크립트 블록(<pre id="script">…</pre>)을 추출해 unescape."""
    import html as _html
    m = re.search(r'<pre id="script">([\s\S]*?)</pre>', _page())
    assert m, "스크립트 블록 없음"
    return _html.unescape(m.group(1))


def test_page_shows_token_but_script_never_contains_it():
    page, script = _page(), _script()
    assert TOKEN in page                      # 토큰 박스(게이트 뒤라 안전)
    assert TOKEN not in script                # 스크립트는 공유-안전(설계: Keychain)
    assert BASE in script                     # __BASE_URL__ 치환됨
    assert "__BASE_URL__" not in script


def test_script_has_required_parts():
    s = _script()
    for marker in ("Keychain", "timeoutInterval", "FileManager.local",
                   "refreshAfterDate", "mode=refresh", "widgetFamily",
                   "isAuth", "토큰 다시 입력"):
        assert marker in s, marker + " 누락"


@needs_node
def test_script_syntax_ok(tmp_path):
    p = tmp_path / "StockMaster.mjs"   # .mjs = 항상 ESM 파싱 — 최상위 await가 node<22.7에서도 통과
    p.write_text(_script(), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_route_serves_page_and_503_without_token(tmp_path):
    from fastapi.testclient import TestClient
    from backend.config import Settings
    from backend.api.app import create_app
    s = Settings(cache_dir=str(tmp_path), flow_mode="demo", widget_token=TOKEN,
                 kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    c = TestClient(create_app(s))
    r = c.get("/widget-setup")
    assert r.status_code == 200 and "Scriptable" in r.text
    s2 = Settings(cache_dir=str(tmp_path), flow_mode="demo", widget_token=None,
                  kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    assert TestClient(create_app(s2)).get("/widget-setup").status_code == 503
