"""인증 게이트(Google OAuth2 + TOTP) 테스트.

최우선 불변식: 공개 노출 시 '모든 경로가 실제로 잠겼는가'. 신원 검증(allowlist)과
TOTP는 순수 함수로 분리해 단위 테스트하고, 게이트는 전-경로 파라미터라이즈로 지킨다.
"""


# ── verify_userinfo: 이메일 검증 + allowlist (순수 함수) ──────────────
def test_verify_userinfo_allows_verified_allowlisted_email():
    from backend.api.auth import verify_userinfo
    info = {"email": "master@gmail.com", "email_verified": True}
    assert verify_userinfo(info, ["master@gmail.com"]) == "master@gmail.com"


def test_verify_userinfo_rejects_unverified_email():
    from backend.api.auth import verify_userinfo
    info = {"email": "master@gmail.com", "email_verified": False}
    assert verify_userinfo(info, ["master@gmail.com"]) is None


def test_verify_userinfo_rejects_email_not_in_allowlist():
    from backend.api.auth import verify_userinfo
    info = {"email": "intruder@gmail.com", "email_verified": True}
    assert verify_userinfo(info, ["master@gmail.com"]) is None


def test_verify_userinfo_rejects_missing_email():
    from backend.api.auth import verify_userinfo
    assert verify_userinfo({"email_verified": True}, ["master@gmail.com"]) is None


def test_verify_userinfo_is_case_insensitive():
    from backend.api.auth import verify_userinfo
    info = {"email": "Master@Gmail.com", "email_verified": True}
    assert verify_userinfo(info, ["master@gmail.com"]) == "master@gmail.com"


# ── TOTP: 검증 + 시크릿 영속 ──────────────────────────────────────────
def test_verify_totp_accepts_current_code():
    import pyotp
    from backend.api.auth import verify_totp
    secret = pyotp.random_base32()
    assert verify_totp(secret, pyotp.TOTP(secret).now()) is True


def test_verify_totp_rejects_garbage_and_wrong_length():
    import pyotp
    from backend.api.auth import verify_totp
    secret = pyotp.random_base32()
    for bad in ("12345", "abcdef", "", "1234567", None):
        assert verify_totp(secret, bad) is False


def test_get_totp_secret_prefers_env(tmp_path):
    from backend.api.auth import get_totp_secret
    assert get_totp_secret(str(tmp_path), env_secret="JBSWY3DPEHPK3PXP") == "JBSWY3DPEHPK3PXP"


def test_get_totp_secret_generates_once_and_persists(tmp_path):
    import os
    from backend.api.auth import get_totp_secret
    s1 = get_totp_secret(str(tmp_path))
    s2 = get_totp_secret(str(tmp_path))     # 재호출 — 재생성 금지(등록된 Authenticator 보호)
    assert s1 == s2 and len(s1) >= 16
    assert os.path.exists(os.path.join(str(tmp_path), "totp_secret.txt"))


def test_get_session_secret_prefers_env_then_persists(tmp_path):
    import os
    from backend.api.auth import get_session_secret
    assert get_session_secret(str(tmp_path), env_secret="fixed-secret") == "fixed-secret"
    a = get_session_secret(str(tmp_path))
    b = get_session_secret(str(tmp_path))   # 영속 — 재시작해도 로그인 유지되도록 동일
    assert a == b and len(a) >= 32
    assert os.path.exists(os.path.join(str(tmp_path), "session_secret.txt"))


# ── 게이트: 전 경로가 실제로 잠겼는가 (최우선 불변식) ──────────────────
import pytest


def _auth_settings(tmp_path, **over):
    from backend.config import Settings
    base = dict(auth_enabled=True, google_client_id="dummy-id",
               google_client_secret="dummy-secret",
               oauth_redirect_url="http://localhost:8000/auth/callback",
               allowed_emails="master@gmail.com", cache_dir=str(tmp_path),
               cookie_secure=False, flow_mode="demo", widget_token="w" * 32)
    base.update(over)
    return Settings(**base)


def _client(settings):
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    return TestClient(create_app(settings), follow_redirects=False)


PROTECTED = ["/", "/live/000660", "/api/live/000660/stream",
             "/api/candles/000660", "/scanner", "/api/scanner", "/api/semi",
             "/api/watch/000660", "/api/widget", "/widget-setup"]


@pytest.mark.parametrize("path", PROTECTED)
def test_protected_endpoints_gated_when_unauthenticated(tmp_path, path):
    c = _client(_auth_settings(tmp_path))
    r = c.get(path)
    if path.startswith("/api/"):
        assert r.status_code == 401, f"{path} API가 안 잠김: {r.status_code}"
    else:
        assert r.status_code in (302, 307), f"{path} HTML 리다이렉트 안 됨: {r.status_code}"
        assert "/login" in r.headers.get("location", "")


def test_public_page_endpoints_reachable(tmp_path):
    c = _client(_auth_settings(tmp_path))
    for path in ("/login", "/healthz", "/manifest.json"):
        assert c.get(path).status_code == 200, f"{path} 공개인데 막힘"
    # 아이콘 프리픽스는 공개 — 없는 아이콘도 게이트가 아니라 핸들러(404)에 도달해야
    assert c.get("/icons/none.png").status_code == 404


def test_auth_check_reports_401_when_unauthenticated(tmp_path):
    c = _client(_auth_settings(tmp_path))
    assert c.get("/api/auth/check").status_code == 401


