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


def test_script_has_pnl_2line_parts():
    """위젯 2줄 보유/수익 재디자인 마커(설계 §5) — 실선·예산·통화·수익색."""
    s = _script()
    for marker in ("pnl", "addSpacer", "addDivider", "budget",
                   "planCapacity", "fmtMoney", "pnlColor",
                   '"USD"', "boldSystemFont(14)"):
        assert marker in s, marker + " 누락"


def _capacity_js():
    """세로예산 순수 함수(planCapacity) 블록만 잘라낸다 — node 단위 실행용(설계 §207)."""
    m = re.search(r"// <capacity>([\s\S]*?)// </capacity>", _script())
    assert m, "capacity 블록 없음"
    return m.group(1)


@needs_node
def test_capacity_no_silent_truncation(tmp_path):
    """블로커 회귀 방지(§137/§207): 큰 위젯 + 10종목 전부 보유 →
    세로예산 컷 + '+N종목' 정확(drawn+more===길이, more>0 — 무경고 잘림 없음).
    고정 max=10이면 하위가 무경고로 잘렸다 → 실제 그린 개수 기준 산정을 JS 단위로 못박음."""
    harness = _capacity_js() + """
const items = [];
for (let i = 0; i < 10; i++) items.push({ shares: 1, avg: 100 });
const big = planCapacity(items, 290);   // 큰 위젯
const mid = planCapacity(items, 110);   // 중간 위젯
function bad(m){ console.error(m); process.exit(1); }
if (big.drawn + big.more !== 10) bad("big sum " + JSON.stringify(big));
if (!(big.more > 0)) bad("big more " + JSON.stringify(big));
if (!(big.drawn > 0)) bad("big drawn " + JSON.stringify(big));
if (mid.drawn + mid.more !== 10) bad("mid sum " + JSON.stringify(mid));
if (!(mid.more > 0)) bad("mid more " + JSON.stringify(mid));
if (!(big.drawn > mid.drawn)) bad("big should fit more than mid");
// shares=0/null 은 '시세만'(1줄), 보유(shares>0)는 2줄 — 예산 코스트가 실제로 갈려야(설계 §49).
// 단일 항목은 1줄/2줄 모두 예산에 들어가 구분 불가 → 예산 경계를 넘기는 10항목으로 팩킹 차이를 못박음.
function mk(n, t){ var a = []; for (var i = 0; i < n; i++) a.push(Object.assign({}, t)); return a; }
const z = planCapacity(mk(10, {shares:0, avg:100}), 110).drawn;   // 0주 = 시세만(1줄)
const nn = planCapacity(mk(10, {shares:null}), 110).drawn;         // 미보유(1줄)
const h = planCapacity(mk(10, {shares:1, avg:100}), 110).drawn;    // 보유(2줄)
if (z !== nn) bad("shares=0 must pack like shares=null (price-only 1-line) z=" + z + " nn=" + nn);
if (!(z > h)) bad("1-line items must pack more than 2-line held z=" + z + " h=" + h);
console.log("OK", big.drawn, mid.drawn, z, h);
"""
    p = tmp_path / "cap.mjs"
    p.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout


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
