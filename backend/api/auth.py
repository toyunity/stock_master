from __future__ import annotations

"""인증 게이트 — Google OAuth2(OIDC) 신원 + TOTP 2차 + 세션 쿠키.

공개 노출(Tailscale Funnel) 전제이므로 '모든 경로가 실제로 잠겼는가'가 최우선 불변식.
신원 검증(allowlist)·TOTP는 순수 함수로 분리해 단위 테스트한다.
설계: docs/superpowers/specs/2026-07-14-public-deploy-auth-design.md
"""

import os
import secrets as _secrets

from html import escape
from typing import Iterable, List, Optional

from fastapi import Request  # 모듈 전역 필수 — from __future__ annotations로 어노테이션이
# 문자열이 되어 FastAPI가 get_type_hints로 모듈 전역에서 Request를 찾는다(지역 import면 못 찾아 422).


def verify_userinfo(info: dict, allowed_emails: Iterable[str]) -> Optional[str]:
    """OIDC userinfo에서 '검증된 + 허용목록' 이메일이면 정규화(소문자) 이메일 반환, 아니면 None.

    email_verified가 참이어야 하고(구글은 bool, 방어적으로 문자열도 허용) 이메일이
    allowlist에 있어야 한다(대소문자 무시). allowlist가 신원의 핵심 — OAuth만으론
    어떤 구글 계정도 통과하므로 이 관문을 반드시 거친다.
    """
    email = (info or {}).get("email")
    if not email:
        return None
    if info.get("email_verified") not in (True, "true", "True", 1):
        return None
    email = email.strip().lower()
    allowed = {e.strip().lower() for e in (allowed_emails or []) if e}
    return email if email in allowed else None


# ── TOTP (Google Authenticator, RFC 6238) ────────────────────────────
def verify_totp(secret: str, code) -> bool:
    """6자리 TOTP 검증. valid_window=1(±30초)로 시계 오차 허용. 형식 불량은 False."""
    import pyotp
    if not secret or not code:
        return False
    code = str(code).strip()
    if not (code.isdigit() and len(code) == 6):
        return False
    try:
        return bool(pyotp.TOTP(secret).verify(code, valid_window=1))
    except Exception:
        return False


def totp_provisioning_uri(secret: str, account: str,
                          issuer: str = "Stock Master") -> str:
    """Google Authenticator 등록용 otpauth:// URI(QR로 표시)."""
    import pyotp
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


