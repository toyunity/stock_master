# KIS 미사용 기능 13종 반영 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/kis-unused-features-2026-09.md` Top 13을 전부 붙인다. 단 #10(스캐너 탭 4개)은 마스터 지시로 **종목 상세의 "시장 속 위치" 패널**로 바꾼다. 미국 실시간 웹소켓은 제외(마스터 결정 2026-09-08).

**Architecture:** 엔진·SSE 경로(매일 도는 핵심)는 건드리지 않는다. 종목 상세의 새 데이터는 전부 `/api/stockinfo/{code}`(5분 폴링) 하나로, 홈은 `/api/market-flow`(60초) 하나로 받는다. 각 API는 모듈 내부 TTL 캐시로 원격 호출을 제한하고, 원천 하나가 죽어도 나머지 키는 살아서 내려간다(격리). 키 없음/데모면 결정적 합성 데이터를 내려 `make verify` 캡처에 패널이 보이게 한다. 차트 일·주·월봉은 KIS 기간별시세로 바꾸되 FDR을 폴백으로 남긴다.

**Tech Stack:** Python 3.9(FastAPI, httpx) · 자기완결 HTML/JS(lightweight-charts 동봉) · pytest + node 렌더 스모크 · 하네스(`make test/verify/eval`).

**Spec:** `docs/kis-unused-features-2026-09.md` §1 Top 13 + §2~§6 항목별 설명. 실응답 픽스처: `tests/fixtures/kis/*.json`(2026-09-08 프로브, 행 6개 축약).

## Global Constraints

- Python 3.9 문법만(`Optional[X]`, `match` 금지), 모듈 맨 위 `from __future__ import annotations`.
- 실서버 8000 불가침. 검증은 `.venv/bin/python`·`make test/verify/eval`. 실 KIS 호출은 프로브(완료)와 마지막 라이브 확인만.
- 색은 `backend/report/theme.py` 토큰만. 페이지 파일엔 레이아웃 CSS만.
- `/live` 패널 DOM 제거·숨김 금지(렌더가 `getElementById().textContent`로 돈다). 새 패널은 **추가만**.
- 새 의존성 0. 새 추상화 0(모듈 함수 + dict).
- 실측 사실은 날짜와 함께 주석에 남긴다.
- 파서는 픽스처로 먼저 빨간 테스트 → 최소 구현.

---

## 실응답에서 확정한 사실(2026-09-08 프로브, 파서가 기대는 근거)

