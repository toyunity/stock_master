# 아이폰 홈 위젯(Scriptable) + 편집 가능 관심종목 — 설계

날짜: 2026-07-16 · 상태: 브레인스토밍 확정 + 멀티에이전트 재검토 반영(29건 지적 → 27건 확정 병합, 마스터 승인)

## 목적·결정

아이폰 홈 화면에서 **앱을 열지 않고** 관심종목 시세(이름·현재가·등락률)를 쓱 본다.
iOS 정책상 PWA는 홈 위젯을 만들 수 없으므로 **Scriptable(무료 앱) 위젯**이 앱 옆의
별도 표면으로 서버 API를 읽는다.

**마스터 확정 결정 3가지**:
1. 위젯 방식 = **Scriptable** (Swift/Xcode/개발자계정/Widgy 배제 — 무료·복붙 설치).
2. 위젯 내용 = **관심종목 시세 리스트** (이름·현재가·등락률).
3. 관심종목은 **앱(대시보드)에서 편집**하고 위젯은 서버 목록을 따라감.
   위젯별 파라미터 오버라이드 없음.

## 제약 (사용자 고지 완료)

- **iOS 위젯은 실시간 티커가 아니다**: 새로고침 ~15분+, OS 재량(일일 예산 40~70회).
- **맥북이 잠자면 위젯 갱신 중단**: 서버가 맥에 있음(Funnel). 위젯은 마지막 값 +
  기준 시각을 표시해 멈춤을 가시화한다(빈 화면 금지).
- **Python 3.9**(실서버 시스템 파이썬) — `match`·`X|Y` 힌트 금지.
- **공개 Funnel 전제**: "모든 경로가 실제로 잠겼는가" 불변식([[2026-07-14-public-deploy-auth-design]])을
  위젯 경로가 **깨면 안 된다** — 예외가 아니라 게이트 안의 또 다른 잠금 방식으로 통과한다.
- **KIS = 유일 컴플라이언스 시세 소스**. 개인 이용(본인 위젯)은 약관 내. 단 토큰이
  담긴 산출물을 타인과 공유하면 시세 제3자 제공이 되므로 가이드에 경고를 명시한다.

---

## 아키텍처 개요

```
아이폰 홈 위젯(Scriptable JS, 토큰은 Keychain)
   │  GET /api/widget  (Authorization: Bearer <SM_WIDGET_TOKEN>)
   ▼
AuthGate ──[/api/widget이면 Bearer 검사]──▶ 핸들러(인증 코드 0줄)
   │                                          │
   │ (그 외 경로는 기존 OAuth+TOTP 세션)       ▼
   ▼                                    KIS price() ×N (시간대 불문 단일 소스)
기존 앱 화면들                            + 일자별 TR 1회(거래일 판별, 캐시)
                                              │
관심종목: <cache_dir>/watchlist.json ◀── 대시보드 편집 UI(2단계)
  get_watchlist() 단일 접근자 — 소비자 5곳 전부 경유
```

## 1단계 — 위젯 (현 하드코딩 관심종목 기준으로 먼저 배송)

### `/api/widget` 엔드포인트

**시세는 시간대 불문 KIS `client.price()`(FHKST01010100) 단일 소스.**
KIS는 장마감 후·주말·공휴일에도 직전 세션 종가+등락률을 정확히 반환한다
(`kis.py:238` 마감 후 조회 실측 전제). ~~장외엔 FDR/캐시~~는 재검토에서 기각:
universe 캐시는 12h EOD라 월요일 저녁에 금요일 종가가 나가고, 캐시 만료 시
동기 FDR 스크랩(수 초~실패)이 위젯 시간예산을 태우며, sync 함수라 이벤트루프를
멈춘다. **위젯 요청은 어떤 경우에도 FDR 수집을 동기 대기하지 않는다.**

- 폴백(KIS 키 없음/전 종목 실패): universe 캐시를 `check_age=False`로 **읽기만**
  (stale 허용, 갱신 트리거 금지). 그마저 없으면 `503 {"error": ...}`.
