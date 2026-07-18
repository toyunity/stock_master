# KIS API 미사용 기능 분석 & 활용 방안

작성: 2026-07-18 · 대상: Stock Master(개인용 KR주식 실시간 조언 PWA)

---

## 0. 지금 쓰는 것 (baseline)

| 분류 | 사용 중인 엔드포인트/TR |
|---|---|
| 국내 시세 | 현재가(inquire-price, FHKST01010100), 일별시세(inquire-daily-price), 분봉(inquire-time-itemchartprice, FHKST03010200), 시간대별체결(inquire-time-itemconclusion), 투자자별(inquire-investor, FHKST01010900), 회원사(inquire-member) |
| 국내 수급 | 종목별투자자매매일별(investor-trade-by-stock-daily), 투자자매매추이추정(investor-trend-estimate), 외국인·기관합계(foreign-institution-total), 프로그램매매(program-trade-by-stock), 신용잔고 일별(daily-credit-balance), 공매도 일별(daily-short-sale) |
| 국내 순위 | 거래량순위(volume-rank), 등락률순위(ranking/fluctuation) |
| 해외 | 현재가(HHDFS00000300), 현재가상세(HHDFS76200200), 지수·환율(FHKST03030100) |
| 실시간(WS) | 체결가 H0STCNT0, 프로그램매매 H0STPGM0 (KRX / NXT / 통합) |

**요약: "시세 조회 + 실시간 체결·수급" 중심.** 주문/계좌, 실시간 호가, 기업 재무, 종목 스크리닝, 체결·리스크 알림은 전혀 안 쓰고 있음.

---

## 1. 안 쓰지만 가치 큰 기능 — 우선순위

### ⭐ Tier 1 — 저비용·즉효

**① 국내휴장일 조회** — `chk-holiday` / TR `CTCA0903R` (`BASS_DT` 기준일)
- **지금 문제:** `market_status.py`가 "공휴일은 모른다"고 명시 — 평일 공휴일에 벽시계만 보고 '장중' 오표시, 갱신 힌트 오판. (오늘 고친 ADR 갱신 버그와 같은 계열의 정확도 문제)
- **활용:** 연초 1회(또는 월 1회) 휴장일 목록을 당겨 캐시 → `open` 판정과 `refresh_after_sec`가 공휴일까지 정확. KIS TR 1콜/년, 부작용 없음.
- **효과:** 정확도 상시 개선. 난이도 하.

**② 주식잔고조회** — `inquire-balance` / TR `TTTC8434R` (`/uapi/domestic-stock/v1/trading/inquire-balance`)
- **지금 문제:** 사용자가 보유수량·평단을 **손으로 입력** — 초보 최대 마찰점이자 오입력 시 손익이 통째로 틀림.
- **활용:** 계좌에서 실제 보유종목·평균단가·평가손익을 **자동 로드** → 위젯/대시보드 손익이 "추정"이 아니라 "실제값". 수동입력은 선택(관심종목만 담고 싶을 때)으로 강등.
- **주의:** 실계좌 계좌번호(CANO/ACNT_PRDT_CD) 필요, **읽기전용**. 개인용이라 문제 없음. 재배포 대상 아님(내 계좌 데이터).
- **효과:** UX 도약(초보 온보딩 마찰 제거). 난이도 중.

**③ 실시간 호가** — `H0STASP0` (WS)
- **활용:** /live에 매수/매도 10단계 잔량·총잔량비·매물대 → "지금 어디에 사자·팔자가 쌓였나"를 초보에게 신호로 번역. 체결(H0STCNT0)만으로는 안 보이는 벽/받침.
- **주의:** 실시간 등록 개수 상한 존재(계정 단위) → 관심종목 수와 조율 필요.
- **효과:** /live 신호 품질↑. WS 인프라 이미 보유 → 난이도 중.

### ⭐ Tier 2 — 조언·디스커버리 품질

**④ 현재가 시세2** — `inquire-price-2` — PER·PBR·EPS·BPS·52주 고저를 한 콜에.
- 활용: education/advice 레이어에 밸류 지표. "지금 비싼가/싼가"를 숫자로.

**⑤ 재무제표 계열** (재무비율·손익계산서·대차대조표·배당) — 초보용 "이 회사 돈 버나·배당 주나" 설명 카드.

**⑥ 다양한 순위 API** — 체결강도상위·시가총액상위·신용잔고상위·공매도상위·호가잔량상위 등 → 대시보드 "오늘 뭐 볼까" 발굴/스크리닝.

**⑦ 국내 지수** (업종지수 조회 + 실시간 H0UPCNT0) — 코스피·코스닥 지수 컨텍스트(현재 개별종목만 봄).

### Tier 3 — 매매·알림 (마스터가 실제 거래할 때)

**⑧ 실시간 체결통보** `H0STCNI0` — 내 주문 체결 즉시 알림(HTS ID 필요, 계정당 1개 등록).
**⑨ 실현손익/기간손익** `inquire-balance-rlz-pl` 등 — 실현 수익 리포트.
**⑩ VI 발동 조회** — 보유종목 변동성완화장치(급등락) 발동 알림.
**⑪ 주문 API** `order-cash` 등 — 앱에서 직접 매매. 권한·리스크 크므로 신중(별도 결정 필요).

### 해외

**⑫ 해외주식 실시간** `HDFSCNT0`(체결)·`HDFSASP0`(호가) (WS) — ADR/미국주식 실시간.
- **주의:** 무료는 통상 **15분 지연**, 실시간은 별도 신청/유료. 오늘 ADR 갱신을 근본에서 개선하나 지연 조건 확인 필수.

**⑬ 해외 잔고/기간시세** — 미국주식 손익 자동화 + 차트.

---

## 2. 참고 — KIS 공식 자산

- 공식 GitHub `koreainvestment/open-trading-api`에 **LLM용 예제(`examples_llm/`)와 KIS Trading MCP 서버**가 포함 → 우리 Claude 기반 스택과 궁합 좋음(엔드포인트·파라미터 스키마를 그대로 참조 가능).

## 3. 상업화 제약(기존 결론과 연결)

- 개인용은 전부 사용 가능. 단 **실시간 시세 재배포는 상업화 하드블로커**(코스콤 법인전용 유료)로 이미 확인됨 → 잔고/주문은 "내 계좌"라 무관하지만, 시세 데이터를 공개 서비스로 재배포하는 순간 별개 이슈. 개인 앱 범위 유지 시 문제 없음.

## 4. 추천 로드맵

1. **1차(저비용·고효과):** ④ 시세2 + ① 휴장일 — 코드 소량, 정확도·정보량 즉시 상승.
2. **2차(UX 도약):** ② 잔고 자동화 — 초보 온보딩 마찰 제거, 손익 "실제값".
3. **3차(신호 강화):** ③ 실시간 호가 + ⑥ 순위 API.
4. **조건부:** ⑫ 해외 실시간(지연 확인), ⑧⑪ 매매·알림(마스터 거래 시).

---

### 출처
- [KIS Developers 오픈API 개발자센터](https://apiportal.koreainvestment.com/intro)
- [koreainvestment/open-trading-api (공식 GitHub)](https://github.com/koreainvestment/open-trading-api) — chk-holiday(CTCA0903R), inquire-balance(TTTC8434R), inquire-price-2, examples_llm/, KIS Trading MCP 확인