| 모듈 | TR | 본문 | 핵심 필드·단위 |
|---|---|---|---|
| 예탁원 배당 | HHKDB669102C0 `/ksdinfo/dividend` | output1 list | record_date YYYYMMDD, per_sto_divi_amt 원, divi_rate %(액면가 기준), divi_pay_dt "YYYY/MM/DD", divi_kind 결산/분기, SHT_CD 지정 시 그 종목만 |
| 유상증자 | HHKDB669100C0 `/ksdinfo/paidin-capin` | output1 | right_dt(권리락) YYYYMMDD, fix_rate 배정률%, disc_rate, fix_price, sub_term "YYYY/MM/DD ~ YYYY/MM/DD" |
| 무상증자 | HHKDB669101C0 `/ksdinfo/bonus-issue` | output1 | right_dt, fix_rate |
| 주총 | HHKDB669111C0 `/ksdinfo/sharehld-meet` | output1 | gen_meet_dt "YYYY/MM/DD", gen_meet_type, agenda |
| 액면변경 | HHKDB669105C0 `/ksdinfo/rev-split` | output1 | inter_bf/af_face_amt 0패딩 9자리, td_stop_dt "YYYY/MM/DD ~" |
| 합병분할 | HHKDB669104C0 `/ksdinfo/merger-split` | output1 (9~12월 0건) | 필드는 문서대로(td_stop_dt 등) |
| 매수청구 | HHKDB669103C0 `/ksdinfo/purreq` | output1 | buy_req_price 0패딩 12자리, buy_req_rcpt_term "0YYYYMMDD"(앞 0 하나) |
| 투자의견 | FHKST663300C0 `/quotations/invest-opinion` | output list(최신순) | invt_opnn 'BUY' 또는 '매수'(증권사마다 다름), hts_goal_prc 원, dprt 괴리율%(전일종가 기준), mbcr_name |
| 시장 투자자 일별 | FHPTJ04040000 `/quotations/inquire-investor-daily-by-market` | output list 300행 최신순 | **DATE_1=끝(최신), DATE_2=시작**. *_ntby_tr_pbmn **백만원**, *_ntby_qty 천주. 마감 후 당일 행 포함 |
| 증시자금 | FHKST649100C0 `/quotations/mktfunds` | output list 100행 최신순 | cust_dpmn_amt·crdt_loan_rmnd·uncl_amt·mmf_amt **억원**, bsop_date |
| 업종별 시세 | FHPUP02140000 `/quotations/inquire-index-category-price` | output1 dict + output2 list | KOSPI(0001,K): output1 ascn/down/stnr_issu_cnt, output2 38행 업종. **KOSDAQ(1001,Q)는 output1(폭)만 쓴다** — output2는 선물 ETF 쓰레기 |
| 매물대 | FHPST01130000 `/quotations/pbar-tratio` | output1 dict + output2 100행 | output2 stck_prpr 가격대, cntg_vol, acml_vol_rlim %, output1 wghn_avrg_stck_prc |
| 시간외 단일가 | FHPST02300000 `/quotations/inquire-overtime-price` | output dict | ovtm_untp_prpr/vol/prdy_ctrt, ovtm_untp_antc_cnpr(예상). **대형주(005930·000660)는 vol 0**(애프터마켓이 NXT로 감) — 소형주(032820)만 값 있음 |
| 프로그램 일별 | FHPPG04650201 `/quotations/program-trade-by-stock-daily` | output list 30행 최신순 | whol_smtn_ntby_qty 주, whol_smtn_ntby_tr_pbmn 원, stck_clpr |
| 일별 매수/매도 체결량 | FHKST03010800 `/quotations/inquire-daily-trade-volume` | output2 list 최신순 | total_shnu_qty(매수) total_seln_qty(매도) |
| 체결금액별 비중 | FHKST111900C0 `/quotations/tradprt-byamt` | output list 8행 | prpr_name '3백 이하'…'5억 초과', shnu/seln_cnqn_smtn 거래량, *_cntg_csnu 건수, whol_ntby_qty_rate 순매수비율 |
| 공매도 상위 | FHPST04820000 `/ranking/short-sale` | output 30행 | mksc_shrn_iscd, ssts_vol_rlim, stnd_date1 |
| 신용잔고 상위 | FHKST17010000 `/ranking/credit-balance` | output2 100행 | mksc_shrn_iscd, whol_loan_rmnd_rate |
| 예상 지수 | FHKUP11750000 `/quotations/exp-total-index` | output2 list | bstp_cls_code '0001' 행의 bstp_nmix_prdy_ctrt. 동시호가 밖에선 값이 신뢰 불가 → **08:30~09:00만** |
| 기간별시세 | FHKST03010100 `/quotations/inquire-daily-itemchartprice` | output2 100행 최신순 | stck_bsop_date, stck_oprc/hgpr/lwpr/clpr, acml_vol. PERIOD D/W/M. 당일 봉 포함(날짜 정확) |
| 해외 분봉 | HHDFS76950200 `/overseas-price/v1/quotations/inquire-time-itemchartprice` | output2 120행 최신순 | kymd+khms(KST), open/high/low/last 소수 4자리, evol |
| 해외 체결추이 | HHDFS76200300 `/overseas-price/v1/quotations/inquire-ccnl` | output2 100행 최신순 | khms(KST), last, evol, vpow(체결강도) |
| K200 현물 | FHPUP02100000 iscd 2001 | output dict | bstp_nmix_prpr — 베이시스 = 선물 − 이것 |

