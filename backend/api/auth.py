from __future__ import annotations

"""인증 게이트 — Google OAuth2(OIDC) 신원 + TOTP 2차 + 세션 쿠키.

공개 노출(Tailscale Funnel) 전제이므로 '모든 경로가 실제로 잠겼는가'가 최우선 불변식.
신원 검증(allowlist)·TOTP는 순수 함수로 분리해 단위 테스트한다.
설계: docs/superpowers/specs/2026-07-14-public-deploy-auth-design.md
"""

import os
import secrets as _secrets
import time

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
    """0600으로 만들고, 이미 있는 파일도 조인다 — session_secret.txt 하나면 OAuth+TOTP를
    통째로 우회하는 sm_session 쿠키를 서명해 만들 수 있다. 이미 0644로 배포된 파일이
    있으므로(2026-08-12 실측) 읽기 경로에서도 한 번 조인다. 권한 조정 실패로 기동이
    막히면 안 되므로 OSError는 삼킨다(남의 소유 파일 등 예외 상황)."""
    path = os.path.join(cache_dir, filename)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            s = f.read().strip()
        if s:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return s
    s = gen()
    os.makedirs(cache_dir, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(s)
    os.chmod(tmp, 0o600)   # 모드는 tmp의 것이 os.replace로 따라간다
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


# ── 2FA 남용 방지 (감사 M4) ───────────────────────────────────────────
_2FA_WINDOW = 300.0   # 실패 카운터 시간창(초). 지나면 자동 해제 — 영구 잠금은 만들지 않는다
_2FA_MAX = 5          # 창 안 최대 실패 횟수
_2FA_REUSE = 90.0     # 성공한 코드를 막아두는 시간(valid_window=1이라 최대 ±30초 = 90초)


def _now() -> float:
    """2FA 시도 창의 시계 — 한 곳에 모아 테스트가 시간을 앞당길 수 있게 한다(벽시계 점프 무관)."""
    return time.monotonic()


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

    def __init__(self, app, widget_token=None, emails=()):
        self.app = app
        self.widget_token = widget_token   # /api/widget 전용 Bearer(설계 2026-07-16)
        # allowlist를 **매 요청** 대조한다 — 로그인 순간 1회만 보면 계정을 목록에서 빼도
        # 이미 나간 세션 쿠키가 30일 통과한다(감사 M3). 목록 자체는 기동 시 1회 읽으므로
        # 제거는 재기동 후 적용된다.
        self.allowed = {e.strip().lower() for e in (emails or ()) if e}

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path == "/api/widget":
            # 위젯: 세션 대신 Bearer — 공개 예외가 아니라 게이트 안의 두 번째 잠금.
            # 무토큰이 여전히 401이므로 PROTECTED 불변식 테스트에 예외가 없다.
            resp = self._widget_blocked(scope)
        else:
            resp = self._blocked(path, scope.get("session") or {}, self.allowed)
        if resp is None:
            return await self.app(scope, receive, send)
        return await resp(scope, receive, send)

    @staticmethod
    def _blocked(path, session, allowed=frozenset()):
        from starlette.responses import JSONResponse, RedirectResponse
        if _is_public(path):
            return None
        is_api = path.startswith("/api/")
        if session.get("email") not in allowed:            # 0단계(+매 요청 allowlist) → 로그인
            return (JSONResponse({"error": "unauthorized"}, status_code=401)
                    if is_api else RedirectResponse("/login", status_code=302))
        if not session.get("totp_ok"):                     # 1단계 → 2FA
            if path == "/2fa" or path.startswith("/2fa/"):
                return None                                # 2FA 페이지만 허용
            return (JSONResponse({"error": "2fa required"}, status_code=401)
                    if is_api else RedirectResponse("/2fa", status_code=302))
        return None                                         # 완전 인증

    def _widget_blocked(self, scope):
        """Bearer 토큰 → 계정 email 매핑(계정별 토큰). 유효하면 검증한 email을
        scope['state']['widget_email']에 실어 통과(None) — 핸들러가 토큰을 다시 조회하거나
        default_account로 폴백하지 않는 단일 해석 지점(교차계정 유출 차단). 미매칭/무토큰은
        동일 401(실패 사유로 정보 누출 금지). 위젯 자체 미설정(env·계정 토큰 전무)이면 503
        (fail-closed) — 기능 꺼짐을 401과 구분. 바이트 파싱 유지(비ASCII도 500 아닌 401)."""
        from starlette.responses import JSONResponse
        from backend.flow.userstore import email_for_token
        auth = b""
        for k, v in scope.get("headers") or ():
            if k == b"authorization":
                auth = v
                break
        # 바이트로 파싱한 뒤 안전 디코드 — 비ASCII 토큰(예: b"\xff\xfe")은 str화에서
        # 예외를 던질 수 있으므로 try/except로 ""로 흡수(공개 표면에 미처리 500 금지).
        raw = auth[7:] if auth[:7].lower() == b"bearer " else b""
        try:
            token = raw.decode("utf-8") if raw else ""
        except Exception:
            token = ""
        email = email_for_token(token) if token else None
        if email and email in self.allowed:   # 위젯 토큰도 allowlist에서 빠지면 죽는다(M3)
            st = scope.get("state")
            if not isinstance(st, dict):
                st = {}
                scope["state"] = st
            st["widget_email"] = email
            return None
        # 미설정 503은 self.widget_token(주입 env 토큰)에만 근거 — 파일(cache_dir/users)을
        # 읽지 않아 결정적. env·계정 토큰이 전무하면 503(기능 꺼짐), 있으면 미매칭 401.
        if not self.widget_token:
            return JSONResponse({"error": "widget not configured"}, status_code=503)
        return JSONResponse({"error": "unauthorized"}, status_code=401)


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
    app.add_middleware(AuthGate, widget_token=settings.widget_token, emails=emails)
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

    # 시도 카운터·재사용 기록은 **이메일 키**다(세션 키면 쿠키를 버려 초기화된다).
    # 계정 수가 한 자리라 증가 걱정이 없다. 프로세스 메모리 — 재기동하면 풀린다(의도).
    fail = {}      # email -> (실패 횟수, 창 시작 시각)
    used = {}      # email -> (마지막으로 통과한 코드, 만료 시각)

    @app.post("/2fa", response_class=HTMLResponse)
    async def _twofa_post(request: Request):
        if not request.session.get("email"):
            return RedirectResponse("/login", status_code=302)
        em, now = request.session["email"], _now()
        n, t0 = fail.get(em, (0, now))
        if now - t0 > _2FA_WINDOW:      # 창이 지났으면 초기화 — 여기서 t0를 갱신하지 않으면
            n, t0 = 0, now              # 재시도가 창을 계속 밀어 영구 잠금이 된다
        if n >= _2FA_MAX:
            return HTMLResponse(_twofa_html(error="시도가 너무 많아요 — 5분 뒤 다시 해주세요."),
                                status_code=429)
        form = await request.form()
        secret = get_totp_secret(settings.cache_dir, settings.totp_secret)
        code = str(form.get("code", "")).strip()
        last, exp = used.get(em, ("", 0.0))
        if code and code == last and now < exp:
            # ponytail: 마지막 1개만 기억한다 — 같은 창의 다른 코드까지 막으려면 집합으로.
            return HTMLResponse(_twofa_html(error="이미 쓴 코드예요 — 새 코드를 입력하세요."),
                                status_code=401)
        if verify_totp(secret, code):
            used[em], fail[em] = (code, now + _2FA_REUSE), (0, now)
            request.session["totp_ok"] = True
            return RedirectResponse("/", status_code=302)
        fail[em] = (n + 1, t0)
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
        # 이 라우트는 공개(미인증도 401을 받아야 PWA가 로그인 화면으로 간다)라 게이트를
        # 안 탄다 — allowlist 대조를 여기서 한 번 더 한다. 안 하면 제외된 계정이 다른
        # 경로는 전부 401을 받으면서 여기서만 ok:true를 받아 껍데기 화면이 뜬다(M3).
        allowed = {e.strip().lower() for e in emails if e}
        ok = bool(request.session.get("email") in allowed and request.session.get("totp_ok"))
        return JSONResponse({"ok": ok}, status_code=200 if ok else 401)


# ── 최소 로그인/2FA 페이지 ────────────────────────────────────────────
# 인증 페이지들(/login·/2fa·/2fa/setup)은 backend/report/theme.py를 import하지 않는다 —
# 아래 :root 토큰은 자체 복제본이고 6차 리디자인(2026-08-12) 이전 값 그대로다
# (--bg:#eceef3, --border:#e0e4ec, --r:12px 등 — theme.py의 현재 값과 다르다).
# 통합은 별도 작업. 여기 값은 바꾸지 않는다(2026-08-13, 전체 브랜치 리뷰).
_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<meta name="theme-color" content="#f4f6fb" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d1117" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-title" content="Stock Master">
<style>
:root{{--bg:#eceef3;--surface:#fff;--surface-2:#f3f5f9;--text:#12151d;--text-2:#586074;
--text-3:#8b93a4;--border:#e0e4ec;--primary:#6a4ff0;--up:#e5342f;--r:12px;
--font-mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0a0c12;--surface:#141824;--surface-2:#1a1f2e;
--text:#e9ecf3;--text-2:#8b93a5;--text-3:#5f6879;--border:#252c3c;--primary:#9a86ff;--up:#ff5b52}}}}
*{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
min-height:100vh;margin:0;background:var(--bg);color:var(--text);line-height:1.6;
display:flex;align-items:center;justify-content:center;
padding:32px max(20px,env(safe-area-inset-left)) max(32px,env(safe-area-inset-bottom)) max(20px,env(safe-area-inset-right))}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:16px;
box-shadow:0 1px 2px rgba(18,21,29,.05),0 10px 30px rgba(18,21,29,.10);
padding:34px 26px;width:100%;max-width:380px;text-align:center}}
h1{{font-size:22px;font-weight:800;margin:0 0 6px;letter-spacing:-.03em}}
p{{color:var(--text-2);font-size:14px;margin:8px 0}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:50px;max-width:100%;
margin-top:18px;padding:0 26px;background:var(--primary);color:#fff;border:none;border-radius:var(--r);
font-size:16px;font-weight:700;cursor:pointer;text-decoration:none;
box-shadow:0 4px 14px rgba(106,79,240,.28);-webkit-tap-highlight-color:transparent}}
.btn:active{{opacity:.85}}
.btn.alt{{background:var(--surface-2);color:var(--text);box-shadow:none;border:1px solid var(--border);font-weight:500}}
input{{font-family:var(--font-mono);font-size:28px;letter-spacing:8px;text-align:center;
padding:14px 10px;width:230px;max-width:100%;
border:1px solid var(--border);border-radius:var(--r);margin-top:12px;background:var(--surface-2);
color:var(--text);font-variant-numeric:tabular-nums;font-weight:700}}
input:focus{{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px rgba(106,79,240,.18)}}
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
