# KIS 미사용 시장데이터 — 구현·반영 계획 (라이브 검증 완료)

작성 2026-07-18 · 검증: 마스터 KIS 키 + 캐시 토큰으로 REST 라이브 프로브(읽기전용, 웹소켓·8000 미접촉)

> **제외(신투 사용자라 무쓸모):** 잔고·매수가능·체결통보(H0STCNI0)·실현손익·주문 — 전부 **한투 계좌**를 읽는 TR. API키(시장데이터)와 무관하게 신투 보유분은 안 보임. → 폐기.
> 남은 건 전부 **순수 시장데이터** = 어느 증권사에서 거래하든 API키만으로 동작.

---

## 0. 검증 결과 요약 (전부 rt_cd=0, 실데이터 수신)

| 기능 | TR / path | 라이브 응답 발췌 |
|---|---|---|
| ① 휴장일 | CTCA0903R · chk-holiday | `bass_dt=20260718, opnd_yn=N`(토요일 정상), output list[24]일치 |
| ④ 밸류(시세2) | FHPST01010000 · inquire-price-2 | dict 48키(per/pbr/eps/bps 포함) |
| ③ 호가/예상체결 | FHKST01010200 · inquire-asking-price-exp-ccn | output1: askp1~10·bidp1~10·잔량 / output2: 예상체결·OHLC |
| ⑤ 재무비율 | FHKST66430300 · finance/financial-ratio | list[23]분기 `roe_val=61.16, eps=56066` |
| ⑦ 지수 | FHPUP02100000 · inquire-index-price | 코스피 `bstp_nmix_prpr=6820.60, ctrt=-6.37` |
| ⑥ 조회상위 | HHMCM000100C0 · ranking/hts-top-view | list[20] `[0]=005930(삼성전자)` |

→ **6/6 통과.** 우리 기존 `KisClient._get(path, tr, params)`로 호출 변경 없이 그대로 동작. 통합은 "파서 + 표면 배선"만 남음.

---

## 1. 기능별 구현 & 현 시스템 반영

### ① 국내휴장일 — `market_status.py` ⭐최우선
- **구현:** `KisClient.holidays(bass_dt)` 추가(파서: output → `{date: opnd_yn=='Y'}`). `latest_trade_date`와 같은 패턴.
- **반영:** `market_status.get_status()`의 open 판정에 "오늘 opnd_yn?"을 결합(현재 `_estimate_trade_date`/벽시계의 "공휴일 모름" 대체). `next_open_sec`도 휴일 스킵. TTL 하루~월.
- **파급:** 위젯 open배지·`refresh_after_sec`·/live 장중판정 전부 공휴일까지 정확. (오늘 ADR 버그와 같은 계열의 정확도 마무리)
- **작업량:** 소 · **위험:** 낮음(읽기전용 조회 1콜/일)

### ④ 밸류지표(PER·PBR·EPS·52주) — `parse_price` 확장 ⭐가성비
- **구현(가장 쌈):** 신규 TR 불필요 — **이미 쓰는** inquire-price(FHKST01010100) output에 per/pbr/eps/bps/w52_hgpr/w52_lwpr가 이미 들어옴. `parse_price`가 안 뽑을 뿐. 필드 6개 추가 파싱이면 끝. (시세2 FHPST01010000는 대안)
- **반영:** dashboard·/live 종목 헤더에 "PER n · PBR n · 52주 x% 지점" 칩 + `education/glossary` 툴팁(초보 설명).
- **작업량:** 소 · **위험:** 낮음

### ③ 호가/매물대 — `/live` FlowState
- **구현 2안:**
  - **(A) REST 스냅샷 폴링(권장 시작):** `client.asking_price(code)` → /live가 수초 간격 폴. **WS 세션 충돌 없음**(1키1세션 안전).
  - **(B) WS 실시간 H0STASP0:** `engine._run_live` 구독에 tr 추가. 실시간이나 등록수 상한·복잡도↑.
- **반영:** `FlowState.apply_asking()` 신설 → /live에 매도벽/매수받침·총잔량비 패널(`live_page.py` 렌더). 초보용 "지금 위/아래 어디 두껍나".
- **작업량:** 중 · **위험:** (A)낮음 / (B)중(WS 등록 관리)

### ⑤ 재무 체력(ROE·성장·부채) — `backend/analysis` or `education`
- **구현:** `client.financials(code)` → 최근 분기 N개(financial-ratio). 분기 갱신이라 TTL 크게.
- **반영:** 종목 상세/교육에 "기업 체력" 카드. `signals/rules`와 연결해 "적자/고부채 경고" 룰 가능.
- **작업량:** 중 · **위험:** 낮음

### ⑦ 시장 지수 컨텍스트 — 대시보드/위젯/live 상단
- **구현:** `client.index(iscd)` 코스피(0001)/코스닥(1001).
- **반영:** 상단 "시장 한 줄"(코스피 ▲/▼%) — 지금은 개별종목만 봐서 "내 종목이 시장 탓인지 종목 탓인지" 구분 불가. 이 한 줄이 그걸 준다.
- **작업량:** 소 · **위험:** 낮음

### ⑥ 발굴/순위 — `scanner_page` / 대시보드
- **구현:** `client.ranking(kind)` — hts-top-view(조회상위)·dividend_rate(배당률) 등. 등락률·거래량은 이미 사용.
- **반영:** 대시보드 "오늘 뭐 볼까" 발굴 패널 또는 scanner_page 확장.
- **작업량:** 중 · **위험:** 낮음

### ⑫ 해외 실시간 — 보류(검증 안 함)
- KIS 해외 실시간은 공식 폴더명이 `delayed_ccnl`/`delayed_asking_price_asia` → **무료는 지연(대개 15분)**, 실시간은 별도 신청/유료. **WS라 프로브 미실시**(마스터 실시간 세션 충돌 회피).
- **판단:** 오늘 고친 ADR 갱신은 이미 REST 폴링(usquote)으로 충분. 실시간이 정말 필요할 때만 지연·요금 확인 후 착수.

---

## 2. 권장 순서 (검증 근거 기반)

1. **① 휴장일 + ④ 밸류지표** — 둘 다 작업량 소, 위험 낮음, 즉효(정확도+정보량). 밸류는 기존 콜 확장이라 사실상 공짜.
2. **⑦ 지수 한 줄** — 소, 체감 큼(시장 맥락).
3. **③ 호가(REST안) + ⑥ 순위** — /live·발굴 강화.
4. **⑤ 재무 카드** — 교육/조언 깊이.
5. 조건부 **⑫ 해외 실시간** — 외부 확인 후.

## 3. 공통 검증 원칙(이번에 적용)
- REST만·캐시 토큰 재사용(재발급=알림톡 금지) · 웹소켓 미접촉(1키1세션) · 8000 실서버 불가침 · Python 3.9 호환.
- 신규 연동마다: (1) 공식 examples_llm에서 path/tr/params 추출 → (2) `_get`로 1회 라이브 프로브 → (3) 파서 유닛테스트(픽스처) → (4) 표면 배선.
