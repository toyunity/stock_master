from harness.cmd import verify


def test_screens_cover_every_user_facing_page():
    """화면을 추가하면 여기도 같이 늘려야 한다 — 아이폰 폭 회귀 가드를 빠뜨리지 않게.
    uslive는 2026-08-06 US 상세 화면 추가분."""
    names = {s[0] for s in verify.SCREENS}
    assert names == {"live", "uslive", "dashboard", "scanner", "widget", "login"}


def test_login_html_importable():
    # login 화면 소스가 실제로 임포트되는 HTML 문자열이어야 한다(라우트 미의존)
    src = dict((s[0], s) for s in verify.SCREENS)["login"]
    assert src[1] == "html"
    assert "<!doctype html" in src[2].lower()
