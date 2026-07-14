# 공개 배포(Tailscale Funnel) + Google OAuth2·TOTP 인증 게이트 — 설계

날짜: 2026-07-14 · 상태: 브레인스토밍 확정(공개 Funnel + OAuth2+TOTP, 마스터 3회 확인)

## 목적·결정

로컬(같은 WiFi)에서만 보이던 앱을 **어디서든 폰에서** 보게 한다. 앱은 KIS 1키·1세션·
로컬 캐시·마스터 키를 쥔 상시 Python 서버라 "클라우드 업로드"가 아니라 **맥의 서버를
무료 터널로 공개 노출**한다. 부수효과로 HTTPS(secure context)가 생겨 감시선 OS 알림
([[2026-07-14-watch-line-editor-design]] C)이 함께 풀린다.

**의식적 결정(트레이드오프 고지 후 3회 확인)**: 폰에 Tailscale 앱을 안 깔기 위해 **공개
Funnel**을 택했고, 그 대가로 **인증 게이트가 필수 전제**다. 공개 노출에서 게이트에 뚫린
경로가 하나라도 있으면 KIS 키가 인터넷 전체에 노출된다(레이트리밋 남용·토큰 재발급 카톡
스팸). 따라서 "모든 경로가 실제로 잠겼는가"가 이 작업의 최우선 불변식이다.

## 제약

- **1키 1세션**: 맥과 클라우드 동시 구동 불가 → 서버는 맥에 그대로, 노출만 추가.
- **Python 3.9.6**(venv). authlib 1.6.12·pyotp 2.10.0·itsdangerous 2.2.0·qrcode 8.2
  설치·import 검증 완료. `match`·`X|Y` 힌트 금지.
