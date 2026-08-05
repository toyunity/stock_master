# S5 실시간 수급 모니터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) — 이 세션에서 작성자=실행자. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `/live/000660` 페이지에서 SK하이닉스의 실시간 수급(체결·프로그램매매·외인/기관 잠정·일별 확정)을 SSE로 관측 — KIS 키 있으면 LIVE, 없으면 DEMO.

**Architecture:** `backend/flow/` 모듈(순수 파서 + FlowState + FlowEngine) → FastAPI SSE(1초 전체 스냅샷) → 자기완결 HTML(EventSource + Lightweight Charts). 스펙: `docs/superpowers/specs/2026-07-10-realtime-susub-monitor-design.md`.

**Tech Stack:** Python 3.9 (`from __future__ import annotations`, PEP604 런타임 금지), httpx(설치됨, REST), websockets 15(설치됨, WS), FastAPI SSE(StreamingResponse), Lightweight Charts(로컬 파일).

## Global Constraints

- 새 pip 의존성 금지 (httpx·websockets·fastapi 기설치분만).
- pytest-asyncio 없음 → async 테스트는 `asyncio.get_event_loop().run_until_complete` 또는 TestClient 스트리밍으로.
- 네이버 계열 호출 금지. KIS 실전 도메인만: REST `https://openapi.koreainvestment.com:9443`, WS `ws://ops.koreainvestment.com:21000`.
- 화면 문구: 모드 배지(LIVE/DEMO), 신선도 라벨(실시간/잠정 hh:mm/전일 확정), §16 투자 유의 고지.
- 설정 env: `SM_KIS_APP_KEY`, `SM_KIS_APP_SECRET`, `SM_FLOW_MODE`(''|'demo').

## 검증된 KIS 와이어 포맷 (구현·픽스처의 유일한 근거)

- WS 프레임: `0|TRID|N|f1^f2^...` (N레코드 필드 연접, 평문). JSON 프레임(구독ACK/PINGPONG)은 `{`로 시작. PINGPONG은 원문 그대로 에코.
- `H0STCNT0` 46필드/레코드. 사용 인덱스: [0]=code, [1]=HHMMSS, [2]=현재가, [3]=전일대비부호(1/2 상승, 4/5 하락), [5]=전일대비율, [12]=체결량, [13]=누적거래량, [14]=누적거래대금, [18]=체결강도, [21]=CCLD_DVSN(1 매수·5 매도).
- `H0STPGM0` 11필드/레코드: [0]=code, [1]=HHMMSS, [2]=매도체결량, [3]=매도대금, [4]=매수체결량, [5]=매수대금, [6]=순매수체결량, [7]=순매수대금, [8]=매도호가잔량, [9]=매수호가잔량, [10]=전체순매수호가잔량.
- 구독: `{"header":{"approval_key":K,"custtype":"P","tr_type":"1"|"0","content-type":"utf-8"},"body":{"input":{"tr_id":T,"tr_key":C}}}`.
  - **정정(2026-08-06)**: 해지는 `"0"`이 아니라 **`"2"`**다(`1:등록 2:해지`). 여기 적힌 `"0"`이
    그대로 코드에 들어갔고, 등록만 쓰는 동안 약 한 달을 무증상으로 지나가다 wsbus가 해지를
    실제로 보내기 시작하자 `OPSP8997 invalid tr_type`으로 터졌다. 이 문서를 참조해 프레임을 다시 짜는
    사람이 같은 값을 옮기지 않도록 원문은 남기고 정정만 붙인다. 상세: index-futures 스펙 §출하.
