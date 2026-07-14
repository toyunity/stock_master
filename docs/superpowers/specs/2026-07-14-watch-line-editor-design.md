# 감시선 편집·저장 + 알림 정직화 — 설계

날짜: 2026-07-14 · 상태: 브레인스토밍 확정(A/C 확정, B 풀기능=패널+탭+드래그)

## 목적

두 결함을 해결한다.

1. **알림 허용 버튼 무반응** — `#notifbtn`은 `Notification` API가 있고 권한이
   `default`일 때만 표시된다. 아이폰을 `http://<맥IP>:8000`(비보안 컨텍스트)로 접속하면
   `Notification` API 자체가 없어 버튼이 안 뜨거나 눌러도 아무 일이 없다. **OS 웹 알림은
   http-LAN(비-secure-context)에서 원천 불가**(메모리·PWA 제약). 반면 소리(Web Audio
   beep)·화면 내 배너(`#walert`)는 보안 컨텍스트 없이도 동작한다.
2. **감시선 조절 불가** — 감시선은 `SM_WATCH_LINES` env / config 기본값으로만 주입되고
   UI에서 편집·저장할 수단이 전무하다(localStorage·쓰기 API 없음).

사용 환경: 아이폰 PWA(http-LAN) + 맥(localhost)을 **섞어서** 사용 → 저장은 서버에 두어
한 기기에서 바꾸면 다른 기기에도 반영되게 한다.

## 제약 (설계를 좌우)

- **비보안 컨텍스트**: 아이폰 http-LAN에선 `Notification`·서비스워커·푸시 불가. 소리·화면
  배너만 신뢰. → C는 기기 능력을 감지해 **정직하게** 표시한다.
- **1인용**: 인증·동시성 고려 불필요. 원자적 파일 쓰기(temp+rename)로 부분쓰기만 방지.
- **Python 3.9**: 실서버는 시스템 3.9(venv). `match`문·`X|Y` 힌트 금지, zoneinfo OK.
- **차트 라이브러리**: 번들 `lightweight-charts.js`에 `coordinateToPrice`·
  `priceToCoordinate`·`subscribeClick`/`unsubscribeClick`·`createPriceLine`/
  `removePriceLine`·priceLine `applyOptions` 모두 존재(실측) → 탭·드래그 구현 가능.

---

## A. 감시선 서버 저장 (확정)

### `backend/flow/watch.py` (신규)
- 저장 파일: `<cache_dir>/watch_lines.json` — `{"000660":[{"price":1853000,"label":"절대선"}, …]}`.
- `get_lines(code) -> list[dict]`: 파일을 읽어 **코드 키가 있으면 파일값을 그대로**(빈 배열
  포함 — 사용자가 전부 지운 상태도 영속), **없으면 `settings.watch_lines.get(code) or []`**
  로 폴백. 파일 손상/부재 시 config 폴백(예외 삼키고 로그).
- `set_lines(code, lines) -> list[dict]`: 검증 후 원자적 쓰기, 정규화된 리스트 반환.
  - 검증: `price`는 유한 실수 & > 0; `label`은 문자열 strip 후 1~20자; 줄 수 ≤ 10.
    위반 시 `ValueError`(메시지 포함). 알 수 없는 키는 무시(price/label만 취함).
  - 정규화: `price`는 int(원 단위 반올림), `label`은 strip. 입력 순서 유지.
  - 쓰기: 파일 전체 dict 로드 → `d[code]=정규화값` → temp 파일에 json.dump →
    `os.replace`(원자적). 모듈 레벨 `threading.Lock`으로 직렬화.

### API (`backend/api/app.py`)
- `GET /api/watch/{code}` → 코드 6자리 검증 → `{"lines": watch.get_lines(code)}`.
- `POST /api/watch/{code}` (body `{"lines":[{"price":num,"label":str}, …]}`)
  → `watch.set_lines` 호출 → `ValueError`면 `400 {"error": msg}`, 성공 시
  `{"lines": saved}`. 코드 형식 오류 404.

### 주입 변경 (`backend/report/live_page.py`)
- `render_live_page`가 초기 WATCH를 **`watch.get_lines(code)`**에서 주입(기존
  `settings.watch_lines` 직접 읽기 대체). 기존 `</` 이스케이프·타입가드 유지.

---

## B. 편집 UI — 패널 + 차트 탭 + 드래그 (풀기능 확정)

### 상태 리팩터 (`live_page.py` JS)
- `const WATCH` → **`let WATCH`**(가변). `const armed` → `let armed`.
- `let priceLines=[]` — 생성된 IPriceLine 추적(재렌더 시 `removePriceLine`).
- `function renderWatchLines()`: 기존 priceLines 전부 제거 → WATCH로 재생성 →
  `priceLines` 갱신. 초기 1회 + 저장/드래그 후 호출.
- `function rearm()`: `armed = WATCH.map(()=>true)`(WATCH 변경 때마다).

### 설정 패널 (신규 `<details class="panel" id="wl-panel">`)
- 제목 "🎯 감시선 설정". 열면 편집용 **작업 복사본**(`wlDraft`)으로 줄 목록 표시.
- 줄마다: `가격`(number input) · `라벨`(text input, maxlength 20) · `삭제` 버튼.
- 버튼: **추가**(빈 줄 push) · **저장**(POST) · 상태 텍스트(`wl-status`).
- **저장**: draft에서 유효 줄(가격 숫자>0 & 라벨 비지 않음)만 모아 `POST /api/watch/{code}`.
  - 성공: `WATCH=응답.lines` → `renderWatchLines()` → `rearm()` → draft 동기화 →
    "저장됨 ✓ (기기 간 반영됨)".
  - 400: `wl-status`에 서버 메시지, 저장 안 함.
  - 네트워크 실패: "저장 실패 — 재시도". (SSE 재연결과 독립)
