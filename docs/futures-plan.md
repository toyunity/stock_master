# 지수 선물(코스피·야간·나스닥) PWA 표시 — 평일 실검증 계획

작성 2026-07-19(토, 휴장) · 사용자 결정: **셋 다 · 평일 실검증하며 구현** · 나스닥은 유료면 **무료 15분 지연** 채택

## 왜 평일 대기
야간선물(18~05시)·나스닥 선물(미국장)은 **장이 열려야 실데이터가 나옴**. 토요일 휴장이라 오늘은
코스피200 선물(정규장)만 마지막 종가로 확인됨. 검증 없이 blind 빌드 금지(fixture-trap).

## 검증된 것 (2026-07-19 라이브)
- **코스피200 선물 목록+시세**: `GET /uapi/domestic-futureoption/v1/quotations/display-board-futures`
  TR `FHPIF05030200`, params `{FID_COND_MRKT_DIV_CODE:"F", FID_COND_SCR_DIV_CODE:"20503", FID_COND_MRKT_CLS_CODE:"MKI"}`
  → output 행: `futs_shrn_iscd, hts_kor_isnm(예 "미니F 202608"), futs_prpr(현재가), futs_prdy_ctrt(등락률),
  prdy_vrss_sign, acml_vol, futs_askp/bidp`. **한 콜에 시세까지** 다 옴(inquire-price 불필요).
  - MKI = **미니** 코스피200 선물. 정규(대형) 선물의 cls 코드는 평일 재확인(다른 값 시도: "" 등).
  - 월물 선택 = **거래량(acml_vol) 최다** 행(최근월물). 코드는 월물마다 바뀜(롤오버) → 매번 board로 재해결.
- 개별 현재가 TR: `inquire-price` `FHMIF10000000` `{FID_COND_MRKT_DIV_CODE:"F", FID_INPUT_ISCD:<code>}`
  (board가 시세를 줘서 보조용).

## 평일 검증 체크리스트

### ① 코스피200 선물 (정규장) — 월 09:00~15:45
- [ ] 정규(대형) 선물 cls 코드 확정(MKI=미니 대신). 안 되면 미니로 진행(같은 KOSPI200 추종).
- [ ] board가 장중 실시간 등락률 주는지(무료·무지연 기대).

### ② 코스피200 야간선물 — 월 18:00~익 05:00
- [ ] **핵심**: 야간 시간대에 `display-board-futures`(같은 TR)가 **야간 세션가**를 주는지 확인.
  - 주면 → REST로 야간선물 해결(WS 회피 성공).
  - 안 주면 → 야간 전용은 WS(H0MFCNT0)뿐 = 1키1세션 충돌 → **야간선물 표시 보류**(대안: SGX/CME 코스피 연계 없음).
- [ ] 야간 board가 별도 cls/scr 코드 필요한지.

### ③ 나스닥 선물 — 미국장(일 저녁 ET ~ 금)
- [ ] SRS_CD(나스닥 E-mini/마이크로 월물코드) 확보 — KIS 해외선물 종목 마스터 파일 또는 포털 검색.
- [ ] `overseas-futureoption/.../inquire-price` TR `HHDFC55010000` `{SRS_CD:<code>}` 응답 확인.
- [ ] **지연/요금**: 무지연이 유료면 → 무료 15분 지연 채택 + UI에 "지연" 배지.

## 설계 (표시 위치)
- 대시보드 상단 **"📊 선물" 라인**(기존 지수 라인 옆/아래), **시간대 적응**:
  - KR 장중 → 코스피200 선물(현재가·등락%).
  - KR 야간(18-05) → 야간선물.
  - 미국 시간대 → 나스닥 선물(지연 배지).
- 셋을 한 줄에 나란히 보여도 됨(공간 되면): `코스피선물 ▲ · 야간 ▲ · 나스닥선물 ▼(지연)`.
- 파서/조립: `backend/flow/futures.py`(신설, 순수 파서 + KisClient 메서드) → `marketdata.get_futures()` (TTL 캐시)
  → `/api/futures` → 대시보드 렌더. **각 단계 라이브 검증 후 커밋**(코스피→야간→나스닥 순).
- 연계 확장(후순위): 야간선물·나스닥 선물을 **내일예상(nextday) 신호로 추가** — 가장 직접적 시초가 예측.

## 안전/제약
- REST·캐시토큰·웹소켓 미접촉(야간 WS는 쓰지 않음) · Python 3.9 · 실시간 재배포 금지(개인용).
- 나스닥 선물 지연 시 반드시 "지연" 표기(오인 방지).