- 부분 실패: 실패 종목을 빼지 말고 `price: null`로 포함(조용한 누락 금지, 위젯은 "—" 표시).
- 시장구분은 대시보드와 동일한 `market_div`(기본 UN) — 앱과 값이 항상 일치.
  UN은 NXT 애프터장(15:30~20:00)에 값이 계속 움직이므로 장외 라벨은 "종가"가 아닌
  **"마감"**으로 표기(가이드에 한 줄 고지).

**거래일 판별** (`parse_price`에 날짜 필드가 없음): 일자별 시세 TR
**FHKST01010400**(주식현재가 일자별)을 삼성전자(005930) 고정 1회 조회해 최신 행의
`stck_bsop_date` = `trade_date`. 메모리 캐시(장중 10분/장외 60분). 구현 시
**장중 당일 행 포함 여부를 verify 스킬로 실측**해 확정한다.
- `open` 판정: `_kr_market_open()`(벽시계) **AND** `trade_date == 오늘`.
  → 평일 공휴일(연 10일+)에 벽시계만으로 open:true가 되는 오표시가 **휴장일 캘린더
  없이** 자동 해소된다. TR 실패 시 벽시계 단독 폴백(공휴일 한정 부정확 허용).

**응답 계약(화이트리스트 — 테스트로 고정)**:
```json
{"open": true, "trade_date": "2026-07-16", "fetched_at": "2026-07-16T10:30:12+09:00",
 "refresh_after_sec": 900,
 "items": [{"code": "005930", "name": "삼성전자", "price": 71200, "change": 1.25}]}
```
- `change` = 등락률(%, `rate`). `refresh_after_sec` = 서버 권장 다음 갱신:
  장중 900초, 장외 `min(다음 개장까지 초, 21600)` — 클라이언트에 KST 달력 로직 불요.
- **이 필드 외 어떤 것도 추가 금지**: watch_lines(절대선·예약매도 = 실매매 의도)·조언·
  계좌성 정보는 이 엔드포인트가 메인 앱보다 약한 인증(정적 토큰 단일 팩터)이므로
  절대 유입 금지. 허용 필드 화이트리스트를 테스트로 단언해 미래 확장이 계약을
  깨면 테스트가 먼저 실패하게 한다.

### 인증 — AuthGate 안의 Bearer 검사 (공개 예외 아님)

`_PUBLIC_EXACT`에 넣지 않는다(잠금의 진실이 두 곳으로 쪼개지는 fail-open 구조).
**AuthGate가 `path == "/api/widget"`이면 `scope["headers"]`의
`Authorization: Bearer`를 `secrets.compare_digest`로 검사** — 유효하면 통과,
아니면 기존 게이트와 동일한 `401 {"error":"unauthorized"}`(본문으로 실패 사유
구분 금지). 세션 불요, 순수 ASGI로 충분. 핸들러에는 인증 코드가 없다.
→ 토큰 없는 `GET /api/widget`이 여전히 401이므로 **PROTECTED 불변식 테스트에
예외 없이 그대로 추가**된다.

- `SM_WIDGET_TOKEN` 미설정 시 게이트가 **503**을 반환(401과 구분 — "기능 꺼짐"
  신호, 핸들러 도달 전 차단).
- `SM_AUTH_ENABLED=false`(로컬/테스트)면 게이트 미장착 → 위젯 토큰 검사도 없이
  열린다. 기존 규칙("Funnel 노출은 반드시 auth_enabled=true 이후")과 동일 전제라
  추가 방어 불요 — 테스트로 이 동작을 명문화만 한다.

### 토큰 정책 — env 단일 경로, fail-closed

- **`SM_WIDGET_TOKEN` env 하나만**. 캐시파일 자동생성 경로는 만들지 않는다
  (env를 지우면 조용히 재생성 → 위젯만 영문 모를 401 — 이중 상태 금지).
- 생성: `secrets.token_urlsafe(32)`(256bit)로 한 번 만들어 `.env`에 고정.
- 검증: env가 있는데 **20자 미만이면 기동 거부**(auth.install의 fail-closed 스타일) —
  약한 토큰('stock1234')이 유일 방어선이 되는 것을 차단(레이트리밋 없는 서버).
