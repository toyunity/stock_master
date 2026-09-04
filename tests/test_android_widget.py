"""갤럭시(안드로이드) 위젯 — 설치 페이지 갤럭시 섹션·APK 라우트·theme.py 색 드리프트.

설계: docs/superpowers/specs/2026-09-04-android-widget-design.md
- 딥링크 stockmaster://setup?base=…&token=… 는 페이지(게이트 뒤)에만 있고 스크립트 블록엔 토큰이 없다.
- APK 버튼은 파일이 있을 때만(없으면 `make android` 안내). 라우트는 파일 없으면 404, 있으면 APK MIME.
- Colors.kt는 theme.py 토큰의 복사본 — 값이 어긋나면 여기서 먼저 깨진다.
"""
import html as _html
import os
import re
import urllib.parse

TOKEN = "t" * 32
BASE = "https://example.ts.net"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLORS_KT = os.path.join(ROOT, "android", "app", "src", "main", "kotlin",
                         "com", "toyunity", "stockmaster", "widget", "Colors.kt")


def _page(apk=False):
    from backend.report.widget_setup import render_widget_setup
    return render_widget_setup(TOKEN, BASE, apk_available=apk)


def test_android_section_has_deeplink_with_encoded_token_and_base():
    page = _page()
    link = "stockmaster://setup?base=%s&token=%s" % (
        urllib.parse.quote(BASE, safe=""), urllib.parse.quote(TOKEN, safe=""))
    assert _html.escape(link) in page                 # href는 HTML 이스케이프(& → &amp;)
    assert "갤럭시" in page and "절전 예외 앱" in page


def test_apk_button_only_when_file_exists():
    assert 'href="/widget-setup/android.apk"' not in _page(apk=False)
    assert "make android" in _page(apk=False)
    assert 'href="/widget-setup/android.apk"' in _page(apk=True)


def test_script_block_still_has_no_token():
    """갤럭시 섹션(토큰이 든 링크)이 스크립트 블록을 오염시키지 않는다 — 치환 순서 규칙."""
    m = re.search(r'<pre id="script">([\s\S]*?)</pre>', _page(apk=True))
    assert m and TOKEN not in _html.unescape(m.group(1))


def _client(tmp_path, monkeypatch, apk_path):
    from fastapi.testclient import TestClient
    from backend.config import Settings, settings as gs
    from backend.api.app import create_app
    monkeypatch.setattr(gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(gs, "default_account", "master@gmail.com")
    s = Settings(cache_dir=str(tmp_path), flow_mode="demo", default_account="master@gmail.com",
                 android_apk_path=apk_path, kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    return TestClient(create_app(s))


def test_apk_route_404_without_file_then_200_with_file(tmp_path, monkeypatch):
    apk = tmp_path / "StockMasterWidget.apk"
    c = _client(tmp_path, monkeypatch, str(apk))
    assert c.get("/widget-setup/android.apk").status_code == 404
    assert 'href="/widget-setup/android.apk"' not in c.get("/widget-setup").text   # 파일 없으면 버튼도 없다
    apk.write_bytes(b"PK\x03\x04fake-apk")
    r = c.get("/widget-setup/android.apk")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.android.package-archive")
    assert r.content == b"PK\x03\x04fake-apk"
    assert "StockMasterWidget.apk" in r.headers["content-disposition"]   # 스펙 §서버 변경 2
    assert r.headers["cache-control"] == "no-store"
    assert 'href="/widget-setup/android.apk"' in c.get("/widget-setup").text


def _theme_tokens():
    """theme.py의 --up/--down/--flat/--warn 값 — 첫 두 개가 (라이트, 다크)."""
    from backend.report import theme
    src = open(theme.__file__, encoding="utf-8").read()
    found = {}
    for name, hexv in re.findall(r"--(up|down|flat|warn):\s*(#[0-9a-fA-F]{6})", src):
        found.setdefault(name, []).append(hexv.lower())
    return found


def test_kotlin_colors_match_theme_tokens():
    assert os.path.isfile(COLORS_KT), COLORS_KT
    kt = open(COLORS_KT, encoding="utf-8").read().lower()
    tokens = _theme_tokens()
    for name in ("up", "down", "flat", "warn"):
        assert len(tokens[name]) >= 2, name                      # 라이트 + 다크
        light, dark = tokens[name][0][1:], tokens[name][1][1:]
        # 슬롯 단위 대조 — UP/DOWN 을 서로 바꿔도 통과하던 '어딘가에 있음' 검사 보강(리뷰 2026-09-04)
        pat = r"val %s = colorprovider\(color\(0xff%s\), color\(0xff%s\)\)" % (name.lower(), light, dark)   # kt는 소문자화됨
        assert re.search(pat, kt), "%s (라이트 #%s, 다크 #%s) 슬롯이 Colors.kt에 없음" % (name, light, dark)