- 클라 사전검증: 가격 비었거나 ≤0 또는 라벨 공백인 줄은 저장에서 제외(안내). 전부 지우고
  저장하면 빈 배열 전송(감시선 없음 상태 영속).

### 차트 탭(선 추가)
- `pchart.subscribeClick(param => …)`: `param.point` 있으면
  `price = pseries.coordinateToPrice(param.point.y)`. null 아니면 draft에 `{price:
  round(price), label:'감시선'}` 추가 → 패널 자동 열고 해당 줄로 스크롤 → 사용자가
  라벨/가격 다듬어 저장. (탭만으론 저장 안 함 — 명시적 저장 필요)
- 드래그와 충돌 방지: 아래 드래그가 시작된 포인터 시퀀스에서는 click 이벤트를 무시
  (`draggedRecently` 플래그, pointerup 후 300ms).

### 드래그 이동(기존 선)
- `#pchart` 컨테이너에 pointer 핸들러(capture 단계):
  - `pointerdown`: y좌표로 각 WATCH 선의 `pseries.priceToCoordinate(w.price)` 계산,
    |Δy| ≤ 10px 이내 가장 가까운 선을 잡음(drag index 확정). 잡히면
    `preventDefault()`+`setPointerCapture` 로 차트 자체 팬/스크롤 억제.
  - `pointermove`: `price=coordinateToPrice(y)` → `priceLines[i].applyOptions({price})`
    로 실시간 이동 + draft/패널 행 값 동기화.
  - `pointerup`: `WATCH[i].price=round(price)` 확정 → `POST` 저장 → `rearm()` →
    `draggedRecently` 설정(click-add 억제).
  - 선을 안 잡았으면(빈 영역) 아무 것도 안 함 → 차트 기본 팬/탭 그대로.
- **리스크**: 모바일에서 차트 자체 터치 제스처와의 간섭. 드래그가 불안정하면 패널+탭이
  완전한 폴백(기능 손실 없음). 구현 시 실기기 확인 항목으로 표시.

---

## C. 알림 정직화 (확정, 버그 수정)

- 소리(beep)·화면 배너(`#walert`)는 모든 기기에서 동작 → **주 알림**. 첫 터치
  `pointerdown`에서 오디오 잠금 해제(기존) 유지.
- `NOTIF_OK = (typeof Notification!=='undefined')` 감지 후 `#notifbtn` 적응:
  - **OS 알림 가능**(맥 localhost 등) & 권한 `default`: "🔔 OS 알림 허용" → 클릭 시
    `unlockAudio()` + `Notification.requestPermission()`(기존 동작, 실제 작동 확인).
  - **불가**(아이폰 http-LAN): 버튼을 **"🔔 소리 테스트"**로 바꿔 클릭 시
    `unlockAudio()+beep()`(소리 켜짐 즉시 확인) + `#walert`에 안내
    "이 기기에선 소리·화면 알림만 — OS 알림은 https 필요".
  - OS 알림 이미 `granted`거나 `denied`: OS 알림 버튼 숨김, 소리 테스트만 제공.
- `notifyWatch`는 그대로 `#walert` 텍스트 + (granted일 때만) `new Notification` 시도.

---

## 데이터 흐름

로드 → 서버가 `watch.get_lines`로 WATCH 주입 → `renderWatchLines()`·`rearm()`·패널 렌더.
편집(패널 입력/차트 탭/드래그) → 저장 → `POST /api/watch/{code}` → 서버 영속 → 클라
`WATCH` 갱신·선 재렌더·재무장. SSE 스냅샷 가격 → `checkWatch` → 소리+배너(+가능 시 OS 알림).

## 검증·에러 처리

- 서버: 가격 유한 양수, 라벨 1~20자, ≤10줄 아니면 400. 원자적 쓰기. 코드 정규식 6자리.
- 클라: 무효 줄은 저장 제외·안내. 저장 실패 시 상태 표시(화면 데이터 흐름과 독립).
- 파일 손상 시 config 폴백(화면 안 죽음).

## 테스트

- 백엔드(`tests/test_watch.py` 신규): get/set 왕복 · 검증 거부(음수가격/빈라벨/11줄/비수치)
  · 파일이 config 덮어씀 · 빈 배열 영속(전부 삭제) · 손상 파일 폴백 · 원자적 쓰기(temp 잔재 없음).
- API(`tests/test_live_api.py` 확장): `GET /api/watch/000660` 기본값 · `POST` 왕복 ·
  `POST` 무효 400 · 잘못된 코드 404.
- 프론트(`tests/test_live_page_js.py` 확장, node 하니스): 패널이 WATCH로 줄 렌더 ·
  저장이 올바른 POST payload 구성(fetch 목으로 캡처) · 차트 탭이 draft에 줄 추가
  (subscribeClick 콜백 직접 호출) · `NOTIF_OK` 유무에 따라 버튼 문구 정직 · 기존 render
  스모크·재연결 테스트 유지(회귀 방지).

## 스코프·리스크

- 드래그 이동만 유일한 고위험 요소(모바일 제스처 간섭) — 패널+탭이 완전한 폴백이라
  기능 손실 없음. 나머지(저장·패널·탭·알림)는 저위험.
- YAGNI: 방향(위/아래) 구분·색상 커스터마이즈·종목별 대량편집은 제외. 가격+라벨만.
