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


def test_secret_files_are_owner_only(tmp_path):
    """M8 — session_secret.txt 하나면 OAuth+TOTP를 통째로 우회하는 쿠키를 만들 수 있다.
    이미 0644로 만들어진 파일도 다음 기동에 조여야 한다(실서버에 이미 있다)."""
    import os
    import stat
    from backend.api.auth import get_session_secret, get_totp_secret
    for name, fn in (("session_secret.txt", get_session_secret),
                     ("totp_secret.txt", get_totp_secret)):
        fn(str(tmp_path))
        path = os.path.join(str(tmp_path), name)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600, name
        os.chmod(path, 0o644)               # 기존 배포분 모사
        fn(str(tmp_path))
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600, name + " (기존 파일)"


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
             "/api/worldidx",
             "/api/watch/000660", "/api/widget", "/widget-setup",
             "/widget-setup/rotate", "/widget-setup/android.apk", "/api/watchlist"]


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


# ── 접근 취소 · 2FA 남용 방지 (감사 M3·M4, 2026-08-12) ─────────────────
def _stage1(app):
    """OAuth 콜백만 통과한(=email 세션만 있고 2FA 미완) 클라이언트."""
    from fastapi.testclient import TestClient

    async def fake_token(request):
        return {"userinfo": {"email": "master@gmail.com", "email_verified": True}}
    app.state.oauth_client.authorize_access_token = fake_token
    c = TestClient(app, follow_redirects=False)
    c.get("/auth/callback")
    return c


def _code(tmp_path, s):
    import pyotp
    from backend.api.auth import get_totp_secret
    return pyotp.TOTP(get_totp_secret(str(tmp_path), s.totp_secret)).now()


def test_removed_email_is_blocked_on_next_request(tmp_path):
    """M3 — allowlist 대조가 로그인 순간 1회뿐이면, 계정을 빼도 기존 쿠키가 30일 통과한다.
    (한계: install()이 기동 시 읽으므로 제거는 재기동 후 적용 — 그 재기동을 여기서 모사한다.)"""
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    s = _auth_settings(tmp_path)
    c = _stage1(create_app(s))
    assert c.post("/2fa", data={"code": _code(tmp_path, s)}).status_code == 302
    assert c.get("/api/watch/000660").status_code == 200      # 전제: 지금은 통과 중
    # 같은 cache_dir(=같은 session_secret) + allowlist에서 제거 → 재기동
    app2 = create_app(_auth_settings(tmp_path, allowed_emails="other@gmail.com"))
    c2 = TestClient(app2, follow_redirects=False, cookies=c.cookies)
    assert c2.get("/api/watch/000660").status_code == 401
    assert c2.get("/api/auth/check").status_code == 401   # 공개 라우트라 게이트를 안 탄다 — 여기서도 대조


def test_2fa_rejects_reused_code(tmp_path):
    """M4 — pyotp는 쓴 코드를 기억하지 않는다. 어깨너머로 본 6자리가 90초간 재사용됐다."""
    from backend.api.app import create_app
    s = _auth_settings(tmp_path)
    app = create_app(s)
    code = _code(tmp_path, s)
    assert _stage1(app).post("/2fa", data={"code": code}).status_code == 302   # 첫 사용
    c2 = _stage1(app)                                                          # 다른 기기
    assert c2.post("/2fa", data={"code": code}).status_code == 401             # 재사용 차단
    assert c2.get("/api/auth/check").status_code == 401


def test_2fa_locks_out_after_too_many_wrong_codes(tmp_path):
    """M4 — 상한이 없으면 1단계를 뚫은 공격자가 6자리를 무제한 대입한다.
    카운터는 세션이 아니라 이메일 키 — 쿠키를 버려도 초기화되면 안 된다."""
    from backend.api.app import create_app
    s = _auth_settings(tmp_path)
    app = create_app(s)
    c = _stage1(app)
    for i in range(5):
        assert c.post("/2fa", data={"code": "00000%d" % i}).status_code == 401
    assert c.post("/2fa", data={"code": "000009"}).status_code == 429
    assert c.post("/2fa", data={"code": _code(tmp_path, s)}).status_code == 429  # 맞아도 막힘
    assert _stage1(app).post("/2fa", data={"code": "000009"}).status_code == 429  # 새 쿠키도


