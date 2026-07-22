from harness.cmd import verify


def test_screens_cover_five():
    names = {s[0] for s in verify.SCREENS}
    assert names == {"live", "dashboard", "scanner", "widget", "login"}


def test_login_html_importable():
    # login 화면 소스가 실제로 임포트되는 HTML 문자열이어야 한다(라우트 미의존)
    src = dict((s[0], s) for s in verify.SCREENS)["login"]
    assert src[1] == "html"
    assert "<!doctype html" in src[2].lower()
