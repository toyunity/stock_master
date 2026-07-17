# 관심종목 v2 — 계정별 저장 · 보유/수익 위젯 · 미국주식 · 드래그 편집 — 설계

날짜: 2026-07-17 · 상태: 브레인스토밍(마스터 결정 다수 확정) — 스펙 리뷰 대기

## 목적

아이폰 위젯 + 대시보드의 관심종목 기능을 4가지로 확장한다. 데이터 모델을 새로 짜는 김에
**계정별 분리**를 기반으로 깔고 그 위에 나머지를 얹는다.

## 마스터 확정 결정

1. **계정별 데이터 분리** — 로그인(구글 OAuth+TOTP) 이메일 기준으로 관심종목·보유·수익을
   저장. 계정끼리 공유하지 않는다.
2. **보유·수익(P&L)** — 종목별 보유수량·평균매입가 입력 → 위젯에 현재가/등락%/**수익 금액**까지.
   (금액 노출 트레이드오프를 알고 선택 — 아래 보안 절.)
3. **미국 주식** — 검색창에 **티커 직접 입력**(예: NVDA). 서버가 거래소 자동 탐색.
4. **편집 UX** — 대시보드 상단 **컴팩트 관리 리스트**에서 **드래그 순서변경 + 스와이프 삭제**.
5. **위젯 시각 개선** — 항목 구분 실선, 폰트 확대, **상승 빨강 / 하락 파랑**(수익에도 적용).

## 제약 (기존 유지)

- **Python 3.9**(`match`·`X|Y` 금지), 자기완결 HTML(외부 CDN 0), KIS=유일 시세 소스.
- "모든 경로 잠금" 불변식([[2026-07-14-public-deploy-auth-design]]). 테스트: `.venv/bin/python -m pytest`.
- 위젯은 iOS 갱신 ~15분+, 맥 잠자면 오프라인 — 기존 위젯 설계([[2026-07-16-iphone-widget-design]]) 계승.

---

## 1. 계정 정체성 (기반)

- **계정 키 = 세션 이메일**(`session["email"]`, 소문자 정규화 — auth.py가 이미 보장).
- **세션 없는 소비자의 기본 계정**: `settings.default_account`(`SM_DEFAULT_ACCOUNT` env,
  미설정이면 allowlist 첫 이메일). CLI `report`·MCP 도구가 사용(마스터 로컬 도구이므로).
- 파일 경로에 이메일을 직접 쓰지 않는다 → `uid(email) = sha256(email).hexdigest()[:16]`.

## 2. 계정별 저장소 — `backend/flow/userstore.py` (신규)

기존 전역 `watchlist.py`(단일 파일)를 대체·흡수. 감시선 저장(watch.py)과 같은 원자적 패턴.

- 파일: `<cache_dir>/users/<uid>.json` — 계정 하나당 한 파일(격리 + 원자적 per-user 쓰기).
- 스키마:
  ```json
  {"email": "master@gmail.com",
   "watchlist": [{"code":"005930","market":"KR","shares":10,"avg":230000},
                 {"code":"NVDA","market":"US","shares":5,"avg":170.0}],
   "watch_lines": {"005930": [{"price":230000,"label":"절대선"}]},
   "widget_token": "…"}
  ```
  - `market`: `"KR"`(6자리 숫자) | `"US"`(알파벳 티커).
  - `shares`/`avg`: 선택(0/null이면 시세만 — 수익 미표시). `avg`는 **해당 종목 통화**(KR=원, US=$).
  - 순서 = 배열 순서 = 표시·위젯 순서(드래그가 이 배열을 재정렬).
  - **`watch_lines`도 계정별로 이동**(상위 검토): 감시선은 절대선·예약매도 = 실제 매매가라
    관심종목보다 민감. 3개 실계정이 지금 이걸 전역 공유 중 → 격리 대상. 기존 전역
    `watch_lines.json`은 마스터 계정으로 마이그레이션.
- API(전부 email 인자 — email은 `norm_email()`로 중앙 정규화, 마스터가 두 uid로 갈리지 않게):
  - `get_watchlist(email) -> list[dict]` — **반환 계약: `[{code, market, shares, avg}]`**(항상 dict 배열).
    파일 우선, 부재 시: **마스터 계정(email==default_account)만** config 시드, **그 외 계정은 빈 배열**.
  - `get_kr_codes(email) -> list[str]` — watchlist에서 `market=='KR'` 6자리 코드만 추출. **KR 전용
    파이프라인(build_dashboard·_analyze·fetch_live_prices)은 이걸 쓴다**(dict/US 유입 차단, 아래 §6).
  - `set_watchlist(email, items) -> list[dict]` — 검증·정규화·원자적 저장.
  - `get_lines(email, code)` / `set_lines(email, code, lines)` — 계정별 감시선. **비마스터 계정은 파일 부재 시
    config 폴백 없이 항상 빈 배열**(blocker: config.watch_lines=마스터 실매도가라 폴백 시 유출). config 시드는
    마스터 계정에만. 검증 로직(형식·MAX_LINES=10)만 watch.py에서 재사용.
  - **토큰(단일 진실원 = 유저 파일):** `get_token(email)`/`ensure_token(email)`/`rotate_token(email)` — 토큰은
    유저 파일의 `widget_token` 하나에만 산다(별도 인덱스 파일 없음 — desync 제거). 회전 = 유저 파일 토큰 교체
    → 구 토큰 즉시 사망.
  - `email_for_token(token) -> str|None` — `users/` 디렉터리를 스캔해 `{widget_token: email}` 매핑을 만들고
    **메모리 캐시(디렉터리 mtime 변할 때만 재빌드)** + dict 조회. 3계정이라 스캔은 3파일. 미매칭 → **None(→게이트 401)**.
    **env `SM_WIDGET_TOKEN`은 마이그레이션 때 마스터 유저 파일에 등록**되며, 여기선 그 파일 토큰으로만 매칭
    (요청 시 default_account 재계산 금지 — 구성 변경돼도 기존 아이폰 위젯이 타 계정으로 리포인트되지 않게).
- 검증(`set_watchlist`): 항목 1~**10개**, `code`가 `^\d{6}$`면 market=KR, `^[A-Z]{1,5}([.][A-Z])?$`(대문자화)면
  market=US, 그 외 400. 중복 제거(code+market), `shares>=0`(정수), **`avg`는 통화별: KR=양의 정수, US=양의 실수(소수 보존 — int 반올림 금지), 또는 null**. 위반 시 `ValueError`(사용자 메시지).

### 계정 정체성 정책 (검토 반영)
- `default_account` = **`SM_DEFAULT_ACCOUNT` env 필수화**(마이그레이션 시 확정된 마스터 이메일, 정규화값).
  미설정이면 allowlist 첫 이메일을 쓰되 **경고 로그**(위치적 추론은 불안정 — 재구성 시 리포인트 위험).
- `norm_email(e)` = `e.strip().lower()` 단일 함수. uid·시드·토큰·세션 비교 전부 이걸 통과(마스터가 두 uid로 분리 방지).

### 마이그레이션
- 기존 전역 `<cache_dir>/watchlist.json`({"codes":[...]})이 있으면 **마스터 계정 파일로 1회 승격**
  (code→{code,market:"KR",shares:null,avg:null}), 이후 전역 파일은 무시.
- 기존 전역 `<cache_dir>/watch_lines.json`도 **마스터 계정 파일의 `watch_lines`로 1회 승격**.
- 기존 env `SM_WIDGET_TOKEN`(마스터가 이미 설치)은 **마이그레이션 때 마스터 유저 파일 `widget_token`에 1회 등록**
  (그 시점 확정 마스터 이메일에 고정). 이후 위젯 인증은 유저 파일 토큰으로만 — env를 default_account로 재해석하지 않음.
- `watchlist.py`는 `userstore` 얇은 래퍼로 남기거나 삭제(소비자 전부 userstore로 전환).

## 3. 미국 주식 시세 — `backend/flow/usquote.py` (semi.py 로직 일반화)

- 기존 `semi._us_quote`(HHDFS00000300, `/uapi/overseas-price/v1/quotations/price`, EXCD=NAS)를
  **거래소 순회**로 일반화: `price_us(client, sym) -> {price, change, currency:"USD", exch}`.
  EXCD를 **NAS→NYS→AMS** 순으로 시도, 첫 유효 응답 채택. **유효 판정은 `last>0` AND 거래량/기준가 존재**
  (스테일·미상장 거래소 오채택 방지). 순회 간 `_GAP`(0.25s) 유지 + 확정 거래소를 **종목별 캐시(TTL 12h)**해
  매 요청 재순회·호출폭주 방지(시세 캐시 60s와 별개).
- 이름: **`semi.US_NAMES` 우선, 없으면 티커 그대로**(KIS 해외현재가 응답엔 한글 종목명 필드가 없음 — 검토 확인).
  자주 담는 US 종목은 US_NAMES에 수동 보강.
- 미국 장 상태: `adr.us_market_open()`(ET) — **US 항목의 신선도(장중/마감)를 위젯 응답에 종목별로 실어**
  KR 단일 라벨과 구분(§5).
- 폴백: KIS 실패 시 semi 네이버 월드스톡(`_us_quote_naver`)은 **`.O`(NASDAQ) 하드코딩이라 NAS 종목에만** 시도,
  NYS/AMS는 폴백 없이 `price:null`(개인용, 개별 격리).

## 4. `/api/widget` 응답 (계정별 + 보유/수익)

- **인증 변경**: AuthGate `_widget_blocked`가 Bearer(바이트 파싱 유지 — 비ASCII도 안전 try/except로 str화 후
  `email_for_token`) → 매칭 email. **미매칭 → 401(동일 본문). None을 default_account로 폴백 금지**(교차계정 유출).
  기존 "위젯 미설정 503" 의미는 유지: 어떤 계정도 토큰이 없고 env도 없으면 503(핸들러), 토큰 있는데 틀리면 401.
- **게이트→핸들러 email 전달**: 게이트가 검증한 email을 `scope["state"]["widget_email"]`에 넣고, `widget_api`가
  그것을 읽어 조립(핸들러가 토큰을 다시 조회하거나 default로 폴백하지 않음 — 단일 해석 지점).
- 조립: 그 계정의 `get_watchlist(email)`로 KR/US 분기 시세(KR=`price()`, US=`price_us()`),
  보유 있으면 수익 계산. KR 세마포어 유지, US는 거래소 캐시. 부분 실패 종목은 `price:null`(행 유지).
- 응답 계약(화이트리스트 갱신):
  ```json
  {"open": false, "trade_date": "2026-07-16", "fetched_at": "…",
   "refresh_after_sec": 900,
   "items": [{"code":"005930","name":"삼성전자","market":"KR","currency":"KRW",
              "price":253500,"change":-9.3,
              "shares":10,"avg":230000,"pnl":235000,"pnl_pct":10.2}]}
  ```
  - 보유 없으면 `shares:null, avg:null, pnl:null, pnl_pct:null`.
  - 수익 = `(price-avg)*shares`(종목 통화), 수익률 = `(price/avg-1)*100`.
  - US 항목은 `market:"US", currency:"USD"` + `us_open`(장중/마감, ET). KR은 `us_open` 생략.
  - **여전히 금지**: 감시선·조언·타 계정 데이터. 화이트리스트 테스트로 고정.

## 5. Scriptable 위젯 재디자인

- 종목당 **2줄**(보유 있으면) / 1줄(없으면), 사이에 **구분 실선**(divider stack, 1px, 반투명):
  ```
  ───────────────
  삼성전자        253,500  ▲9.30%
  10주        +2,350,000  +10.2%
  ───────────────
  NVDA 엔비디아    $189.70  ▼0.85%
  5주             +$97.5   +11.6%
  ───────────────
  ```
- 폰트: 이름/현재가 `boldSystemFont(14)`, 수익 줄 `mediumSystemFont(12)` — 기존보다 확대.
- 색: 등락%·수익 모두 `Color.dynamic` 상승 빨강 / 하락 파랑, `±` 부호 항상.
- 통화: KR=`n.toLocaleString('ko-KR')`+원 생략(공간), US=`$`+소수 2자리.
- **용량은 고정 개수 금지 — 세로 예산 누적(검토 blocker성 지적).** 2줄 항목 ≈ 42pt, 1줄 ≈ 26pt, 실선 ≈ 5pt로
  누적하다 위젯 가용 세로(중간 ~110pt, 큰 ~290pt, 기기별 보수적) 초과 **직전에서 컷**. **"+N종목"은 실제로 그린
  개수 기준**으로 산정(고정 max=10 조건이면 10개 보유 시 하위가 무경고로 잘림 — 방지). 대략 중간=2줄 2~3개, 큰=2줄 6~7개.
  가이드에 "보유·수익 많으면 큰 위젯" 안내.
- 상태 라벨: 하단은 KR 거래일 기준(기존). US 항목은 각 행에 `us_open` 미반영 시 흐리게(장중이면 라이브 표식) —
  KR/US 신선도 혼동 방지. ↻ 갱신·오프라인 캐시·Keychain·계정 토큰 재입력 흐름 그대로.

## 6. 대시보드 편집 — 컴팩트 관리 리스트 (`dashboard.py`)

- 검색창 위에 **관리 리스트**: 한 줄 = `⠿(핸들) · 종목명 · 현재가 · [보유 편집]`.
- **드래그**(핸들 pointerdown→move) 순서변경, **스와이프 좌**(pointer 이동 임계) 삭제(빨강 배경+휴지통).
  - 순수 Pointer Events(외부 라이브러리 0). 스크롤과 충돌 방지: 핸들에서만 드래그 시작, 가로 이동이
    세로보다 클 때만 스와이프로 판정(임계 각도).
  - 저장: 재정렬/삭제/보유변경 시 `POST /api/watchlist`(전체 items 배열 교체) → 성공 시 카드 갱신.
  - **API 계약 변경**: `GET/POST /api/watchlist`가 `{codes:[...]}` → `{items:[{code,market,shares,avg}]}`. 화이트리스트 테스트.
  - **degrade 함정 방지(검토)**: 카드의 편집버튼을 없애므로, 드래그/스와이프 JS가 죽어도 추가·삭제·재정렬이 전부
    불가해지지 않게 — 관리 리스트에 **버튼 기반 폴백**(각 행 ▲▼·× 버튼)을 항상 렌더하고, 드래그/스와이프는
    그 위에 얹는 향상(progressive enhancement). try/catch 실패 시 버튼은 계속 동작.
- **보유 입력**: 리스트 행의 [보유 편집] → 인라인 `수량`(정수) + `평균매입가`(KR=원 정수 / US=$ 소수) 저장.
- 검색: 기존 KRX universe + **US 티커 감지**(입력이 대문자 1~5자(+.접미)면 "＋ NVDA(US) 담기" 제안, 담기 시
  서버가 price_us로 존재 확인 — 없으면 400 "티커를 찾을 수 없어요(NAS/NYS/AMS)").
- 큰 분석 카드: **KR 종목만 렌더**(US는 분석 파이프라인 없음). 순서만 반영, 편집 버튼 제거.
- **소비자별 KR/US 처리(검토 핵심 — list[dict] 파급):**
  - `build_dashboard`·`_analyze`(MCP)·`fetch_live_prices`(/api/prices): **`get_kr_codes(email)`로 KR 코드만** 넘김
    (US 티커는 KRX get_ohlcv/지표/DART/국내 price에 경로 없음 → 명시적 제외).
  - `/api/widget`(`widget_data`): 전체 items로 KR/US 분기(§4).
  - 관리 리스트·검색: 전체 items(KR+US).
  - 세션 email 해석: `scope["session"]` 있으면 그 email, 없으면(인증 비활성) `default_account`. **라우트는
    `request.session` 직접 접근 금지**(SessionMiddleware 미설치 시 AssertionError) — `scope.get`으로 방어.
  - 감시선 소비자(`/api/watch/{code}`·`live_page`·`live()` 라우트)도 세션 email로 `get_lines(email,code)`
    (시그니처 연쇄 변경: `render_live_page`·`live()`에 email 전파).

### 편집 UI JS 격리 (상위 검토 — 한 시간 전 실사고 방어)
- 드래그+스와이프는 앱에서 가장 복잡한 클라이언트 JS. dashboard.py의 기존 단일 `<script>`에 넣지 않고
  **별도 `<script>` 블록**으로 분리하고, 초기화를 `try/catch`로 감싼다 → 이 JS가 실패해도
  "편집 비활성"으로 degrade(카드·검색·반도체가 다시 통째로 안 뜨는 사고 방지).
- `node --check` 스모크를 **두 블록 모두**에 적용(test_dashboard_inline_js_parses 확장).

## 보안 (마스터 고지·동의)

- 수익 금액을 위젯에 넣음 = **위젯 토큰이 자산 정보를 지키는 키**가 된다(계정별 토큰).
  토큰 유출 시 그 계정의 보유·손익 노출. → 설치 가이드 최상단 경고 강화 + 계정별 토큰 회전 절차
  (`/widget-setup`에서 재발급 = 이전 토큰 무효화).
- 계정 격리 불변식: `email_for_token`이 틀린 계정을 반환하면 데이터 유출 → **교차계정 격리 테스트**
  (계정 A 토큰으로 계정 B 데이터 절대 조회 불가) 필수.
- 위젯 엔드포인트는 여전히 게이트 안 Bearer(공개 예외 아님) — PROTECTED 무예외 유지.

## 에러 처리

| 상황 | 처리 |
|---|---|
| US 티커 거래소 전부 실패 | 해당 종목 `price:null`(행 유지, 위젯 "—") |
| 잘못된 티커 입력 | 담기 시 400 "티커를 찾을 수 없어요(NAS/NYS/AMS)" |
| 보유 avg=0/음수 | 저장 400(사용자 메시지) |
| 토큰→계정 매칭 없음 | 401 동일 본문 |
| 유저 파일 손상 | 시드/빈 폴백(감시선 패턴) + 로그 |

## 테스트 계획

- `userstore`: 계정별 격리(A 저장이 B에 안 보임)·검증(KR/US·shares·avg 통화·개수)·원자성·마이그레이션.
- **교차계정 격리(게이트 테스트, §빌드 2):**
  - A 토큰 → B watchlist/보유/watch_lines 절대 조회 불가.
  - **`get_lines`가 비마스터 계정에 config 감시선(절대선·예약매도)을 절대 반환 안 함**(blocker 회귀 방지).
  - `email_for_token` 미매칭 → None(default 폴백 금지). env 토큰 → **고정 마스터**(default_account 바꿔도 불변).
  - **토큰 회전 후 구 토큰 → 401**(다음 요청부터).
  - 비ASCII Bearer → 401(500 아님).
- `usquote.price_us`: NAS 성공 / NAS실패→NYS 성공 / 전부 실패 None / 스테일(last>0이나 거래량0) 배제(모킹).
- `/api/widget`: 계정별 items·수익 계산·화이트리스트·부분실패 null·게이트 email이 핸들러 도달·**위젯 미설정 503 유지**.
- `get_kr_codes`: US 티커가 KR 파이프라인에서 제외됨(build_dashboard/_analyze/fetch_live_prices에 KR만).
- 수익 계산 순수 함수: KR(원 정수)·US($ 소수)·보유 없음·avg null.
- **위젯 용량**: 큰 위젯 + 10종목 전부 보유 → 세로 예산 컷 + "+N종목" 정확(무경고 잘림 없음, JS 산정 단위테스트).
- 인증 비활성(SM_AUTH_ENABLED=false): 웹 라우트가 `request.session` 크래시 없이 default_account로 동작.
- 대시보드 인라인 JS `node --check`(**편집 블록 별도 + 메인 블록 둘 다**).
- 실기기: 아이폰 드래그 순서변경·스와이프 삭제(+버튼 폴백)·보유 입력·위젯 2줄/색/실선/오버플로.

## 산출물 / 내부 빌드 순서 (한 스펙, 순차 구현)

계정=3개(실측) → 전체 계정 격리 기계장치 정당화됨. **default_account는 SM_DEFAULT_ACCOUNT 필수화**(마이그레이션
때 .env에 마스터 이메일 설정; 미설정 시 allowlist 첫 이메일 + 경고 로그).

1. **계정 저장소 기반**: `userstore.py`(watchlist(dict 배열)+get_kr_codes+watch_lines(비마스터 config 폴백 금지)+
   토큰(유저파일 단일원)+마이그레이션(watchlist·watch_lines·env토큰)) + 소비자 전환.
2. **🚧 게이트: 교차계정 격리 테스트 GREEN** — "A 토큰으로 B 데이터 절대 조회 불가(email→uid 오타/누락이
   default_account로 폴백하는 경로 포함)". **이게 통과하기 전엔 3~5(P&L 등)로 넘어가지 않는다**(상위 검토).
3. **위젯 토큰 계정화**: AuthGate Bearer→`email_for_token`(메모리 캐시), `/widget-setup` 계정별 토큰, env 하위호환.
4. **보유/수익**: 수익 계산(순수 함수) + `/api/widget` 확장(화이트리스트) + 위젯 2줄 재디자인(실선·폰트·색).
5. **미국 주식**: `usquote.py`(NAS→NYS→AMS) + 검색 티커 감지 + KR/US 혼합 조립·표시.
6. **편집 UX(가장 나중 — 취약도 최고, 실기기 의존)**: 관리 리스트 드래그/스와이프/보유입력(Pointer Events,
   별도 script+try/catch) + 카드 편집버튼 제거. **P&L 위젯(4)이 이 단계 취약성에 발목 잡히지 않게 뒤에 둔다.**
7. **가이드·보안**: `widget-guide.md` 갱신(계정 토큰·수익 경고 강화·큰 위젯 권장) + 실기기 검증.

## 재검토 이력
2026-07-17 멀티에이전트 재검토(5렌즈 × 반박검증 2인, 87 에이전트): 41건 지적 → **12건 확정 반영**.
주요: (blocker) 비마스터 계정에 config 감시선(마스터 실매도가) 폴백 누출 → 계정별 빈 배열 시작·격리 테스트.
(major) get_watchlist str→dict + US 티커가 KR 전용 파이프라인 5소비자 파손 → get_kr_codes로 KR만 추출·US는 분석 제외.
(major) env 토큰이 동적 default_account에 리포인트 → 고정 마스터 이메일 등록. (major) 위젯 고정 max=10 오버플로 무경고
잘림 → 세로 예산 동적 컷. (minor) 토큰 인덱스 이중원 → 유저파일 단일원+회전 API, 인증비활성 세션 방어, US 정규식/이름/
폴백 한계, 게이트→핸들러 email 전달. 기각 29건(대부분 확정건과 중복이거나 이미 계약에 포함).