버린 것: 장중 시장 투자자(FHPTJ04030000)는 파라미터 조합에 따라 빈 응답/의미 불명 → 일별 TR의 당일 행으로 대체. 선물 기초자산(FHPIF05030000)은 빈 응답 → K200 지수로 대체.

---

## 파일 구조

- Create `backend/flow/ksdinfo.py` — 예탁원 7종 파서·조회(24h 캐시). `parse_events(kind, js) -> list`, `async get_events(client, code) -> dict`.
- Create `backend/flow/stockinfo.py` — 종목 상세 부가 데이터 6종 파서 + 조립 + 데모. `parse_opinions/summarize_opinions`, `parse_profile`, `parse_overtime`, `parse_pgm_daily`, `parse_trade_volume`, `parse_trade_by_amount`, `async get_stockinfo(code, client=None) -> dict`, `demo_stockinfo(code) -> dict`.
- Create `backend/flow/rankpos.py` — 공매도·신용 상위 시장 전체 캐시(1h) + 종목 위치. `parse_short_rank`, `parse_credit_rank`, `async get_position(client, code) -> dict`.
- Create `backend/flow/marketflow.py` — 홈 시장 수급·자금·폭·업종·예상·베이시스. `parse_investor_daily`, `streak`, `parse_funds`, `parse_breadth`, `parse_sectors`, `parse_expected`, `async get_market_flow(client=None, now=None) -> dict`, `demo_market_flow() -> dict`.
- Modify `backend/flow/kis.py` — `parse_period_candles(js)`, `KisClient.period_candles()`, `parse_us_minutes(js)`, `KisClient.us_minutes()`, `parse_us_ccnl(js)`, `KisClient.us_ccnl()`.
- Modify `backend/flow/candles.py` — `_kis_bars()`; `_daily_candles`/`_wm_candles`가 live면 KIS, 아니면 FDR; `_us_minutes()`; `get_candles` US 분봉 분기.
- Modify `backend/flow/usquote.py` — `async ccnl(client, sym)` 30초 캐시(거래소 순회 재사용).
- Modify `backend/api/app.py` — `/api/stockinfo/{code}`, `/api/market-flow`, `/api/usccnl/{sym}`, `/api/candles` US 분봉 허용.
- Modify `backend/report/live_page.py` — 일정 칩·목표가·매물대·시간외 알약·프로그램 20일·체결강도 20일·KIS 체결금액 비중·시장 속 위치 + `loadInfo()/renderInfo()`.
- Modify `backend/report/dashboard.py` — "시장 수급·자금" 섹션 + `loadFlow()/renderFlow()`.
- Modify `backend/report/us_page.py` — 분봉 탭 3개 + 체결강도 패널 + 문구 정정.
- Tests: `tests/test_ksdinfo.py`, `tests/test_stockinfo.py`, `tests/test_rankpos.py`, `tests/test_marketflow.py`, `tests/test_candles.py`(추가), `tests/test_usquote.py`(추가), `tests/test_live_api.py`(라우트), `tests/test_live_page_js.py`(renderInfo), `tests/test_dashboard.py`, `tests/test_us_page.py`. 픽스처 `tests/fixtures/kis/`.
- Docs: `README.md` 화면 목록, `docs/kis-unused-features-2026-09.md` 상단 "반영 현황" 표.

공통 헬퍼: `backend.flow.kis._f/_i`(문자열→수, 콤마·공백 허용). 픽스처 로더는 각 테스트 파일에 `def _fx(name): return json.load(open(Path(__file__).parent/'fixtures'/'kis'/f'{name}.json'))`.

---

### Task 1: 예탁원 일정 파서·조회 (`ksdinfo.py`)

**Files:** Create `backend/flow/ksdinfo.py`, `tests/test_ksdinfo.py`. 픽스처 `ksdinfo_dividend/paidin_capin/bonus_issue/sharehld_meet/rev_split/purreq.json`.