def test_2fa_lockout_expires_by_itself(tmp_path, monkeypatch):
    """마스터가 자기 서비스에서 잠기면 안 된다 — 시간창이 지나면 자동 해제(영구 잠금 없음)."""
    from backend.api import auth
    from backend.api.app import create_app
    s = _auth_settings(tmp_path)
    c = _stage1(create_app(s))
    for i in range(5):
        c.post("/2fa", data={"code": "00000%d" % i})
    assert c.post("/2fa", data={"code": "000009"}).status_code == 429
    t0 = auth._now()
    monkeypatch.setattr(auth, "_now", lambda: t0 + 301)      # 창 밖으로 시계를 옮긴다
    assert c.post("/2fa", data={"code": _code(tmp_path, s)}).status_code == 302


# ── 위젯 Bearer (게이트 안의 두 번째 잠금 — 공개 예외 아님, 설계 2026-07-16) ──
def test_widget_bearer_valid_token_passes_gate(tmp_path, monkeypatch):
    """유효 계정 토큰은 게이트 통과 — 핸들러 도달(데이터 없음 503이지 게이트 401이 아님).
    전역 settings 격리 — 실기기 .env의 KIS 키로 라이브 호출 방지(결정적 503)."""
    from backend.config import settings as _gs
    from backend.flow import userstore
    monkeypatch.setattr(_gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(_gs, "kis_app_key", None)
    monkeypatch.setattr(_gs, "default_account", "master@gmail.com")
    tok = userstore.ensure_token("master@gmail.com")   # 계정별 토큰(정적 env 토큰 아님)
    c = _client(_auth_settings(tmp_path, default_account="master@gmail.com"))
    r = c.get("/api/widget", headers={"Authorization": "Bearer " + tok})
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


def test_widget_bearer_non_ascii_token_401_not_500():
    """비ASCII 바이트가 든 Bearer는 미처리 예외(500)가 아니라 401 — 공개 표면 방어(리뷰 2026-07-16).

    str+compare_digest는 비ASCII에 TypeError를 던진다. 게이트를 ASGI 스코프로 직접 구동해
    바이트 파싱 경로를 검증한다(httpx TestClient는 헤더를 ASCII로 인코드해 이 바이트를
    클라이언트에서 막아 서버 코드에 도달하지 못한다)."""
    from backend.api.auth import AuthGate
    gate = AuthGate(app=None, widget_token="w" * 32)
    scope = {"type": "http", "path": "/api/widget",
             "headers": [(b"authorization", b"Bearer \xff\xfe")]}
    resp = gate._widget_blocked(scope)      # 예외 없이 401 JSONResponse
    assert resp is not None and resp.status_code == 401


# ── 위젯 토큰 계정화 (Task 7 — Bearer→계정 매핑, default 폴백 금지) ──────
def test_widget_token_of_removed_email_is_401(tmp_path, monkeypatch):
    """M3 — allowlist에서 뺀 계정의 위젯 토큰도 죽어야 한다(위젯은 보유수량·평단·평가손익을 준다)."""
    from backend.config import settings as _gs
    from backend.flow import userstore
    monkeypatch.setattr(_gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(_gs, "default_account", "master@gmail.com")
    monkeypatch.setattr(_gs, "kis_app_key", None)    # 실 KIS 호출 방지(게이트가 뚫려도 오프라인)
    tok = userstore.ensure_token("master@gmail.com")
    c = _client(_auth_settings(tmp_path, allowed_emails="other@gmail.com"))
    assert c.get("/api/widget", headers={"Authorization": "Bearer " + tok}).status_code == 401


def test_widget_token_maps_to_account(tmp_path, monkeypatch):
    """계정 토큰으로 그 계정 데이터 도달, 미매칭 401(default 폴백 금지 — 교차계정 유출 차단).

    ⚠ widget_data는 전역 settings를 읽으므로 kis_app_key=None으로 격리(실기기 .env의 실제
    KIS 키로 라이브 호출 방지 — 결정적 503)."""
    from backend.config import settings
    from backend.flow import userstore
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "default_account", "master@gmail.com")
    monkeypatch.setattr(settings, "kis_app_key", None)
    tok = userstore.ensure_token("master@gmail.com")
    c = _client(_auth_settings(tmp_path, default_account="master@gmail.com"))
    r = c.get("/api/widget", headers={"Authorization": "Bearer " + tok})
    assert r.status_code in (200, 503)          # 게이트 통과(핸들러 도달)
    assert c.get("/api/widget",
                 headers={"Authorization": "Bearer wrong" + "x" * 20}).status_code == 401
