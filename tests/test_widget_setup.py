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


def test_setup_shows_account_token(tmp_path, monkeypatch):
    """세션 없음(인증 비활성) → default 계정 토큰을 발급해 페이지 렌더(설계 2026-07-17).
    토큰원이 settings.widget_token이 아니라 userstore.ensure_token(email)로 이동.
    userstore·_req_email이 전역 settings를 읽으므로 전역을 tmp로 격리(test_auth 선례)."""
    import html as _html
    from fastapi.testclient import TestClient
    from backend.config import Settings, settings as gs
    from backend.api.app import create_app
    from backend.flow import userstore
    monkeypatch.setattr(gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(gs, "default_account", "master@gmail.com")
    s = Settings(cache_dir=str(tmp_path), flow_mode="demo", default_account="master@gmail.com",
                 kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    c = TestClient(create_app(s))
    r = c.get("/widget-setup")
    assert r.status_code == 200 and "Scriptable" in r.text          # 세션없음→default 계정 토큰
    # 페이지에 실린 토큰이 곧 그 계정의 저장 토큰(발급 후 파일 단일원)
    tok = userstore.get_token("master@gmail.com")
    assert tok and tok in _html.unescape(r.text)


def test_route_503_when_no_account_resolvable(tmp_path, monkeypatch):
    """계정을 해석할 수 없으면(로그인 없음·default_account 없음·allowlist 비어있음) 503.
    .env의 SM_ALLOWED_EMAILS가 새지 않게 전역을 명시적으로 비운다(constraint: 미설정은 값 명시)."""
    from fastapi.testclient import TestClient
    from backend.config import Settings, settings as gs
    from backend.api.app import create_app
    monkeypatch.setattr(gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(gs, "default_account", None)
    monkeypatch.setattr(gs, "allowed_emails", "")
    s2 = Settings(cache_dir=str(tmp_path), flow_mode="demo", default_account=None,
                  allowed_emails="", widget_token=None,
                  kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    assert TestClient(create_app(s2)).get("/widget-setup").status_code == 503


def test_rotate_route_issues_new_token_and_kills_old(tmp_path, monkeypatch):
    """POST /widget-setup/rotate → 새 토큰 반환, 구 토큰 즉시 사망(email_for_token None).
    계정 격리 불변식: 요청자(_req_email) 계정의 토큰만 회전한다."""
    from fastapi.testclient import TestClient
    from backend.config import Settings, settings as gs
    from backend.api.app import create_app
    from backend.flow import userstore
    monkeypatch.setattr(gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(gs, "default_account", "master@gmail.com")
    s = Settings(cache_dir=str(tmp_path), flow_mode="demo", default_account="master@gmail.com",
                 kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    old = userstore.ensure_token("master@gmail.com")
    c = TestClient(create_app(s))
    r = c.post("/widget-setup/rotate")
    assert r.status_code == 200
    new = r.json()["token"]
    assert new and new != old                          # 새 토큰
    assert userstore.email_for_token(new) == "master@gmail.com"
    assert userstore.email_for_token(old) is None      # 구 토큰 즉시 사망