**Produces:** `parse_events(kind: str, js: dict) -> list[dict]`; 각 행 `{"date": "YYYY-MM-DD", "kind": kind, "label": str, "detail": str, "code": str}`. `KINDS = [("dividend","배당",TR,path,params_fn),...]`. `async get_events(client, code: str, today=None) -> {"rows": [...], "asof": "YYYY-MM-DD"}` — rows는 today-45일~today+120일, 날짜 오름차순, 24h 메모리 캐시(code별).

- [ ] 실패 테스트: 배당 픽스처 → 첫 행 `date=="2026-08-31"`, `label=="배당 기준일"`, `detail`에 "375원"과 "지급 2026-09-30" 포함; 유상증자 → `date`=right_dt(권리락) 변환, detail에 배정률·청약기간; 액면 → detail "500원→2,500원 · 거래정지 2026-10-02~"; 매수청구 → detail 가격 20,891원(0패딩 제거), `date`=buy_req_rcpt_term의 앞 0 제거; 주총 → date "2026-12-07".
- [ ] `_d8("20260831")->"2026-08-31"`, `_dslash("2026/09/30")->"2026-09-30"`, 빈 값→None. 종류별 매핑 함수 6개(합병분할은 액면과 같은 td_stop_dt 규칙). rt_cd≠"0"이면 []. 
- [ ] `get_events`: 7 TR 순차 호출(각 try/except 격리, 하나 실패해도 나머지 반환), 파라미터 `{"CTS":"","F_DT":f,"T_DT":t,"SHT_CD":code}` (+배당 `"GB1":"0","HIGH_GB":""`, 유상 `"GB1":"1"`, 액면 `"MARKET_GB":"0"`). 캐시 dict `_cache[code]=(ts,data)`, TTL 86400.
- [ ] 테스트 통과 확인 후 커밋 `feat(kis): 예탁원 일정 7종 파서`.

### Task 2: 종목 상세 부가 파서 6종 + 조립 (`stockinfo.py`)

**Files:** Create `backend/flow/stockinfo.py`, `tests/test_stockinfo.py`.

**Produces:**
- `parse_opinions(js) -> [{"date","broker","opinion","prev","target","close"}]` 최신순. opinion 정규화: 'BUY'/'매수'/'Buy'→'매수', 'HOLD'/'중립'/'Neutral'→'중립', 'SELL'/'매도'/'Reduce'→'매도', 그 외 원문.
- `summarize_opinions(rows, price) -> {"n","avg_target","max_target","min_target","gap_pct","buy","hold","sell","latest","changes":[...3개]}` — 증권사별 **최신 1건**만 집계(같은 증권사 중복 제거), gap_pct=(price/avg-1)*100, changes=prev≠opinion인 행.
- `parse_profile(js) -> {"wavg","price","levels":[{"price","vol","pct"}](pct 내림차순 상위 8 → 가격 내림차순 정렬),"top":{"price","pct"}}`.
- `parse_overtime(js) -> {"price","change","rate","vol","value","expected","expected_rate"}`; vol 0이면 `{"vol":0}`만(화면은 숨김).
- `parse_pgm_daily(js) -> [{"date","net_qty","net_value","close"}]` 오름차순.
- `parse_trade_volume(js) -> [{"date","buy","sell","strength"}]` 오름차순, strength=buy/sell*100(sell 0이면 None).
- `parse_trade_by_amount(js) -> [{"band","avg","vol","buy_vol","sell_vol","buy_cnt","sell_cnt","net_rate"}]` 응답 순서 유지.
- `async get_stockinfo(code, client=None, now=None) -> dict` 키: `events, opinion, pbar, overtime, pgm_daily, tradevol, tradeamt, rankpos, asof`. 각 원천 try/except → 실패 키는 None. TTL: events·opinion·rankpos 24h(자기 모듈), pgm_daily·tradevol 3600, pbar·overtime·tradeamt 300. `client None`이면 `demo_stockinfo(code)`.
- `demo_stockinfo(code)` — `random.Random(code)` 시드로 결정적 합성(일정 3건, 의견 5건, 매물대 8단, 시간외 vol>0, 30일 프로그램, 26일 체결량, 8구간).

