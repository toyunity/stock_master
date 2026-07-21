# Stock Master 개발 하네스 설계

- 날짜: 2026-07-22
- 상태: 설계 승인 대기
- 범위: 4개 서브커맨드(verify·test·eval·ops)를 **단일 진입점** 하네스로 + GitHub Actions CI(test·eval)

## 1. 배경·문제

지금 이 프로젝트의 개발 루프는 매 세션 다음이 반복된다.

- **시각 검증 도구가 휘발성**: `cdp_shot.py`·`build_baked.py`·`cdp_region.py`가 세션
  scratchpad에만 있어, 세션이 끝나면 사라지고 다음 세션에 재작성한다. 리디자인
  반복(라이트/다크 5화면 캡처)이 매번 처음부터다.
- **검증 레시피가 문서로만 존재**: `.claude/skills/verify`에 절차는 적혀 있지만 실행
  가능한 스크립트가 repo에 없다.
- **테스트 실행이 흩어짐**: pytest 48개 + node 스모크(pytest 내부 subprocess)를 한
  커맨드로 묶은 러너가 없고, CI도 없다(`.github/workflows` 없음).
- **판정 회귀를 못 잡음**: 판정 텍스트/톤은 순수 함수인데(예 `credit.py`,
  `shortbal.py`), 톤이 잘못 바뀌는 회귀(커밋 `7f31fc9` "공매도 평시·신용 상환이
  빨강") 를 자동으로 잡는 골든 테스트가 없다.
- **운영 점검이 수동**: 헬스·Funnel·인증 게이트·KIS 세션 상태를 매번 손으로 curl.

목표: 위 네 가지를 **repo에 커밋된 재현 가능한 하네스**로 고정한다.

## 2. 하드 제약 (반드시 보존)

- **마스터 실서버(8000)를 절대 죽이지 않는다.** 하네스가 서버를 띄우거나 죽일 때
  `pkill -f "...port NNNN"` 패턴을 **절대 쓰지 않는다**(포트 인자 하나 틀리면 8000을
  매칭). 반드시 **자기가 spawn한 PID를 직접 들고 그 PID만 종료**한다. 재기동 경로는
  "대상 PID ≠ 8000 리스너" 양성 확인 후에만.
- **검증 서버는 항상 `SM_FLOW_MODE=demo`.** 라이브로 띄우면 KIS 1키1세션이 마스터
  실시간 세션과 충돌(ALREADY/EOF). 하네스 서버 프로세스는 `SM_FLOW_MODE=demo`·
  `SM_AUTH_ENABLED=false`를 **강제 주입**한다(환경/.env로 덮이지 않게).
- **KIS 토큰 재발급 금지.** verify/test/eval 어느 것도 KIS REST/WS를 호출하지 않는다
  (전부 demo 시드 데이터). ops의 라이브 점검은 읽기전용 `/healthz`·공개 URL만.
- **Python 3.9 호환 문법만**(match문·`X|Y` 타입힌트 금지, zoneinfo OK). 하네스도
  py3.9로 돈다.
- **앱 런타임에 안 섞음.** 하네스는 top-level `harness/` 패키지. `pyproject`의
  `[tool.setuptools.packages.find] include = ["backend*"]`가 `harness`를 안 잡으므로
  배포본에 실리지 않는다(검증 항목).
- **산출물은 gitignore.** 스크린샷·베이크 HTML은 `harness/artifacts/`에 쌓고 커밋 안 함.

## 3. 아키텍처

### 3.1 디렉터리

```
harness/
  __init__.py
  __main__.py          # python -m harness <verify|test|eval|ops> [opts]
  core/
    __init__.py
    server.py          # 데모서버 수명주기(PID 추적 spawn·/healthz 대기·contextmanager 정리)
    ports.py           # 빈 TCP 포트 할당(0번 바인드 후 회수)
    cdp.py             # 헤드리스 크롬 CDP 클라이언트(디바이스 메트릭·미디어·샷·closeTarget)
    bake.py            # /live 무한 SSE → 정적 HTML 베이킹(현 build_baked 로직 승격)
  cmd/
    __init__.py
    verify.py          # 5화면 × 라이트/다크 스크린샷 + 오버플로 체크
    test.py            # pytest + node 스모크 러너
    eval.py            # 판정 골든 회귀
    ops.py             # 읽기전용 운영 점검(+가드된 재기동)
  scenarios/           # eval 입력 시드 + 골든
    *.json             # 입력 상태
    golden/*.json      # 기대 판정 출력
  artifacts/           # (gitignore) 스크린샷·베이크 산출물
  README.md            # 사용법
Makefile               # make verify / test / eval / ops / ci
.github/workflows/test.yml
```

`Makefile` 별칭은 `python -m harness ...`를 감싼 얇은 편의 계층일 뿐. 진짜 로직은
파이썬에 있다(테스트·CI 가능).

### 3.2 공유 코어

**`core/server.py` — 가장 안전이 중요한 모듈**

```
@contextmanager
def demo_server(port=None) -> Iterator[ServerHandle]:
    port = port or ports.free_port()
    env = {**os.environ, "SM_FLOW_MODE": "demo", "SM_AUTH_ENABLED": "false"}
    proc = subprocess.Popen([sys.executable, "-m", "backend.cli", "serve",
                             "--host", "127.0.0.1", "--port", str(port)], env=env)
    try:
        _wait_healthz(port, timeout=20)   # GET /healthz == {"ok":true}
        yield ServerHandle(port=port, pid=proc.pid, base=f"http://127.0.0.1:{port}")
    finally:
        proc.terminate();  proc.wait(timeout=8)   # ★ PID로만 종료, pkill 안 씀
        if proc.poll() is None: proc.kill()
```

- 인터프리터는 `sys.executable`(= 하네스를 실행한 `.venv/bin/python`).
- 포트는 기본 **임의 빈 포트**(8000/8001 등 고정 포트 회피 → 충돌·오죽임 원천 차단).
- `ServerHandle`은 `pid`·`port`·`base`를 담는다.

**`core/cdp.py`** — 헤드리스 크롬을 `--remote-debugging-port`로 띄우고 CDP로
`Emulation.setDeviceMetricsOverride`(390/DSF3/mobile)·`setEmulatedMedia`
(prefers-color-scheme)·`Page.captureScreenshot`. 캡처 후 `Target.closeTarget`으로
탭 정리, 종료 시 크롬 프로세스도 PID로 종료. captureBeyondViewport 타일 아티팩트(약
8926 CSS px 초과) 회피를 위해 뷰포트 바운드 캡처를 기본으로.

**`core/bake.py`** — 현 `build_baked.py` 로직 승격: SSE 1스냅샷 + canned fetch 맵을
`window.__SNAP__`/`__FMAP__` + `EventSource`/`fetch` 스텁으로 `<body>` 직후 주입해,
무한 SSE 페이지가 멈추지 않고 완전 렌더된 정적 HTML을 만든다. `expand` 옵션으로
`details` 전개.

### 3.3 서브커맨드

#### `verify` — 시각 검증
1. `demo_server()` 컨텍스트 진입.
2. `/live/000660`은 `bake.py`로 정적화, 나머지 4화면은 데모 라우트 직접 로드:
   - `/live/000660` (baked)
   - `/` (대시보드)
   - `/scanner`
   - **로그인/2FA**: 인증은 demo에서 off이므로 `backend/api/auth.py`의 페이지
     렌더 함수로 HTML을 직접 만들어 `file://`로 캡처(라우트가 안 뜨므로).
   - `/widget-setup`
3. 각 화면을 **라이트+다크 2벌**, 390px/DSF3로 `harness/artifacts/`에 PNG 저장.
4. 각 샷의 스크롤폭(`scrollWidth`)을 읽어 **가로 오버플로(>390) 검출** → 있으면
   경고와 함께 exit 1.
5. 컨텍스트 종료 시 서버·크롬 PID 정리.
6. 옵션: `--only live,dashboard`(부분), `--theme light|dark|both`.

#### `test` — 테스트 러너
- `pytest -q` 실행(48 파일). node 스모크는 pytest 내부에서 이미 subprocess로 도므로
  래핑만 하면 됨. node 미설치면 해당 테스트 skip(현 동작 유지).
- 데모/py3.9 가드 안내 출력(예: 실행 인터프리터가 `.venv`인지 경고).
- 종료코드 전파. `--fast`로 node 스모크 스킵 옵션은 두지 않음(스모크가 핵심 회귀
  포착 지점).

#### `eval` — 판정 골든 회귀
**대상(고신호만)**: 순수 판정 매퍼의 `{text, tone}` 출력.
- `backend/flow/credit.py`(신용), `shortbal.py`(대차), `exvol.py`(시간외),
  `models.py`(수급 추정·시장상태) 의 판정 함수들.
- 이들은 입력 상태 dict → `{text, tone}` **순수 함수**라 서버·node 불필요.

**시나리오**: `harness/scenarios/*.json` — 각 파일은 `{module, func, cases:[{name,
input}...]}` 형태이고, 기대 출력은 `golden/<module>.<func>.json`에 별도 보관한다.
경계·부호 교차 케이스를 포함(예: 하락+신용증가, 상승+숏이탈, 표본 극소). 초기 시드는
`backend/flow/demo.py`가 만드는 상태 + 각 판정 함수의 분기 경계에서 뽑는다.

**실행**: 각 case의 `func(input)`을 호출해 `{text, tone}`를 얻고
`scenarios/golden/<module>.<func>.json`과 비교. 불일치 시 diff 출력 + exit 1.
`--update`로 골든 재생성(의도된 문구/톤 변경 시).

**노드 경로(2차, 선택)**: `#today-line`·타이밍 알약은 JS render()가 만들므로,
`test_live_page_js.py`의 node 하네스를 재사용해 특정 시드 스냅샷으로 render() 실행 후
해당 엘리먼트 textContent를 골든과 비교. 1차(파이썬 판정)가 백본, node 경로는 있으면
추가.

**가치**: node 스모크는 "render가 죽었나"를 잡고, eval은 "**판정 의미가 조용히
드리프트**했나"(톤이 warn↔good 뒤집힘 등)를 잡는다. 전체 렌더 문자열을 golden하지
않음(유지비 과다) — 판정 필드만.

#### `ops` — 운영 점검(읽기전용 기본)
- 기본 동작은 **읽기전용 상태 리포트**:
  - 로컬 실서버: `lsof -nP -iTCP:8000 -sTCP:LISTEN`로 PID 존재 확인 + `/healthz`.
  - Funnel 공개 URL(`YOUR-MAC.YOUR-TAILNET.ts.net`): 200 + 인증 게이트
    (미인증 302) 확인.
  - KIS 세션: 실서버가 살아있으면 라이브 데이터 응답(예 `/api/asking/000660`
    200)로 세션 건강 확인(REST만, WS 미접촉).
- **재기동은 별도 서브플래그**(`ops restart`)이며 마스터 확인 문구를 출력하고,
  대상 PID가 **8000 리스너 자신인지 양성 확인** 후에만, graceful SIGTERM→대기→
  `.venv` 서브셸 재기동. 기본 `ops`는 절대 재기동 안 함.

### 3.4 CI (`.github/workflows/test.yml`)
- 트리거: push / pull_request.
- 잡: py3.9 셋업 → `pip install -e '.[dev]'` → `python -m harness test` +
  `python -m harness eval`.
- **KIS 시크릿 불필요**(전부 demo). node는 `actions/setup-node`로 깔아 스모크까지.
- **verify는 CI에서 제외**(헤드리스 크롬 무거움) — 로컬 `make verify` 전용.

## 4. 하네스 자체의 테스트

- `core/ports.py`: 빈 포트 반환·재바인드 가능 단위 테스트.
- `core/server.py`: `demo_server()`가 healthz 뜰 때까지 대기하고 컨텍스트 종료 시
  PID가 죽는지(그리고 8000을 안 건드리는지) 테스트. **8000 보호 회귀 테스트**:
  종료 로직이 `pkill`류 문자열 매칭을 쓰지 않음을 구조적으로 보장(코드에 pkill 부재
  단정 + terminate가 self.proc에만 작동).
- `cmd/eval.py`: 샘플 시나리오 1개로 통과/실패 경로 테스트.
- 이 테스트들은 `tests/test_harness_*.py`로 두어 `harness test`에 포함.

## 5. 산출물(Deliverables)
1. `harness/` 패키지(코어 3 + 커맨드 4).
2. `harness/scenarios/` 초기 시드 + 골든.
3. `Makefile`(verify/test/eval/ops/ci 별칭).
4. `.github/workflows/test.yml`.
5. `harness/README.md` 사용법.
6. `.gitignore`에 `harness/artifacts/`.
7. `tests/test_harness_*.py`.
8. `.claude/skills/verify` 갱신(휘발성 scratchpad 대신 `python -m harness verify`
   가리키게).

## 6. 비목표(Non-goals)
- LLM 심판형 eval(결정론 골든으로 충분, 규칙 엔진이므로).
- verify를 CI에 넣기(로컬 전용).
- 실서버 자동 배포·자동 재기동(ops는 점검 기본, 재기동은 수동 확인 게이트).
- 전체 렌더 HTML 스냅샷 golden(유지비 과다 — 판정 필드만).

## 7. 단계(구현 순서, 한 플랜 내)
1. 공유 코어(ports·server·bake·cdp) + 8000 보호 테스트.
2. `verify`(scratchpad 로직 승격) — 즉시 가치.
3. `test` 래퍼.
4. `eval`(시나리오·골든 신규 설계) — 가장 큰 신규 작업.
5. `ops` 읽기전용 점검.
6. CI 워크플로 + Makefile + README + verify 스킬 갱신.
