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
- API(전부 email 인자):
  - `get_watchlist(email) -> list[dict]` — 파일 우선, 없으면 config 시드(마스터 계정 최초 1회만 시드; 그 외 계정은 빈 리스트).
  - `set_watchlist(email, items) -> list[dict]` — 검증·정규화·원자적 저장.
  - `get_lines(email, code)` / `set_lines(email, code, lines)` — 계정별 감시선(watch.py 검증 로직 재사용, MAX_LINES=10).
  - `get_token(email) -> str|None` / `ensure_token(email) -> str` — 계정 위젯 토큰(없으면 `secrets.token_urlsafe(32)` 생성·저장).
  - `email_for_token(token) -> str|None` — 토큰 역참조. `<cache_dir>/users/_tokens.json` 인덱스(`{token: email}`)를
    **메모리 캐시**(mtime 변할 때만 리로드) + dict 조회 O(1). ASGI 게이트가 위젯 요청마다 디스크를 읽지 않는다(상위 검토).
    env `SM_WIDGET_TOKEN`도 이 조회에서 default_account로 인식(하위호환).
- 검증(`set_watchlist`): 항목 1~**10개**, `code` 6자리숫자(KR) 또는 `^[A-Z]{1,5}$`(US, 대문자화),
  중복 제거(code+market 기준), `shares>=0`, `avg>0 or null`. 위반 시 `ValueError`(사용자 메시지).

### 마이그레이션
- 기존 전역 `<cache_dir>/watchlist.json`({"codes":[...]})이 있으면 **마스터 계정 파일로 1회 승격**
  (code→{code,market:"KR",shares:null,avg:null}), 이후 전역 파일은 무시. `watchlist.py`는
  `userstore` 얇은 래퍼로 남기거나 삭제(소비자 전부 userstore로 전환).
- 기존 env `SM_WIDGET_TOKEN`(마스터가 이미 아이폰에 설치)은 **마스터 계정 토큰으로 등록**해
  기존 위젯이 안 끊기게 한다(`email_for_token`이 env 토큰→default_account도 인식).

## 3. 미국 주식 시세 — `backend/flow/usquote.py` (semi.py 로직 일반화)

- 기존 `semi._us_quote`(HHDFS00000300, `/uapi/overseas-price/v1/quotations/price`, EXCD=NAS)를
  **거래소 순회**로 일반화: `price_us(client, sym) -> {price, change, currency:"USD", exch}`.
  EXCD를 **NAS→NYS→AMS** 순으로 시도, 첫 유효 응답 채택(결과를 종목별 캐시해 매번 순회 방지).
- 이름: `semi.US_NAMES` + KIS 응답의 종목명 필드(있으면) → 없으면 티커 그대로.
- 미국 장 상태: `adr.us_market_open()`(ET) — 위젯 상태 라벨용(장중/마감, ET 기준).
- 폴백: KIS 실패 시 semi의 네이버 월드스톡(`_us_quote_naver`) 재사용(개인용, 개별 격리).

## 4. `/api/widget` 응답 (계정별 + 보유/수익)

- **인증 변경**: AuthGate `_widget_blocked`가 Bearer 토큰 → `userstore.email_for_token(token)`.
  매칭 없으면 401(동일 본문). 미설정 계정/토큰이면 401. (env 토큰은 마스터 매핑.)
- 조립: 그 계정의 `get_watchlist(email)`로 KR/US 혼합 시세 조회(KR=`price()`, US=`price_us()`),
  보유 있으면 수익 계산. KR 세마포어 유지, US는 거래소 캐시.
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
- 크기: **중간(4×2)=상위 3종목**, **큰(4×4)=최대 10**. 초과분 "+N종목". (가이드에 "보유·수익은 큰 위젯 권장".)
- 상태 라벨: KR/US 혼합이면 KR 거래일 기준(기존) + 위젯 하단 유지. ↻ 갱신·오프라인 캐시·Keychain 그대로.

## 6. 대시보드 편집 — 컴팩트 관리 리스트 (`dashboard.py`)