- [ ] 실패 테스트(픽스처): 의견 첫 행 broker 'DB증권' target 2300000 opinion '매수'; summarize(rows, 1793000) n==증권사 수, avg_target 계산값, gap_pct<0; 매물대 top price 1793000 pct 5.81; 시간외(032820) rate 1.19 vol 35757, zero 픽스처 → vol 0; 프로그램 오름차순 마지막 date 2026-09-08 net_qty 126584; 체결량 strength ≈107.3; 금액구간 첫 band '3백 이하' buy_cnt 55150.
- [ ] 구현, 통과, 커밋 `feat(kis): 종목 상세 부가 데이터 6종 파서·조립`.

### Task 3: 시장 속 위치 (`rankpos.py`)

- `parse_short_rank(js) -> [{"code","name","ratio"}]` (output, ssts_vol_rlim), `parse_credit_rank(js) -> [{"code","name","rate"}]` (output2, whol_loan_rmnd_rate).
- `async get_position(client, code) -> {"short":{"rank","n","ratio"}|None, "credit":{"rank","n","rate"}|None, "asof"}` — 시장 전체 목록 2콜 1h 캐시(전 종목 공유), rank는 1-based, 목록 밖이면 None이되 n은 채운다(`{"rank":None,"n":30}`).
- [ ] 테스트: 픽스처 short_sale_rank에서 '034220' rank 2 ratio 19.46; credit rank '251340' rank 2; 없는 코드 → rank None n 6.
- [ ] 커밋 `feat(kis): 공매도·신용 상위 속 종목 위치`.

### Task 4: `/api/stockinfo/{code}` 라우트

- `app.py`: `@app.get("/api/stockinfo/{code}")` — 6자리 검증(`_CODE_RE`), `stockinfo.get_stockinfo(code, marketdata._client())`. 
- [ ] 테스트(test_live_api): 키 없음 → 200 + JSON에 `events`·`opinion`·`pbar` 키, `pbar.levels` 길이>0(데모); 잘못된 코드 404.
- [ ] 커밋.

### Task 5: 종목 상세 화면(live_page.py) — 패널 8개 + renderInfo

HTML(추가만):
1. `#note` 뒤: `<div class="evrow" id="ev-chips" style="display:none"></div>` — 칩 `<span class="evchip">D-12 · 배당 기준일 9/30</span>`.
2. `#finsec` 뒤: `<details class="sec" id="opsec" style="display:none"><summary>🎯 증권사 목표가 <span class="findig" id="op-digest"></span></summary><div class="sec-body" id="op-body"></div></details>`.
3. 거래량 차트(`.volwrap`) 뒤: `<div class="panel dp" id="pb-panel"><div class="dp-h"><h2>매물대</h2><span class="pill fixed" id="pb-pill">🕐 데이터 대기</span></div><div id="pb-bars"></div><div class="meta" id="pb-note"></div></div>`.
4. `.hstate` 안 `#wpill` 뒤: `<span id="otpill"></span>` (시간외).
5. 프로그램매매 패널 meta 뒤: `<div class="dp-foot"><span class="sparkwrap"><span class="sk-cap">프로그램 30일</span><span class="sk-svg" id="pgd-spark"></span></span><span class="meta" id="pgd-note"></span></div>`.
6. 체결 규모 분포 패널 안 `#sz-sig` 뒤: `<div class="meta">KIS 집계(확정) — 체결금액 구간별 매수/매도</div><div id="ta-bars"></div><div class="dp-foot"><span class="sparkwrap"><span class="sk-cap">일별 체결강도 20일</span><span class="sk-svg" id="tv-spark"></span></span><span class="meta" id="tv-note"></span></div>`.
7. 위험 지표 섹션 맨 앞 패널: `<div class="panel dp" id="rp-panel"><div class="dp-h"><h2>시장 속 위치</h2><span class="pill fixed" id="rp-pill">🕐 데이터 대기</span></div><table id="rp-tbl"></table><div class="meta">공매도 상위 30·신용잔고 상위 100 안에 있으면 순위, 52주 고가 대비, 시간외 등락.</div></div>`.