- env 미설정이면 `/api/widget`은 503 (위젯 기능만 꺼짐, 앱은 정상 — 게이트에서 차단).
- 회전 절차(가이드에 1줄): `.env`의 토큰 교체 → 서버 재시작 → 위젯 스크립트
  1회 실행해 새 토큰 입력.

### `/widget-setup` 페이지 (인증 게이트 뒤 — 공개 아님)

토큰·스크립트를 아이폰으로 옮기는 단계가 초보 최대 실패 지점 → 파일 전송을 없앤다.
**아이폰 사파리에서 로그인(OAuth+TOTP) 후 이 페이지를 연다**:
1. 위젯 토큰 표시 + [복사] 버튼 (서버가 env에서 읽어 렌더).
2. Scriptable 스크립트 전문 + [전체 복사] 버튼 — **스크립트에 토큰은 없다**.
   Funnel URL만 서버가 채워 렌더(URL은 비밀 아님). 클립보드 복사라 스마트 문장부호
   변형(곡선따옴표 SyntaxError) 없음.
3. 번호순 설치 안내(가이드 문서 요약 + 링크).

### Scriptable 위젯 스크립트 (`StockMaster.js`)

- **토큰은 Keychain**: 최초 실행(앱 안) 시 `Keychain.contains` 없으면 Alert
  텍스트필드로 입력받아 `Keychain.set("sm_widget_token", ...)`. 위젯은
  `Keychain.get`으로 읽음. → 스크립트 파일 자체는 시크릿 없는 공유-안전 파일
  (Scriptable 스크립트는 기본 iCloud Drive 평문 동기화이므로 토큰 하드코딩 금지).
- **크기: 중간(4×2) 단일 레이아웃** — 2×2에 5종목×3필드는 판독 불가, 4×4는 실익
  없음(과설계 판정). 다른 크기는 가이드에 "중간 크기로 추가하세요" 한 줄.
  `config.widgetFamily`가 null(앱 내 미리보기)이면 medium으로 간주.
- 표시: 종목당 1행 — 이름(좌) · 현재가(우) · 등락률(우, ± 부호 항상).
  상위 5종목 + 초과분 "+N종목" 1행(2단계 최대 10 대비). `lineLimit=1` +
  `minimumScaleFactor`(LG에너지솔루션 등 긴 이름 완충).
- 하단 상태행: `open:true` → "HH:MM 장중" / `open:false` → "M/D(요일) 마감"
  (trade_date 기준 — 토요일에 금요일 값이 "10:00 기준"으로 보여 실시간 오해하는 것 방지).
- 등락 색: `Color.dynamic(라이트, 다크)` — 상승 `(#d32f2f, #ff6b6b)`,
  하락 `(#1565c0, #6ba3ff)`, 보합 기본 텍스트색. 배경은 미설정(시스템 자동).
- **네트워크 견고성**: `request.timeoutInterval = 10`(기본 60초는 위젯 실행예산
  초과 — 맥 잠자기는 Funnel이 TLS만 받고 매달리는 실패라 타임아웃 필수).
  전체 try/catch → 실패 시 캐시 렌더 + "오프라인" 배지.
- **캐시: `FileManager.local()` + `documentsDirectory` 고정** —
  iCloud FileManager는 위젯 컨텍스트에서 미다운로드 상태로 실패하고,
  cacheDirectory는 iOS가 임의 삭제. 성공 응답을 JSON으로 저장, 실패 시 로드.
- `widget.refreshAfterDate = now + refresh_after_sec`(서버 값) — 갱신 예산을
  장중에 집중, 밤·주말 낭비 제거(부수효과: 맥 야간 트래픽 감소).
- `widget.url = Funnel 대시보드 URL` — 탭하면 앱(사파리 PWA)이 열림.
  미지정 시 Scriptable 편집기가 열려 초보 사고 지점.
