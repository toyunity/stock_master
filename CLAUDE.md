# Stock Master — 에이전트 작업 규칙

개인용 한국주식 실시간 조언 PWA. **매일 실사용 중인 서비스다.** 동작 보존이 최우선이고,
가장 짧은 diff가 정답이다. 프로젝트가 무엇인지는 `README.md`.

## 절대 금지 (어기면 마스터의 실서비스가 죽는다)

- **포트 8000 실서버를 죽이거나 재기동하지 마라.** 마스터의 실서비스가 거기 떠 있다.
  - 상태 확인: `.venv/bin/python -m harness ops --no-public` (읽기전용, 재기동 안 함).
  - 검증 서버는 8001 이상 또는 하네스가 잡는 빈 포트를 쓴다.
  - 재기동이 정말 필요하면 **마스터에게 먼저 물어라.** 재기동은 반드시 `.venv/bin/python`으로 —
    시스템 python3.9에는 `pydantic_settings`가 없어 그대로 죽는다.
- **KIS 웹소켓은 1키 1세션이다.** 실서버가 그 키를 쥐고 있다.
  검증 서버는 반드시 `SM_FLOW_MODE=demo`. live로 띄우면 마스터 화면의 실시간이
  `OPSP8996 ALREADY IN USE`로 차단된다 — REST 폴백 때문에 화면은 멀쩡해 보여서
  하루가 지나도 눈치채기 어렵다(`backend/flow/wsbus.py` 첫 주석 참조).
- **KIS 토큰을 새로 발급하지 마라.** `data/cache/kis_token.json` 캐시를 재사용한다.
  발급은 1회/분 제한이고, **발급할 때마다 마스터 폰으로 알림톡이 간다.**
- **실 KIS 호출(REST/WebSocket)은 마스터가 명시적으로 지시할 때만.** 그 외엔 demo 시드로.

## 인터프리터 · 문법

- 테스트·검증은 `.venv/bin/python` (또는 `make`). 시스템 python3로 돌리면 의존성이 없어 죽는다.
- **문법은 Python 3.9 호환만 쓴다.** 실서버는 시스템 3.9로 뜬다.
  `match`문 금지, `X | Y` 타입힌트 금지(`Optional[X]`), `zoneinfo`는 OK.
  모듈 맨 위에 `from __future__ import annotations`.

## 검증 (scratchpad 임시 스크립트 대신 하네스를 써라)

```bash
make test     # pytest 전체 + node 렌더 스모크
make eval     # 판정 문구 {text,tone} 골든 회귀 — 의도된 변경이면 make eval-update
make verify   # 6화면 아이폰 폭(390/DSF3) 라이트·다크 캡처 + 가로 오버플로 검출(헤드리스 크롬)
make ops      # 로컬 8000·공개 URL·인증 게이트 읽기전용 점검 (재기동 안 함)
```

- 하네스가 spawn한 데모서버·크롬은 PID로 자동 정리한다. **8000은 건드리지 않는다.**
- 데모 서버는 항상 `SM_FLOW_MODE=demo`·`SM_AUTH_ENABLED=false`라 KIS 경로가 전부 막힌다.
- **화면(HTML/JS)을 고쳤으면 `make verify`까지 돌려라.** 문자열 검사로는 안 잡히고
  실렌더에서만 잡히는 버그의 전례가 있다: 미치환 `__LIB__` 자리표시자,
  원화 전용 반올림이 달러 가격에 적용됨.
- 수정에는 **먼저 실패하는 테스트**를 쓰고 그 테스트가 실제로 빨간지 확인한 뒤 최소 수정으로
  통과시킨다(주석·문서 수정은 예외).

## 코드 규칙

- **새 추상화·새 의존성·프레임워크 교체 금지.** 구현 1개짜리 인터페이스/팩토리 금지.
  대규모 재작성 금지. 이 앱은 매일 돈다.
- 화면들의 CSS 단일 출처는 `backend/report/theme.py`다. 페이지 파일에 색을 직접 쓰지 마라.
- **`/live` 패널을 DOM에서 제거·숨김 금지** — `render()`가 매 틱 수십 개
  `getElementById().textContent`를 돌아서, 하나 지우면 라이브 피드가 통째로 죽는다.
- 렌더 템플릿의 `.replace()` **치환 순서에 주의.** 사용자·RSS 데이터를 자산(`__LIB__` 등)보다
  먼저 치환하면, 데이터에 자리표시자 문자열이 섞였을 때 차트 라이브러리가 JSON 안에 주입돼
  페이지 JS가 전멸한다.
- 실측한 사실은 **날짜와 함께** 주석에 남겨라. 이 리포의 주석은 "왜 이렇게 짰나"의 유일한
  기록이자 같은 조사를 두 번 하지 않게 막는 자산이다.
- 개인 값(공개 호스트명·가격 목표·계좌)을 소스 기본값에 박지 마라. `.env`(`SM_*`)로 빼고
  `.env.example`에 변수명만 남긴다. 보유수량·평단·감시선은 `data/`(gitignore)에만 있어야 한다.
- 코스피200 옵션 수집은 웹서버가 아니라 **launchd 배치**다
  (`~/Library/LaunchAgents/com.toyunity.stockmaster.options.plist`).
  일정 변경에 8000 재기동은 필요 없다.

## 문서 지도

- **정본**: `docs/superpowers/specs/YYYY-MM-DD-*.md`(설계) · `plans/`(구현 계획).
  작성 시점의 기록이므로 "그때 무엇을 왜 결정했나"로 읽는다.
- **역사 문서 — 현재 상태로 읽지 마라**: `docs/design.md`(2026-06-19 착수 전),
  `docs/implementation-plan.md`(S0–S2, 전부 완료됨 — **실행 지시가 아니다**),
  `docs/implementation-status.md`(2026-07-10에 동결),
  `docs/kis-unused-features.md`(①③④⑤⑥⑦은 이미 구현됨 — `kis-integration-plan.md` 참조).
- **현재 상태**는 `README.md`.