CSS(레이아웃만, live_page 인라인): `.evrow{display:flex;flex-wrap:wrap;gap:6px;margin:6px 12px}` `.evchip{font-size:11px;padding:3px 8px;border-radius:999px;background:var(--surface-2);border:1px solid var(--border-2)}` `.evchip.soon{background:var(--warn-bg);color:var(--warn)}`.

JS: `let INFO=null; async function loadInfo(){ const r=await fetch('/api/stockinfo/'+CODE); if(!r.ok)return; INFO=await r.json(); renderInfo(INFO); } loadInfo(); setInterval(loadInfo,300000);` 
`function renderInfo(d)`: 각 블록 독립 try/catch. 
- 일정: rows 중 date≥오늘 앞 5개 → D-n 칩(≤7일 `.soon`), 없으면 숨김.
- 목표가: op.n==0 → 숨김. digest "목표가 평균 n원 · 현재가 대비 -18%"; body: 의견 분포 + 최근 변경(증권사·prev→opinion·목표가) + "목표가는 예언이 아니라…" 한 줄.
- 매물대: `.szrow` 재사용, 바 폭 = pct/최대pct*100%; 현재가 ±0.5% 밴드에 `szbuy` 색, 나머지 `szsell`? → 색은 의미: 현재가 위 매물대는 저항(하락색 `szsell`), 아래는 지지(상승색 `szbuy`). note "가장 두꺼운 가격 n원 (현재가 대비 +x%) — 저항/지지 후보".
- 시간외: `vol>0`이면 `#otpill.textContent='시간외 '+부호+rate+'% · '+num(vol)+'주'`, class `badge b-live`/`b-off`; 아니면 ''.
- 프로그램 30일: spark(net_qty), note "n일 연속 순매수/순매도".
- 체결강도 20일: spark(strength), note "최근 5일 중 사자 우위 n일".
- KIS 집계: 8행 `.szrow` — band, 순매수비율 부호 색.
- 시장 속 위치: 4행 테이블 — 공매도 비중 rank/30 · ratio%, 신용잔고 비율 rank/100 · rate%, 52주 위치(`window.__W52` — loadFin이 v.w52_pos를 저장) "n% · 신고가 근접" (≥95), 시간외 등락(overtime.rate).

- [ ] 테스트 `test_live_page_js.py`: 하니스에 `if(typeof renderInfo==='function'){renderInfo(JSON.parse(fs.readFileSync(process.argv[5])))}` 추가(argv[5]=INFO 픽스처 = `stockinfo.demo_stockinfo('000660')` 덤프), TXT로 `ev-chips`·`op-digest`·`pb-note`·`otpill`·`pgd-note`·`tv-note`·`rp-tbl`(innerHTML) 출력; 단언: 'D-' in ev-chips, '목표가' in op-digest, '원' in pb-note, '시간외' in otpill, '연속' in pgd-note, 'rp-tbl'에 '공매도'.
- [ ] `make verify` 통과(가로 오버플로 0). 커밋 `feat(live): 일정·목표가·매물대·시간외·일별 추이·KIS 체결비중·시장 속 위치`.

### Task 6: 홈 시장 수급·자금 (`marketflow.py` + `/api/market-flow` + dashboard)

