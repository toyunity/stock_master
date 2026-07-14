# 매매 타이밍 패널 — 이평(20/60/120) × 수급 결합 판정 (설계)

날짜: 2026-07-14 · 상태: 브레인스토밍 확정(/live 패널 · 보수적 · 확정+오늘잠정 수급)

## 목적

초보자에게 종목별 **"지금 매수/관망/매도" 국면**을 평이한 코멘트로 제시한다.
20·60·120일 이동평균 배열(추세)과 수급을 **보수적으로** 결합 — 추세·수급이 함께
확실할 때만 매수/매도, 나머지는 관망. `/live/{code}` 상세 페이지의 새 패널.

## 제약·전제

- **참고용 조언**: "추정·참고용" 라벨 + §16 고지 유지. 과신 방지(초보 보호).
- 기존 인프라 재사용: `analysis/indicators.py`(ma20·ma60·rsi14·macd) + `signals/rules.py`
  (골든/데드크로스 헬퍼) + `FlowState`(수급) + `candles`(일봉 120). **ma120만 신규 추가.**
- 판정은 **순수 함수**로 분리(테스트 용이). 스냅샷에 실려 SSE로 렌더(다른 패널과 동일 패턴).

## 입력

### 추세/이평 (일봉 기반)
- `indicators.py`에 **ma120**(SMA 120) 추가.
- 일봉 120개(`candles.get_candles(code,'1d')`)로 ma20·ma60·ma120 산출.
- **현재 위치는 라이브 현재가** 기준(장중 갱신): close(=현재가) vs ma20/60/120.
  - 정배열: 현재가 > ma20 > ma60 > ma120
  - 역배열: 현재가 < ma20 < ma60 < ma120
  - 그 외: 중립(혼조)
- 골든크로스(최근 N=5봉 내 ma20↑ma60) / 데드크로스(ma20↓ma60) — 기존 `_crossed_up/down`.
- RSI14 과열(≥70)/과매도(≤30). 20일선 이격도(추격 경고용).

### 수급 (FlowState, 확정 주 + 오늘 잠정 확인)
- **확정(주)**: `daily` 최근 5거래일 외인(frgn)·기관(orgn) 순매수 → 방향(순매수/순매도 우위)
  + 연속일수. 외인·기관 합산 추세.
- **오늘 잠정(적시성)**: `estimate` 마지막 슬롯 외인·기관 → 확정 추세와 **같은 방향이면 강,
  엇갈리면 중립으로 완충**.
- **프로그램(보조)**: `program.net_value` 부호.
- 산출: `flow_dir ∈ {inflow, outflow, neutral}` + 강도.

## 판정 로직 — `assess_timing(ind, flows) → verdict` (보수적)

추세 상태 × 수급 방향 매트릭스:

| 추세 \ 수급 | 유입 | 중립 | 이탈 |
|---|---|---|---|
| **정배열** | 🟢 buy — "상승추세+수급 유입. 20일선 눌림목 분할 접근 유효" | 🟡 hold — "추세 강하나 수급 뒷받침 약 — 눌림 확인" | 🟡 hold — "추세 강하나 수급 이탈 — 차익 주의·관망" |
| **중립** | 🟡 watch — "방향 모호, 수급 우호 — 정배열 전환 확인 후" | ⚪ hold — "뚜렷한 신호 없음 — 관망" | 🟡 watch — "방향 모호+수급 이탈 — 관망" |
| **역배열** | 🟡 watch — "하락추세지만 수급 유입 — 바닥 다지기 가능, 반등 확인 후" | 🔴 sell — "하락추세 — 신규매수 자제" | 🔴 sell — "하락추세+수급 이탈 — 신규매수 자제·보유분 관리" |

- **강조 트리거**(확실할 때만): 신선한 골든크로스 + 유입 → buy 강조 / 신선한 데드크로스 +
  이탈 → sell 강조.
- **과열 가드**: buy 조건이라도 RSI≥75 또는 20일선 이격 과대 → hold로 다운그레이드
  ("과열 — 추격 자제, 눌림 대기").
- **데이터 부족**(일봉<120 or 수급 없음) → `stance=null` "판정 보류 — 데이터 부족".
- `confidence 0~3`: (추세 명확도 + 수급 동조 + 트리거)로 산정.

## 출력 스키마
```
timing: {
  stance: "buy"|"hold"|"watch"|"sell"|null,
  tone: "good"|"warn"|"info"|"flat",
  headline: "🟢 매수 우호",
  comment: "상승추세+수급 유입 — 20일선 눌림목 분할 접근",
  reasons: ["정배열(현재가>20>60>120)", "외인 3일 연속 순매수", ...],
  entry_hint: "20일선 XX원 지지 확인 시",
  overheated: false, confidence: 2, asof: "13:20"
}
```

## 구현

- `backend/analysis/indicators.py`: `out["ma120"]=SMA(120)`.
- `backend/analysis/timing.py`(신규): `summarize_flows(state)→flow_summary` +
  `assess_timing(ind_row, flow_summary, last_price)→timing dict`. 순수 함수.
- `backend/flow/models.py`: `FlowState.set_timing()` + 스냅샷에 `timing` 필드.
- `backend/flow/engine.py` `_poll_rest`: 60초 주기로 일봉(캐시) 조회→지표 계산→
  `summarize_flows`+`assess_timing`→`state.set_timing`. 일봉은 하루 단위로 느리게 변하므로
  분봉처럼 자주 안 받아도 됨(30분 캐시), 위치 판정만 라이브 현재가 사용.
- `backend/report/live_page.py`: 가격 차트 아래 **"🧭 매매 타이밍"** 패널 — headline·
  comment·reasons·entry_hint·확신도, tone별 색. 데이터 부족/보류 문구 처리.

## 테스트
- `tests/test_timing.py`: `assess_timing` 매트릭스 — 정배열+유입→buy · 역배열+이탈→sell ·
  정배열+RSI과열→hold 다운그레이드 · 확정·잠정 엇갈림→중립 완충 · 데이터부족→보류 ·
  중립추세→관망. `summarize_flows` 방향/연속일 계산.
- `test_indicators`: ma120 존재·값.
- `test_live_page_js`: 타이밍 패널 렌더(스냅샷 timing으로 headline/comment 채워짐).

## 스코프·리스크
- YAGNI: 목표가·손절가 자동 산정·백테스트 연동·알림은 제외(추후). 이번엔 국면 코멘트만.
- 리스크: 과신 유발 → 보수적 판정 + "참고용" 라벨 + 관망 기본으로 완화.