# ── 시크릿 영속 (env 우선, 없으면 캐시 파일 생성·재사용) ──────────────
def _get_or_create_secret(cache_dir: str, filename: str, gen) -> str:
    path = os.path.join(cache_dir, filename)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            s = f.read().strip()
        if s:
            return s
    s = gen()
    os.makedirs(cache_dir, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(s)
    os.replace(tmp, path)  # 원자적
    return s


def get_totp_secret(cache_dir: str, env_secret: Optional[str] = None) -> str:
    """TOTP 시크릿. env가 있으면 그대로(재생성 금지 — 등록된 Authenticator 보호)."""
    import pyotp
    if env_secret:
        return env_secret.strip()
    return _get_or_create_secret(cache_dir, "totp_secret.txt", pyotp.random_base32)


def get_session_secret(cache_dir: str, env_secret: Optional[str] = None) -> str:
    """세션 쿠키 서명키. 영속시켜 재시작해도 로그인이 유지되게 한다."""
    if env_secret:
        return env_secret.strip()
    return _get_or_create_secret(cache_dir, "session_secret.txt",
                                 lambda: _secrets.token_hex(32))


def _emails(settings) -> List[str]:
    return [e.strip() for e in (settings.allowed_emails or "").split(",") if e.strip()]


# ── 게이트 (순수 ASGI — StreamingResponse/SSE를 버퍼링하지 않는다) ─────
_PUBLIC_EXACT = {"/login", "/auth/login", "/auth/callback", "/logout",
                 "/healthz", "/manifest.json", "/api/auth/check", "/favicon.ico"}
_PUBLIC_PREFIX = ("/icons/",)


def _is_public(path: str) -> bool:
    return path in _PUBLIC_EXACT or path.startswith(_PUBLIC_PREFIX)


class AuthGate:
    """세션 2단계(email→totp_ok)를 검사해 미인증 요청을 차단. BaseHTTPMiddleware가
    아니라 순수 ASGI라 SSE 스트리밍을 깨지 않는다. SessionMiddleware가 바깥(먼저)에서
    scope['session']을 채운 뒤 이 게이트가 읽는다(설치 시 add 순서로 보장)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        resp = self._blocked(scope.get("path", ""), scope.get("session") or {})
        if resp is None:
            return await self.app(scope, receive, send)
        return await resp(scope, receive, send)

    @staticmethod
    def _blocked(path, session):
        from starlette.responses import JSONResponse, RedirectResponse
        if _is_public(path):
            return None
        is_api = path.startswith("/api/")
        if not session.get("email"):                       # 0단계 → 로그인
            return (JSONResponse({"error": "unauthorized"}, status_code=401)
                    if is_api else RedirectResponse("/login", status_code=302))
        if not session.get("totp_ok"):                     # 1단계 → 2FA
            if path == "/2fa" or path.startswith("/2fa/"):
                return None                                # 2FA 페이지만 허용
            return (JSONResponse({"error": "2fa required"}, status_code=401)
                    if is_api else RedirectResponse("/2fa", status_code=302))
        return None                                         # 완전 인증


def install(app, settings) -> None:
    """auth_enabled일 때만 호출 — 크리덴셜 없으면 기동 거부(fail-closed)."""
    from starlette.middleware.sessions import SessionMiddleware
    emails = _emails(settings)
    if not (settings.google_client_id and settings.google_client_secret
            and settings.oauth_redirect_url and emails):
        raise RuntimeError(
            "SM_AUTH_ENABLED=true인데 OAuth 크리덴셜/allowlist가 없습니다 "
            "(SM_GOOGLE_CLIENT_ID/SECRET·SM_OAUTH_REDIRECT_URL·SM_ALLOWED_EMAILS 필요) — fail-closed")
    from authlib.integrations.starlette_client import OAuth
    oauth = OAuth()
    # register가 클라이언트를 반환 — 단일 인스턴스로 잡아 재사용(테스트에서 이 객체의
    # authorize_access_token만 목으로 교체하면 됨). app.state에 노출.
    google = oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        client_kwargs={"scope": "openid email profile"})
    app.state.oauth_client = google
    _register_routes(app, google, settings, emails)
    # add 순서: 나중에 add한 것이 바깥(먼저 실행). SessionMiddleware를 바깥에 둬야
    # scope['session']이 채워진 뒤 게이트가 읽는다.
    app.add_middleware(AuthGate)
    app.add_middleware(
        SessionMiddleware,
        secret_key=get_session_secret(settings.cache_dir, settings.session_secret),
        session_cookie="sm_session", max_age=30 * 24 * 3600,
        same_site="lax", https_only=bool(settings.cookie_secure))


def _register_routes(app, google, settings, emails) -> None:
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

    @app.get("/login", response_class=HTMLResponse)
    def _login():
        return HTMLResponse(_LOGIN_HTML)

    @app.get("/auth/login")
    async def _auth_login(request: Request):
        return await google.authorize_redirect(request, settings.oauth_redirect_url)

    @app.get("/auth/callback")
    async def _auth_callback(request: Request):
        try:
            token = await google.authorize_access_token(request)
        except Exception:
            return HTMLResponse(_msg_html("로그인 실패 — 다시 시도해 주세요."), status_code=400)
        email = verify_userinfo(token.get("userinfo") or {}, emails)
        if not email:
            return HTMLResponse(_msg_html("허용되지 않은 계정입니다."), status_code=403)
        request.session["email"] = email
        request.session.pop("totp_ok", None)   # 재로그인 시 2FA 다시
        return RedirectResponse("/2fa", status_code=302)

    @app.get("/2fa", response_class=HTMLResponse)
    def _twofa_get(request: Request):
        if not request.session.get("email"):
            return RedirectResponse("/login", status_code=302)
        return HTMLResponse(_twofa_html())

    @app.post("/2fa", response_class=HTMLResponse)
    async def _twofa_post(request: Request):
        if not request.session.get("email"):
            return RedirectResponse("/login", status_code=302)
        form = await request.form()
        secret = get_totp_secret(settings.cache_dir, settings.totp_secret)
        if verify_totp(secret, form.get("code", "")):
            request.session["totp_ok"] = True
            return RedirectResponse("/", status_code=302)
        return HTMLResponse(_twofa_html(error="코드가 올바르지 않습니다."), status_code=401)

    @app.get("/2fa/setup", response_class=HTMLResponse)
    def _twofa_setup(request: Request):
        if not request.session.get("email"):
            return RedirectResponse("/login", status_code=302)
        secret = get_totp_secret(settings.cache_dir, settings.totp_secret)
        uri = totp_provisioning_uri(secret, request.session["email"])
        return HTMLResponse(_setup_html(uri, secret))

    @app.get("/logout")
    def _logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=302)

    @app.get("/api/auth/check")
    def _auth_check(request: Request):
        ok = bool(request.session.get("email") and request.session.get("totp_ok"))
        return JSONResponse({"ok": ok}, status_code=200 if ok else 401)


# ── 최소 로그인/2FA 페이지 ────────────────────────────────────────────
_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<meta name="theme-color" content="#f4f6fb" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d1117" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-title" content="Stock Master">
<style>
:root{{--bg:#eef1f7;--surface:#fff;--surface-2:#f3f5fa;--text:#131722;--text-2:#556072;
--text-3:#8a94a6;--border:#e3e8f0;--primary:#1565c0;--up:#e0322c;--r:14px}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0d1117;--surface:#161b22;--surface-2:#1b222c;
--text:#e7edf5;--text-2:#9aa6b6;--text-3:#6b7789;--border:#2a323d;--primary:#4c9aff;--up:#ff5b52}}}}
*{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
min-height:100vh;margin:0;background:var(--bg);color:var(--text);line-height:1.6;
display:flex;align-items:center;justify-content:center;
padding:32px max(20px,env(safe-area-inset-left)) max(32px,env(safe-area-inset-bottom)) max(20px,env(safe-area-inset-right))}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:20px;
box-shadow:0 8px 30px rgba(17,24,39,.10);padding:32px 26px;width:100%;max-width:380px;text-align:center}}
h1{{font-size:22px;font-weight:800;margin:0 0 6px;letter-spacing:-.01em}}
p{{color:var(--text-2);font-size:14px;margin:8px 0}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:50px;max-width:100%;
margin-top:18px;padding:0 26px;background:var(--primary);color:#fff;border:none;border-radius:var(--r);
font-size:16px;font-weight:600;cursor:pointer;text-decoration:none;
box-shadow:0 4px 14px rgba(21,101,192,.30);-webkit-tap-highlight-color:transparent}}
.btn:active{{opacity:.85}}
.btn.alt{{background:var(--surface-2);color:var(--text);box-shadow:none;border:1px solid var(--border);font-weight:500}}
input{{font-size:28px;letter-spacing:10px;text-align:center;padding:14px 10px;width:220px;max-width:100%;
border:1px solid var(--border);border-radius:var(--r);margin-top:12px;background:var(--surface-2);
color:var(--text);font-variant-numeric:tabular-nums}}
.err{{color:var(--up);margin-top:12px;font-weight:600;font-size:14px}}
.muted{{color:var(--text-3);font-size:13px;margin-top:24px}} .muted a{{color:var(--text-2)}}
img.qr{{width:230px;height:230px;max-width:100%;image-rendering:pixelated;background:#fff;
padding:12px;border-radius:var(--r);margin:6px auto 0}}
code{{background:var(--surface-2);color:var(--text);padding:3px 8px;border-radius:6px;
word-break:break-all;font-size:14px}}
a{{color:var(--primary);text-decoration:none}}
</style></head><body><div class="card">{body}</div></body></html>"""

_LOGIN_HTML = _PAGE.format(
    title="로그인 — Stock Master",
    body='<h1>🔒 Stock Master</h1><p>계속하려면 로그인하세요.</p>'
         '<a class="btn" href="/auth/login">Google로 로그인</a>')


def _msg_html(msg: str) -> str:
    return _PAGE.format(title="Stock Master",
                        body='<h1>🔒 Stock Master</h1><p>' + escape(msg)
                        + '</p><a class="btn" href="/login">로그인으로</a>')


def _twofa_html(error: str = "") -> str:
    err = '<div class="err">' + escape(error) + '</div>' if error else ''
    return _PAGE.format(
        title="2차 인증 — Stock Master",
        body='<h1>🔐 2차 인증</h1><p>Google Authenticator의 6자리 코드를 입력하세요.</p>'
             '<form method="post" action="/2fa"><input name="code" inputmode="numeric" '
             'autocomplete="one-time-code" pattern="[0-9]*" maxlength="6" autofocus>' + err
             + '<div><button class="btn" type="submit">확인</button></div></form>'
             '<div style="margin-top:14px"><a class="btn alt" href="/2fa/setup">'
             '📱 처음이면 여기서 기기 등록(QR)</a></div>'
             '<div class="muted"><a href="/logout">로그아웃</a></div>')


def _setup_html(uri: str, secret: str) -> str:
    import base64
    import io

    import qrcode
    img = qrcode.make(uri)                 # 기본 PIL(PNG) — 브라우저 렌더 확실
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return _PAGE.format(
        title="Authenticator 등록 — Stock Master",
        body='<h1>🔐 Authenticator 등록</h1>'
             '<p>Google Authenticator 앱 → ➕ → “QR 코드 스캔”으로 아래 QR을 찍으세요.<br>'
             '스캔이 안 되면 “설정 키 입력”에 아래 <b>수동 키</b>를 입력.</p>'
             '<img class="qr" alt="TOTP QR" src="data:image/png;base64,' + b64 + '">'
             '<p class="muted">수동 키: <code>' + escape(secret) + '</code></p>'
             '<a class="btn" href="/2fa">등록했어요 — 코드 입력하러</a>')