- REST 공통 헤더: authorization Bearer, appkey, appsecret, tr_id, custtype=P.
  - `FHKST01010900` GET `/uapi/domestic-stock/v1/quotations/inquire-investor` params `FID_COND_MRKT_DIV_CODE=J, FID_INPUT_ISCD=code` → `output[]`: stck_bsop_date, prsn_ntby_qty, frgn_ntby_qty, orgn_ntby_qty (+ stck_clpr).
  - `HHPTJ04160200` GET `/uapi/domestic-stock/v1/quotations/investor-trend-estimate` params `MKSC_SHRN_ISCD=code` → `output2[]`: bsop_hour_gb, frgn_fake_ntby_qty, orgn_fake_ntby_qty, sum_fake_ntby_qty. bsop_hour_gb 매핑: 1→09:30, 2→10:00, 3→11:20, 4→13:20, 5→14:30 (마지막 행이 최신).
  - `FHPPG04650101` GET `/uapi/domestic-stock/v1/quotations/program-trade-by-stock` params `FID_COND_MRKT_DIV_CODE=J, FID_INPUT_ISCD=code` → `output[]` 시간대별: bsop_hour(HHMMSS), whol_smtn_ntby_tr_pbmn(누적 순매수 대금) — 백필용.
- 토큰: POST `/oauth2/tokenP` body `{grant_type:client_credentials, appkey, appsecret}` → access_token(24h, 1회/분) — `data/cache/kis_token.json` 캐시 필수. approval: POST `/oauth2/Approval` body `{grant_type, appkey, secretkey}`(필드명 secretkey!).

---

### Task 1: 순수 파서 (backend/flow/kis.py 전반부)

**Files:** Create `backend/flow/__init__.py`, `backend/flow/kis.py`; Test `tests/test_flow_parse.py`.

**Produces:**
- `split_frames(raw: str) -> Optional[tuple]` — `('json', dict)` | `('data', (tr_id, [record: list[str]]))` | `None`
- `parse_ccnl(rec: list) -> dict` — {t:'HH:MM:SS', price:int, sign:str, rate:float, vol:int, acml_vol:int, acml_value:int, strength:float, side:'buy'|'sell'|''}
- `parse_program(rec: list) -> dict` — {t, sell_qty, sell_value, buy_qty, buy_value, net_qty, net_value}
- `build_subscribe(key, tr_id, code, on=True) -> str`
- `is_pingpong(raw) -> bool`

- [ ] 실패 테스트: 46필드 1레코드/2레코드 연접, 11필드 프로그램, JSON ACK, PINGPONG, 구독 메시지 라운드트립 (픽스처는 위 필드 순서로 직접 제작)
- [ ] 최소 구현 → 통과 → 커밋 `feat(s5): KIS 웹소켓 프레임 파서`

### Task 2: FlowState (backend/flow/models.py)

**Files:** Create `backend/flow/models.py`; Test `tests/test_flow_models.py`.

**Produces:** `FlowState(code, name, mode)` — `.apply_tick(d)`, `.apply_program(d)`(누적 및 points append), `.set_estimate(list)`, `.set_daily(list)`, `.set_status(**kw)`, `.snapshot() -> dict` (keys: code,name,mode,ts,market{price,sign,rate,vol,value,strength,time},tape[≤30],program{net_qty,net_value,points[≤200]},estimate{asof,rows|null},daily[≤10],status{connected,note}).

- [ ] 실패 테스트: snapshot 스키마·테이프 30개 상한(최신순)·프로그램 points 누적·JSON 직렬화 가능
- [ ] 구현 → 통과 → 커밋 `feat(s5): FlowState 스냅샷 모델`

### Task 3: KIS REST 파서 + 클라이언트 (kis.py 후반부)

**Files:** Modify `backend/flow/kis.py`; Test `tests/test_flow_kis_rest.py`; Modify `backend/config.py` (kis_app_key/kis_app_secret/flow_mode 추가).

**Produces:**
- 순수: `parse_daily_investor(js) -> list[{date,prsn,frgn,orgn,close}]`, `parse_estimate(js) -> list[{asof,frgn,orgn,sum}]`, `parse_program_trend(js) -> list[{t,net_value}]`
- `KisClient(appkey, appsecret, cache_dir)`: async `token()`(디스크 캐시·만료 60s 여유), `approval_key()`, `daily_investor(code)`, `estimate(code)`, `program_trend(code)` — httpx.AsyncClient, 실패 시 예외를 호출부가 처리.