- `parse_investor_daily(js) -> [{"date","frgn","prsn","orgn","close"}]` 오름차순, 금액 **억원**(백만원/100). `streak(rows,key) -> int` 마지막 값 부호와 같은 연속 일수(양수=순매수 연속, 음수=순매도 연속).
- `parse_funds(js) -> [{"date","deposit","deposit_chg","credit","uncl","mmf"}]` 오름차순 억원.
- `parse_breadth(js) -> {"up","down","flat"}` output1. `parse_sectors(js) -> [{"name","rate"}]` output2에서 이름에 '종합','대형주','중형주','소형주','코스피','TR','50','우선주','VKOSPI','ESG' 포함 행 제외.
- `parse_expected(js) -> float|None` output2 code '0001'의 bstp_nmix_prdy_ctrt.
- `get_market_flow(client=None, now=None)`: `{"investors":{"rows":[-20:],"today":row|None,"streak_frgn","streak_orgn","asof","provisional":bool}, "funds":{"rows":[-20:],"deposit","deposit_chg5_pct","credit","credit_pos20","uncl","asof"}, "breadth":{"kospi":{...},"kosdaq":{...}}, "sectors":{"up":[3],"down":[3]}, "expected":{"rate"}|None, "basis":{"fut","spot","basis"}|None, "asof"}`. provisional = today row date==오늘 and now<16:00. expected는 08:30~09:00만 조회. basis: `marketdata.get_futures()` k200.price와 `client.index("2001")`. 캐시 TTL 표(투자자 300, 자금 3600, 폭·업종 60, 예상 30, 베이시스 60). 키 없음 → `demo_market_flow()`.
- `app.py`: `/api/market-flow`.
- dashboard: 지수 섹션 뒤 `<details class="sec" id="flowsec" style="display:none"><summary>수급·자금 <span class="gdig" id="flow-dig"></span></summary><div class="sec-body"><div id="flow-body"></div><div class="meta" id="flow-foot"></div></div></details>`; JS `loadFlow()` 60초; `renderFlow(d)` 줄 5개(투자자·자금·폭·업종·예상/베이시스), digest "외국인 +6,316억 · 예탁금 93.6조 · 상승 231/하락 634".
- [ ] 테스트 test_marketflow: 픽스처로 investor 오름차순·억 변환(631623→6316.23), streak 계산(부호 열 만든 리스트), funds 억 그대로, breadth 231/634/45, sectors에 '종합' 없음·'화학' 있음, expected 0.94; demo dict 키 전부.
- [ ] 테스트 test_dashboard: HTML에 `flowsec`·`renderFlow` 포함. test_live_api: `/api/market-flow` 키 없음 → 200 + investors 키.
- [ ] `make verify`. 커밋 `feat(home): 시장 수급·자금·폭·업종·예상시가·베이시스`.

### Task 7: 일·주·월봉 KIS 전환 (`kis.py` + `candles.py`)

- `kis.parse_period_candles(js) -> [{"t":"YYYY-MM-DD","open","high","low","close","vol"}]` 오름차순, 빈 clpr 행 제외. `KisClient.period_candles(code, period, end_yyyymmdd, start_yyyymmdd)` → FHKST03010100 params `FID_COND_MRKT_DIV_CODE:"J", FID_INPUT_ISCD, FID_INPUT_DATE_1:start, FID_INPUT_DATE_2:end, FID_PERIOD_DIV_CODE:period, FID_ORG_ADJ_PRC:"0"`(0=수정주가 — KIS 문서. 실측 픽스처는 1(원주가)로 받았고 SK하이닉스는 분할 이력 없어 동일).
- `candles._kis_bars(client, code, period, want)`: end=오늘부터 100봉씩 뒤로 페이징(다음 end = 가장 오래된 날짜-1일), 빈 응답 또는 want 충족 시 종료, 최대 4콜.
- `_daily_candles`: `live`면 `asyncio.run` 불가(스레드) → `_daily_candles`는 to_thread에서 도니 여기서 새 이벤트 루프로 `_kis_bars` 실행(기존 `_long_daily_bars`도 동기). 실패·빈 결과면 FDR 경로로 폴백(로그). `_wm_candles`: live면 KIS W/M 240봉 → MA 계산 → [-120:]; 아니면 기존 aggregate.
- `live` 판정은 `get_candles`의 것과 같은 식(키 있음 and flow_mode != demo). **US 티커는 항상 FDR**(`userstore.market_of(code)=="US"`).
- [ ] 테스트: 픽스처 `daily_itemchartprice` → 파서 6행 오름차순 첫 t '2026-09-01'? (픽스처 6행: 0908,0907,0904,0903,0902,0901 → 오름차순 첫 '2026-09-01', 마지막 close 1793000). `_kis_bars` 페이징 테스트(가짜 client 두 페이지). `_daily_candles` monkeypatch: live+KIS 성공 → FDR 미호출; KIS 예외 → FDR 호출.
- [ ] 커밋 `feat(chart): 일·주·월봉을 KIS 기간별시세로(FDR 폴백)`.