- **Funnel 뒤 프록시**: 앱은 localhost:8000에 http로 받지만 브라우저 쪽은 HTTPS
  `*.ts.net`. → OAuth redirect_uri·쿠키 Secure는 **공개 HTTPS 기준**으로 설정, `request.url`
  (=http://localhost)에서 유도 금지.

---

## 인증 아키텍처

### 세션 (Starlette `SessionMiddleware`, 서명 쿠키)
- 2단계 상태: `session["email"]`(OAuth 통과=1차) · `session["totp_ok"]`(TOTP 통과=2차).
- **완전 인증 = 둘 다 참**. 쿠키 30일. 서명키 `SM_SESSION_SECRET`(없으면 생성 후
  `<cache_dir>/session_secret.txt`에 영속 — 재시작해도 로그인 유지).
- 쿠키 옵션: HttpOnly·SameSite=Lax(구글→ts.net 톱레벨 리다이렉트에 쿠키 실려야 함)·
  Secure=`SM_COOKIE_SECURE`(기본 True; 맥 `http://localhost` 사파리 테스트용으로 False 가능).

### 게이트 미들웨어 (`backend/api/auth.py`)
- **공개 경로**(인증 없이 통과): `/login`·`/auth/login`·`/auth/callback`·`/2fa`(POST 포함)·
  `/2fa/setup`(단 1차 통과 필요)·`/logout`·`/healthz`·`/manifest.json`·`/icons/`(프리픽스)·
  `/api/auth/check`.
- 그 외 모든 경로: 완전 인증 필요.
  - 1차만 통과(email 있고 totp 없음): `/2fa*`는 허용, 나머지는 `/2fa`로.
  - 미인증: HTML(비-`/api/`)은 `302 → /login`, `/api/*`(SSE 포함)은 `401`.
- **활성 조건**: `SM_AUTH_ENABLED`(기본 **False**). True면 시작 시 필수 크리덴셜
  (client_id/secret/redirect/allowed_emails) 존재를 **단언(fail-closed, 없으면 기동 거부)**.
  False면 미들웨어 미장착 → 기존 로컬/테스트 동작 그대로. **Funnel 노출은 반드시
  `SM_AUTH_ENABLED=true` 이후에만.**

### OAuth2 (Google OIDC, authlib)
- `oauth.register("google", server_metadata_url=".../openid-configuration",
  client_id, client_secret, client_kwargs={"scope":"openid email profile"})`.
- `GET /login`: "Google로 로그인" 버튼 → `/auth/login`.
- `GET /auth/login`: `authorize_redirect(request, redirect_uri=SM_OAUTH_REDIRECT_URL)`
  — **명시 redirect_uri**(공개 HTTPS 콜백). state/nonce는 authlib가 세션에 저장.
- `GET /auth/callback`: `token=await authorize_access_token(request)` →
  `info=token["userinfo"]` → **`email_verified is True` 및 `email ∈ SM_ALLOWED_EMAILS`**
  확인. 통과 시 `session["email"]=email`, `totp_ok` 삭제 → `/2fa`. 불허 이메일 → `403`.
- 검증 로직은 `verify_userinfo(info)->email|None` 순수 함수로 분리(테스트 용이).

### TOTP 2차 (pyotp, Google Authenticator)
- 시크릿 `SM_TOTP_SECRET`(base32). 없으면 `pyotp.random_base32()` 생성 후
  `<cache_dir>/totp_secret.txt` 영속(**재생성 금지 — 등록된 Authenticator가 조용히 깨짐**).
- `GET /2fa`: 1차(email) 통과 시 6자리 입력 폼(아니면 `/login`). `/2fa/setup` 링크.
- `POST /2fa`: `pyotp.TOTP(secret).verify(code, valid_window=1)` → 성공 `session["totp_ok"]=True`
  → `/`. 실패 안내.
- `GET /2fa/setup`(1차 통과 필요): `otpauth://` URI + QR(SVG, qrcode) 표시 → Google
  Authenticator에 스캔. 시크릿 노출 경로이므로 반드시 1차 게이트 뒤에 둔다.
- `GET /logout`: 세션 클리어 → `/login`.

### SSE 401 루프 방지 (앞서 고친 재연결 로직과 충돌 차단)
- 세션 만료 시 `/api/live/{code}/stream`이 401 → EventSource는 상태코드를 못 읽어
  CLOSED → `scheduleReconnect()`/워치독이 무한 재접속("재접속 중…" 영구, 방금 고친 버그처럼 보임).
- 대응: `GET /api/auth/check`(완전 인증 200 / 아니면 401) 추가. `live_page.js`의 **CLOSED
  분기와 워치독 강제 재접속 직전에 먼저 `fetch('/api/auth/check')`** → 401이면
  `location.href='/login'`, 아니면 기존 `connect()/scheduleReconnect()`.

### 설정(env, `backend/config.py` 확장)
`SM_AUTH_ENABLED`(bool,기본F) · `SM_GOOGLE_CLIENT_ID` · `SM_GOOGLE_CLIENT_SECRET` ·
`SM_OAUTH_REDIRECT_URL` · `SM_ALLOWED_EMAILS`(콤마구분) · `SM_SESSION_SECRET`(opt) ·
`SM_TOTP_SECRET`(opt) · `SM_COOKIE_SECURE`(bool,기본T).
`pyproject.toml [project].dependencies`에 `authlib>=1.6`·`pyotp>=2.9`·`itsdangerous>=2.2`·
`qrcode>=8.0` 추가, `httpx>=0.27`를 dev→main으로 이동(authlib 토큰교환에 필요).

---

## 배포 절차 (Tailscale Funnel) — 순서가 중요

인증을 **먼저** 갖추고 노출은 **맨 마지막**. redirect_uri가 ts.net 호스트명이라 순서가 얽힘.

1. **Tailscale 설치·로그인**(제가 `brew install tailscale`; **마스터가 직접** `sudo tailscale up`
   → 뜨는 URL로 본인 계정 로그인·기기 승인). MagicDNS 켜기. 호스트명 `<맥>.<테일넷>.ts.net` 확보.
2. **Google Cloud Console(마스터)**: 프로젝트 → OAuth 동의화면(External·Testing, 본인을
   테스트 사용자) → 사용자 인증정보 → OAuth 클라이언트(웹) → **승인 리다이렉트 URI 2개**:
   `http://localhost:8000/auth/callback`(로컬 테스트) + `https://<맥>.<테일넷>.ts.net/auth/callback`.
   발급된 ID/시크릿을 `.env`에 기입. `SM_ALLOWED_EMAILS`=본인 이메일, `SM_OAUTH_REDIRECT_URL`
   =로컬은 localhost·배포 시 ts.net(환경별로 교체).
3. **로컬 검증**: `SM_AUTH_ENABLED=true`로 맥에서 기동 → localhost에서 Google 로그인 →
   `/2fa/setup`으로 Authenticator 등록 → 6자리 → 대시보드. 미인증 시 게이트 동작 확인.
4. **Funnel 활성(맨 마지막)**: 관리콘솔 ACL 정책에 `funnel` nodeAttr 부여 →
   `tailscale funnel 8000`(또는 `tailscale serve`+`funnel`) → Let's Encrypt 인증서 자동 →
   공개 `https://<맥>.<테일넷>.ts.net`. redirect를 ts.net으로 바꿔 폰에서 최종 검증.
   - **주의**: Funnel은 `tailscale up`과 **별개의 2차 대화형 단계**(MagicDNS+인증서+ACL nodeAttr).
   - Funnel 포트는 443/8443/10000만 — 공개 443 → 내부 8000 매핑.

---

## 테스트

- **[최우선] `tests/test_auth.py` — 전 경로 게이트 파라미터라이즈**: `SM_AUTH_ENABLED=true`
  + 더미 크리덴셜에서 **미인증** 요청이 각 실경로(`/`·`/live/000660`·`/api/live/000660/stream`
  ·`/api/candles/000660`·`/scanner`·`/api/scanner`·`/api/semi`·`/api/watch/000660`)에 대해
  401 또는 3xx인지, 공개경로(`/login`·`/healthz`·`/manifest.json`·`/icons/x`·`/api/auth/check`)만
  열려 있는지 단언. **이 테스트가 공개 노출을 안전하게 만드는 핵심.**
- 세션 단계: email만 있고 totp 없음 → 보호경로가 `/2fa`로, `/2fa` 도달 가능.
- TOTP: 시크릿으로 `pyotp.TOTP(secret).now()` 계산해 `POST /2fa` → totp_ok → 보호경로 200.
- `verify_userinfo`: 허용 이메일(email_verified) 통과 · 불허/미검증 이메일 거부(403).
- `/api/auth/check`: 미인증 401 · 완전 인증 200.
- `SM_AUTH_ENABLED=false`(기본)에서 기존 테스트(test_live_api 등) 전부 그대로 통과(회귀).
- 프론트(node 하니스): SSE CLOSED/워치독 재접속 전에 auth-check 호출 후 401이면 로그인 이동
  (fetch 목으로 분기 검증), 기존 재연결/render 스모크 유지.

## 보안·리스크

- **fail-closed**: `SM_AUTH_ENABLED=true`인데 크리덴셜 없으면 기동 거부(공개인데 무방비 방지).
- 시크릿(세션/TOTP)은 캐시 파일 영속 + `.env`는 git 제외 확인. TOTP 시크릿 재생성 금지.
- 단일 이메일 allowlist + `email_verified` 필수 — OAuth만으론 아무 구글계정도 통과하므로
  allowlist가 신원의 핵심. TOTP는 구글계정 탈취 대비 심층방어.
- 잔여 리스크: 손수 만든 게이트의 누락 경로 → "전 경로 게이트" 테스트로 방어. 신규 라우트
  추가 시 이 테스트에 반드시 포함.
- YAGNI: 다중 사용자·역할·리프레시토큰 회전·비번 재설정 흐름 제외(1인용).