- [ ] 실패 테스트: 3개 파서(문서 필드명 그대로의 목 JSON), 토큰 캐시 재사용(파일 기반, 네트워크 목킹 없이 캐시 히트 경로만)
- [ ] 구현 → 통과 → 커밋 `feat(s5): KIS REST 수급 클라이언트`

### Task 4: DemoSource + FlowEngine (demo.py, engine.py)

**Files:** Create `backend/flow/demo.py`, `backend/flow/engine.py`; Test `tests/test_flow_engine.py`.

**Produces:**
- `DemoSource(state).run(stop: asyncio.Event)` — 시드 랜덤워크(기준가: universe 캐시 price_map→fallback 100_000), 틱 0.2~0.8s, 프로그램 ~2s, 추정 스냅샷 즉시 1회+주기, 일별 10행 합성. 데모 라벨은 state.mode='demo'가 담당.
- `FlowEngine.get(code) -> FlowEngine`(레지스트리); `.mode`('live' iff settings.kis_app_key&&secret and flow_mode!='demo'); `.subscribe() -> AsyncIterator[dict]` — 첫 yield 즉시, 이후 1s 간격; 첫 구독자에서 소스 태스크 lazy 시작, 구독자 0이면 정지. live면 `_run_live`(WS 수신 + REST 폴링 + 백필, 재접속 지수 백오프), demo면 DemoSource.

- [ ] 실패 테스트: 키 없으면 mode=='demo'; `subscribe()` 첫 스냅샷을 2초 내 수신하고 필수 키 존재(run_until_complete + wait_for); 두 번째 스냅샷의 ts가 진행
- [ ] 구현 → 통과 → 커밋 `feat(s5): FlowEngine + 데모 소스`

### Task 5: SSE 라우트 + 라이브 페이지 (app.py, live_page.py)

**Files:** Create `backend/report/live_page.py`; Modify `backend/api/app.py`; Test `tests/test_live_api.py`; Modify `backend/report/dashboard.py`(카드 종목명 → `/live/{code}` 링크 + 관심종목 상단에 워치 링크).

**Produces:**
- `render_live_page(code, name, mode) -> str` — 자기완결 HTML(dashboard.py 패턴): 헤더/모드 배지/잠정 패널/프로그램 차트(Lightweight Charts area)/일별 표/체결 테이프/고지, `new EventSource('/api/live/'+code+'/stream')`, 필드는 snapshot 스키마(Task 2)와 1:1.
- `GET /live/{code}`: 6자리 검증(아니면 404), display_name/universe에서 이름.
- `GET /api/live/{code}/stream`: `StreamingResponse(gen, media_type='text/event-stream')`, 각 스냅샷 `data: <json>\n\n`.

- [ ] 실패 테스트: `/live/000660` 200·HTML에 'EventSource'·'000660'·'DEMO' 배지·고지문; `/live/12ab` 404; `client.stream`으로 `/api/live/000660/stream` 첫 `data:` 라인이 JSON 파싱되고 code=='000660'
- [ ] 구현 → 통과 → 커밋 `feat(s5): /live 수급 화면 + SSE 스트림`

### Task 6: E2E 검증 + 문서

**Files:** Modify `docs/implementation-status.md`.

- [ ] `pytest` 전체 green
- [ ] `python -m backend.cli serve` 기동 → `curl /live/000660` + `curl -N .../stream` 3초 관측(장중 데모 스트림 실동작 확인) → 종료
- [ ] implementation-status.md에 S5 섹션(모드·키 발급 절차·LIVE 검증 체크리스트) 추가 → 커밋 `docs(s5): 구현 현황 갱신`

## Self-Review

- 스펙 §4 아키텍처/§5 화면/§6 에러/§7 테스트 → Task 1–6에 매핑 완료. 커버리지 갭 없음.
- LIVE 경로(WS·REST 폴러)는 픽스처 단위테스트로만 검증되고 실연결은 키 입력 후 체크리스트(Task 6 문서)로 이월 — 스펙 §7과 일치.
- 타입/명칭 일관성: snapshot 스키마(Task 2) ↔ 페이지 JS(Task 5) ↔ SSE(Task 5) 동일 키 사용 확인.