- **↻ 갱신 버튼**(마스터 추가 요청 2026-07-16): 하단 상태행 우측 "↻ 갱신" 스택에
  자체 `url = scriptable:///run/<스크립트명>?mode=refresh` — 탭하면 Scriptable
  앱에서 스크립트가 즉시 실행되어 **KIS 최신 시세를 전체 화면 표(UITable)로 표시**
  하고 캐시를 갱신한다. 위젯 숫자 자체의 즉시 갱신은 iOS가 허용하지 않음
  (인터랙티브 위젯 버튼은 네이티브 App Intents 전용 — Scriptable 불가, 사용자 고지
  완료). 위젯은 다음 OS 갱신 때 새 값 반영. 몸통 탭(대시보드 열기)과 영역 구분.

## 2단계 — 편집 가능 관심종목 (위젯 검증 후)

### 저장소 — `backend/flow/watchlist.py` (감시선 `watch.py` 패턴 복제)

- 파일: `<cache_dir>/watchlist.json` = `{"codes": ["005930", ...]}`.
  원자적 쓰기(temp+`os.replace`) + 모듈 Lock. 부재/손상 시 config 시드 폴백.
- **`get_watchlist() -> list[str]` 단일 접근자** — 파일값 우선, 없으면
  `settings.watchlist`(시드로 격하). **`settings.watchlist` 직접 참조 금지.**
- **소비자 5곳 전부 경유** (재검토에서 2곳 누락 적발):
  ① 대시보드 카드(`build_dashboard`) ② `/api/prices` ③ `/api/widget`
  ④ CLI `report`(`cli.py:152`) ⑤ MCP 도구(`mcp/tools.py:78,89`
  `watchlist_summary`·`dashboard_data`) — 안 바꾸면 앱에서 편집해도 MCP/리포트가
  옛 목록을 보여주는 사일런트 분기. (`tests/test_config.py:6`의
  `len(s.watchlist) >= 5` 단언도 시드 의미로 조정.)

### 편집 API/UI

- `GET /api/watchlist` → `{"items":[{"code","name"}]}` /
  `POST /api/watchlist` body `{"codes":[...]}` 전체 교체(감시선과 동일 패턴).
- 검증(400 + 사용자 메시지): 6자리 코드 정규식 · 중복 제거 · **최소 1개 ·
  최대 10개**(`MAX_CODES=10` — 대시보드 렌더·KIS 버스트·위젯 공간 모두 커버).
- 순서 = 저장 순서 = 표시 순서. **새 종목은 맨 앞에 추가**(위젯 상위 5에 바로
  보임). 순서변경 UI는 만들지 않는다(YAGNI).
- UI: 대시보드 기존 이름검색(universe) 결과에 [＋추가], 카드에 [－삭제].

### 이름 해석 일반화 (신규 종목이 '035720' 숫자로 보이는 문제)

- 위젯·대시보드 카드 공통: **universe(전 KRX 코드→이름, 12h 캐시) 우선,
  `display_name` 폴백**(둘 다 실패 시 코드 그대로). universe 조회는 stale 허용
  읽기 전용 — 위젯 경로에서 수집 트리거 금지.
- 뉴스 별칭: `match.py`의 `names.get(code, [])`이 신규 종목에서 빈 리스트 →
  뉴스 영구 0건. **universe 이름 1개를 자동 별칭으로 보강**(STOCK_NAMES는 수동
  별칭 보강용 유지). 신규 종목의 별칭 1개 매칭 한계는 가이드에 알려진 제약으로.

### KIS 동시 호출 제한

`fetch_live_prices`의 무제한 `asyncio.gather`(현 5종목이라 안전)가 10종목 ×
대시보드 12초 폴링 × 위젯과 겹치면 KIS 초당 20건/간헐 500(EGW00201, `kis.py:321`
실측) 노출 → **`asyncio.Semaphore`(동시 5~8) 추가**(candles의 `_GAP=0.2` 선례).

---

## 에러 처리 요약

| 상황 | 서버 | 위젯 |
|---|---|---|
| 토큰 없음/틀림 | 게이트 401(본문 동일) | Keychain 재입력 안내 문구 렌더 |
| KIS 일부 종목 실패 | `price: null` 포함 | 해당 행 "—" |
| KIS 전체 실패/키 없음 | universe stale 폴백, 없으면 503 | 캐시 렌더 + "오프라인" |
| 맥 잠자기/서버 다운 | (응답 없음) | 10초 타임아웃 → 캐시 + "오프라인" |
| env 토큰 미설정 | `/api/widget` 503 | — (설치 전 단계) |
| env 토큰 20자 미만 | **기동 거부**(fail-closed) | — |