def test_create_app_fails_closed_when_enabled_without_credentials(tmp_path):
    from backend.api.app import create_app
    s = _auth_settings(tmp_path, google_client_id=None, allowed_emails="")
    with pytest.raises(Exception):
        create_app(s)   # 공개인데 무방비로 뜨는 것 방지(fail-closed)


def test_auth_disabled_has_no_gate(tmp_path):
    c = _client(_auth_settings(tmp_path, auth_enabled=False))
    assert c.get("/healthz").status_code == 200
    assert c.get("/manifest.json").status_code == 200
    assert c.get("/login").status_code == 404   # 게이트 미장착 → 로그인 라우트 없음


def test_full_login_flow_email_then_totp_grants_access(tmp_path):
    # OAuth 콜백(목) → 1단계(email): 보호경로는 /2fa로 → TOTP 통과 → 2단계 완전 인증.
    import pyotp
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    from backend.api.auth import get_totp_secret
    s = _auth_settings(tmp_path)
    app = create_app(s)

    async def fake_token(request):   # 구글 미접속 — 토큰 교환만 목으로
        return {"userinfo": {"email": "master@gmail.com", "email_verified": True}}
    app.state.oauth_client.authorize_access_token = fake_token

    c = TestClient(app, follow_redirects=False)
    r = c.get("/auth/callback")                       # 콜백 → email 세션 → /2fa
    assert r.status_code == 302 and r.headers["location"] == "/2fa"
    # 1단계 상태: 보호경로는 로그인이 아니라 2FA로 유도
    assert c.get("/").headers["location"] == "/2fa"
    assert c.get("/api/candles/000660").status_code == 401
    assert c.get("/api/auth/check").status_code == 401
    # 2단계: 올바른 TOTP → 완전 인증
    code = pyotp.TOTP(get_totp_secret(str(tmp_path), s.totp_secret)).now()
    r = c.post("/2fa", data={"code": code})
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert c.get("/api/auth/check").status_code == 200


def test_full_login_flow_rejects_wrong_totp(tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    s = _auth_settings(tmp_path)
    app = create_app(s)

    async def fake_token(request):
        return {"userinfo": {"email": "master@gmail.com", "email_verified": True}}
    app.state.oauth_client.authorize_access_token = fake_token
    c = TestClient(app, follow_redirects=False)
    c.get("/auth/callback")
    assert c.post("/2fa", data={"code": "000000"}).status_code == 401  # 틀린 코드
    assert c.get("/api/auth/check").status_code == 401                 # 여전히 미완


def test_2fa_setup_page_has_scannable_png_qr(tmp_path):
    # 실사고: SvgImage QR이 빈 SVG(모듈 미렌더)라 화면에 안 보임 → 렌더 확실한 PNG로.
    import base64
    import re
    from backend.api.auth import _setup_html, totp_provisioning_uri
    secret = "JBSWY3DPEHPK3PXP"
    html = _setup_html(totp_provisioning_uri(secret, "m@example.com"), secret)
    m = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", html)
    assert m, "QR PNG data URI 없음"
    png = base64.b64decode(m.group(1))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"      # 유효 PNG 시그니처
    assert len(png) > 200                        # 실제 QR 내용 있음(빈 이미지 아님)
    assert secret in html                        # 스캔 실패 대비 수동 키 폴백


def test_callback_rejects_disallowed_email(tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    s = _auth_settings(tmp_path)
    app = create_app(s)

    async def fake_token(request):
        return {"userinfo": {"email": "intruder@gmail.com", "email_verified": True}}
    app.state.oauth_client.authorize_access_token = fake_token
    c = TestClient(app, follow_redirects=False)
    assert c.get("/auth/callback").status_code == 403     # allowlist 밖 → 거부
    assert c.get("/api/auth/check").status_code == 401     # 세션 안 생김


# ── 위젯 Bearer (게이트 안의 두 번째 잠금 — 공개 예외 아님, 설계 2026-07-16) ──
def test_widget_bearer_valid_token_passes_gate(tmp_path, monkeypatch):
    """유효 토큰은 게이트 통과 — 핸들러 도달(데이터 없음 503이지 게이트 401이 아님).
    전역 settings 격리 — 실기기 .env의 KIS 키로 라이브 호출 방지(결정적 503)."""
    from backend.config import settings as _gs
    monkeypatch.setattr(_gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(_gs, "kis_app_key", None)
    c = _client(_auth_settings(tmp_path))
    r = c.get("/api/widget", headers={"Authorization": "Bearer " + "w" * 32})
    assert r.status_code == 503                    # 테스트 환경: KIS/캐시 없음 → 핸들러 503
    assert r.json()["error"] != "unauthorized"     # 게이트가 아니라 핸들러의 응답


def test_widget_bearer_wrong_token_401(tmp_path):
    c = _client(_auth_settings(tmp_path))
    r = c.get("/api/widget", headers={"Authorization": "Bearer wrong-token-1234567890"})
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}   # 본문으로 실패 사유 구분 금지


def test_widget_token_unset_503_fail_closed(tmp_path):
    """SM_WIDGET_TOKEN 미설정 → 게이트가 503(기능 꺼짐) — 401과 구분, 핸들러 미도달."""
    c = _client(_auth_settings(tmp_path, widget_token=None))
    assert c.get("/api/widget").status_code == 503