### Task 8: 미국 분봉·체결추이 (`kis.py` + `candles.py` + `usquote.py` + `app.py` + `us_page.py`)

- `kis.parse_us_minutes(js) -> [{"t":"HH:MM:SS","date":"YYYY-MM-DD","ts":int,"open","high","low","close","vol"}]` 오름차순; ts = KST 벽시계를 UTC로 간주한 epoch(`calendar.timegm`) — 차트 라벨이 KST로 보이게(국내 toTs와 같은 관행). `KisClient.us_minutes(exch, sym, nmin)` params `{"AUTH":"","EXCD":exch,"SYMB":sym,"NMIN":str(nmin),"PINC":"1","NEXT":"","NREC":"120","FILL":"","KEYB":""}`.
- `kis.parse_us_ccnl(js) -> {"rows":[{"t","price","vol","vpow"}][-30:] 오름차순,"vpow":float|None}`. `KisClient.us_ccnl(exch, sym)`.
- `usquote.ccnl(client, sym)` 30초 캐시, 거래소 `_cached_exch(sym) or _order(sym)` 순회 첫 성공.
- `candles.get_candles`: US and tf in 5m/15m/60m → `_us_minutes(sym, {"5m":5,"15m":15,"60m":60}[tf])`; 키 없음/데모 → `_demo_minutes` 재사용(달러 소수: demo는 원 정수 → US 데모는 `price/1000` 소수 2자리로 스케일). `app.py`: US 400 거절 제거, 1m만 거절.
- `app.py`: `/api/usccnl/{sym}` → `usquote.ccnl(client, sym)`; 키 없음 → 200 `{"rows":[],"vpow":None}`.
- us_page: tf 버튼 `5분/15분/60분` 추가, `TF_CAP` 확장, `loadCandles`에서 `time: c.ts!=null?c.ts:c.t`; 체결강도 패널 `<div class="panel" id="uc-panel"><h2>체결 테이프·체결강도 <span class="fresh" id="uc-fresh">· REST 60초</span></h2><div class="sig" id="uc-sig"></div><div class="tbl-wrap"><table id="uc-tbl"></table></div></div>` + `loadCcnl()` 60초; `.nomore` 문구를 "분봉은 KIS 해외분봉(REST)로 그립니다"로 정정.
- [ ] 테스트: us_minutes 픽스처 파서(ts 단조 증가, 마지막 close 230.53), us_ccnl 파서(vpow 58.4), `/api/candles/NVDA?tf=5m` 키 없음 → 200 candles>0, test_us_page 문자열('5분','uc-panel').
- [ ] `make verify`(uslive 캡처). 커밋 `feat(us): 분봉 3종 + 체결강도(REST)`.

### Task 9: 문서·마무리

- README 화면 목록에 새 패널 한 줄씩. `docs/kis-unused-features-2026-09.md` 상단에 "반영 현황(2026-09-08)" 표(13항목 상태·커밋). `us_page.py:110` 문구 정정은 Task 8에서.
- `make test` · `make verify` · `make eval` 전부 통과 → 커밋 → 8000 graceful 재기동(`.venv/bin/python`) → `make ops` → 라이브 `/api/stockinfo/000660`·`/api/market-flow` 1회 확인.