## 테스트 계획

- **인증 불변식**: `/api/widget`을 PROTECTED 파라미터라이즈에 **예외 없이 추가**
  (무토큰 401). + 올바른 토큰 200 · 틀린 토큰 401 · auth_disabled 시 동작 정의.
- **응답 계약**: 허용 필드 화이트리스트 단언(초과 필드 = 실패).
- **거래일/open 판정**: 순수 함수로 분리(공휴일·주말·장전·애프터장 케이스).
- **watchlist 저장소**: 검증(개수·형식·중복)·원자성·시드 폴백 — `watch.py` 테스트 미러.
- **이름 해석**: universe 히트/미스/폴백 체인.
- **실측(verify 스킬)**: FHKST01010400 장중 당일 행 포함 여부, 장외 `price()` 값,
  Funnel 경유 위젯 왕복.

## 산출물

1. 백엔드: `/api/widget` + AuthGate Bearer + `/widget-setup` + (2단계) watchlist 모듈·API·UI.
2. `StockMaster.js` — Scriptable 스크립트(토큰 없음, 공유-안전).
3. **`docs/widget-guide.md` — 마스터용 설치·사용 가이드**(초보 눈높이, 스크린샷 자리):
   - 설치 5단계: ① App Store에서 Scriptable 설치 → ② 아이폰 사파리로
     `/widget-setup` 접속(구글 로그인+2FA) → ③ 스크립트 [전체 복사] → Scriptable
     새 스크립트 붙여넣기 → 실행 → 토큰 붙여넣기(1회) → ④ 홈 화면 길게 누르기 →
     ＋ → Scriptable → **중간 크기** → 추가 → ⑤ 위젯 길게 누르기 → 편집 →
     Script: StockMaster 지정 (⚠ 이 단계를 빼먹으면 'Tap to configure' 방치 —
     최다 실수).
   - 사용법: 라벨 의미("장중"/"마감" — 마감값은 NXT 애프터장 반영 고지),
     갱신 주기(~15분+, OS 재량), 맥 잠자면 "오프라인", 탭하면 앱 열림,
     **↻ 갱신 탭 = 즉시 실시간 시세 표**(위젯 숫자는 다음 OS 갱신 때 반영).
   - 문제해결: 401/재입력 → 스크립트 실행해 토큰 재입력, 빈 위젯 → 서버·Funnel 확인
     ([[server-restart-ops]] 참조), 토큰 회전 절차.
   - **경고(최상단)**: 토큰·스크립트 타인 공유 금지 — KIS 시세 제3자 제공은 약관 위반.

## 단계 배송

- **1단계**: `/api/widget`(하드코딩 관심종목) + AuthGate Bearer + `/widget-setup` +
  `StockMaster.js` + 가이드 → **홈 화면 위젯으로 Funnel 왕복을 실기기 검증**.
- **2단계**: watchlist 저장소·편집 API/UI·이름 해석·세마포어 → 편집이 대시보드·
  위젯·MCP·리포트에 일괄 반영.

## 재검토 이력

2026-07-16 멀티에이전트 재검토(리뷰어 5렌즈 × 반박검증 2인, 63 에이전트):
29건 지적 → 27건 확정·2건 기각. 주요 반영: 장외 FDR 소스 → KIS 단일(blocker),
_PUBLIC_EXACT 예외 → AuthGate 내 Bearer(major), 토큰 .js 하드코딩 → Keychain(major),
토큰 env 단일+fail-closed(major), watchlist 소비자 5곳(major), 이름 해석
일반화(major), 크기 3종 → 중간 단일(과설계), trade_date/fetched_at 분리,
공휴일 open 오표시 자동 해소, 응답 화이트리스트, 세마포어, 딥링크, 다크모드 색.
기각 2건: "토큰 검증 순서 명시"(게이트 검사로 무의미), "오프라인 캐시 1단계 불필요".