- 검색창 위에 **관리 리스트**: 한 줄 = `⠿(핸들) · 종목명 · 현재가 · [보유 편집]`.
- **드래그**(핸들 pointerdown→move) 순서변경, **스와이프 좌**(pointer 이동 임계) 삭제(빨강 배경+휴지통).
  - 순수 Pointer Events(외부 라이브러리 0). 스크롤과 충돌 방지: 핸들에서만 드래그 시작, 가로 이동이
    세로보다 클 때만 스와이프로 판정(임계 각도).
  - 저장: 재정렬/삭제/보유변경 시 `POST /api/watchlist`(전체 배열 교체) → 성공 시 카드 갱신.
- **보유 입력**: 리스트 행의 [보유 편집] → 인라인 `수량` + `평균매입가`(통화 라벨 KR 원/US $) 저장.
- 검색: 기존 KRX universe + **US 티커 감지**(입력이 대문자 1~5자면 "＋ NVDA(US) 담기" 제안).
- 큰 분석 카드: 순서만 반영, 편집 버튼 제거(관리 리스트로 일원화 → "제거 표시 자연스럽게").
- 소비자 전환: `index`·`/api/prices`·`/api/widget`·CLI `report`·MCP → `userstore.get_watchlist(email 또는 default_account)`.
  감시선 소비자(`/api/watch/{code}`·`live_page`)도 세션 이메일로 `get_lines(email,code)`.

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

- `userstore`: 계정별 격리(A 저장이 B에 안 보임)·검증(KR/US·shares·avg·개수)·원자성·마이그레이션·토큰 인덱스.
- `email_for_token`: 정상·env 토큰→마스터·미매칭 None. **교차계정 격리**(A 토큰→B 데이터 불가).
- `usquote.price_us`: NAS 성공 / NAS실패→NYS 성공 / 전부 실패 None(모킹).
- `/api/widget`: 계정별 items·수익 계산·화이트리스트·부분실패 null. auth Bearer→계정 매핑.
- 수익 계산 순수 함수: KR/US 통화·보유 없음·avg null.
- 대시보드 인라인 JS `node --check`(드래그/스와이프 추가로 회귀 위험 ↑ — 필수).
- 실기기: 아이폰에서 드래그 순서변경·스와이프 삭제·보유 입력·위젯 2줄/색/실선.

## 산출물 / 내부 빌드 순서 (한 스펙, 순차 구현)

계정=3개(실측) → 전체 계정 격리 기계장치 정당화됨. default_account = allowlist 첫 이메일(SM_DEFAULT_ACCOUNT 미설정).

1. **계정 저장소 기반**: `userstore.py`(watchlist+watch_lines+token, 마이그레이션 포함) + 소비자 전환.
2. **🚧 게이트: 교차계정 격리 테스트 GREEN** — "A 토큰으로 B 데이터 절대 조회 불가(email→uid 오타/누락이
   default_account로 폴백하는 경로 포함)". **이게 통과하기 전엔 3~5(P&L 등)로 넘어가지 않는다**(상위 검토).
3. **위젯 토큰 계정화**: AuthGate Bearer→`email_for_token`(메모리 캐시), `/widget-setup` 계정별 토큰, env 하위호환.
4. **보유/수익**: 수익 계산(순수 함수) + `/api/widget` 확장(화이트리스트) + 위젯 2줄 재디자인(실선·폰트·색).
5. **미국 주식**: `usquote.py`(NAS→NYS→AMS) + 검색 티커 감지 + KR/US 혼합 조립·표시.
6. **편집 UX(가장 나중 — 취약도 최고, 실기기 의존)**: 관리 리스트 드래그/스와이프/보유입력(Pointer Events,
   별도 script+try/catch) + 카드 편집버튼 제거. **P&L 위젯(4)이 이 단계 취약성에 발목 잡히지 않게 뒤에 둔다.**
7. **가이드·보안**: `widget-guide.md` 갱신(계정 토큰·수익 경고 강화·큰 위젯 권장) + 실기기 검증.

## 재검토 예정
멀티에이전트 재검토(보안=계정격리/토큰, iOS=드래그·스와이프·2줄레이아웃, 코드정합=userstore 소비자,
데이터=US 거래소순회/통화, 범위=YAGNI) 후 확정.
