# 종목 상세 고도화 + 내일장 예상 — 설계

작성 2026-07-18 · 상태: **구현 완료·배포** · 대상: 주린이(near-novice) 개인용 KR주식 PWA

> 구현 커밋: glossary(Task1)·nextday엔진(Task2)·marketdata/엔드포인트(Task3)·/live(Task4)·대시보드(Task5).
> 라이브 실증: 하이닉스 오늘 −12.1%+미국 반도체 약세+수급 이탈 → 규칙 엔진이 "내일 🔵약세 우세"로 정확 종합.

## 1. 목표

관심종목 상세를 초보가 봐도 이해되게 고도화하고, **오늘 동향이 내일 장에 어떻게 반영될지**를
투명한 규칙 기반으로 예상해 보여준다. 세 가지 사용자 결정(확정):

1. **위치: 둘 다 풀로** — 대시보드 카드엔 한 줄 요약, /live 상세엔 풀 설명.
2. **내일 예상: 배지 + 설명 조합** — 방향 배지(🔴강세/🔵약세/⚪중립) + 근거 불릿 + ⚠주의.
3. **용어: 항상 쉬운말 병기** — 지표마다 "지금 값"을 읽어주는 한 줄(값 인식형).

## 2. 접근: 규칙 기반 시나리오 엔진 (LLM 아님)

신호를 규칙으로 조합해 방향·근거를 산출. **투명(근거가 신호로 추적됨)·테스트 가능·무료·오프라인·
빗나가도 이유가 남음.** LLM 생성은 비용·지연·환각·과신 위험으로 제외. 규칙 하나 = 근거 한 줄이라
"배지+설명" 형식과 정확히 맞는다.

## 3. 구성 요소 (기존 엔진 재사용, 단위별 단일 책임)

### 3.1 `backend/education/glossary.py` (확장) — 값 인식형 쉬운말
순수 함수 모음. 각 지표의 "지금 값"을 초보 문장 한 줄로.
- 인터페이스: `read_per(v)`, `read_pbr(v)`, `read_w52_pos(v)`, `read_roe(v)`, `read_debt(v)`,
  `read_bid_ratio(v)`, `read_flow(frgn_net, orgn_net)` → `str | None`(값 없으면 None).
- 값 밴드(v1, 절대 기준 + 헤지어): 예) PER `<10 싼 편 / 10–20 보통 / 20–40 비싼 편 / >40 매우 비쌈`,
  부채 `<50 적은 편·안정 / 50–100 보통 / >150 많은 편·주의`, 52주위치 `>80 고점 부근 / <20 저점 부근`.
- **한계 명시**: v1은 절대 밴드(업종 상대 아님) → 문구에 "업종마다 달라요" 헤지. 향후 업종 상대화.
- 의존: 없음(순수). 테스트: 값→문자열 밴드 경계 TDD.

### 3.2 `backend/signals/nextday.py` (신설) — 규칙 엔진
순수 함수 `outlook(signals: dict) -> dict`. 입력은 상위에서 조립한 신호 번들, 출력:
```
{direction: "up"|"down"|"neutral", score: int,
 reasons: [{text: str, dir: "up"|"down", kind: str}],
 caution: str, session: str, framing: str}
```
- **입력 신호(4종)**:
  - `us`: {sox_rate, nasdaq_rate, mu_rate, us_open}  (semi.get_overview에서)
  - `adr`: {overnight_rate, premium} | None  (adr.get_quote — DR의 KR종가 대비 오버나잇 변화)
  - `flow`: {frgn_net, orgn_net}  (오늘 외국인·기관 순매수, daily_investor/estimate)
  - `momentum`: {rate, overheated(bool), limit_up(bool)}  (오늘 등락/과열)
  - `is_semi`: bool (반도체·미국 상관 종목 여부 — semi 유니버스/adr_map)
- **가중 규칙(v1)**:
  - ADR 오버나잇(ADR 종목·미국 세션 유효 시): >+1.5%→+2, +0.5~1.5%→+1, -0.5~-1.5%→-1, <-1.5%→-2.
  - 미국 반도체/나스닥(is_semi 또는 수출 상관): SOX/나스닥 >+2%→+2, >+1%→+1, 대칭 하락. 미국 개장 전이면 "변수 남음"으로 기여 축소.
  - 수급: 외인·기관 동반 순매수→+1, 동반 순매도→-1, 혼조→0.
  - 모멘텀: 강한 상승(+대금)→+1(지속), **과열(급등/상한가)→0 + 되돌림 주의**, 강한 하락→-1.
  - 방향: net≥+2 강세 / net≤-2 약세 / 그 외 중립. (임계값 튜너블 상수)
- **reasons**: 0이 아닌 신호를 초보 문장으로(예: "간밤 미국 반도체 강세(SOX +2.1%)"). **caution**: 최강 반대 신호 또는 과열, 없으면 일반 문구. 항상 "예상일 뿐, 빗나갈 수 있어요" 톤.
- **세션/시간 인식(`session`,`framing`)**: `market_status`+`adr.us_market_open`로 판정 →
  - `kr_closed_us_pending`(KR 마감·미국 개장 전): "오늘 마감 기준 · 오늘 밤 미국장이 변수"
  - `us_live`: "미국 진행 중 반영" / `us_closed`(간밤~KR개장 전): "간밤 미국·ADR 반영"
  - `kr_open`(장중): 내일 예상은 약하게/생략, "오늘 장중" 표기.
- 의존: 입력 번들만(신호 수집은 상위). 테스트: 대표 번들→direction/reasons/caution TDD.

### 3.3 `backend/api/marketdata.py` (확장) — 신호 수집 + 조립
- `get_outlook(code, client)` **(풀, /live용)**: semi 개요 + adr + 오늘 수급 + 모멘텀을 모아
  `nextday.outlook()` 실행. 60초 캐시. 실패 신호는 빠지고 남은 것으로 산출(부분 실패 허용).
- `get_outlook_brief(codes, client)` **(경량, 대시보드용)**: 비용 억제 위해 축소 신호(전역 미국 방향
  1콜 + 종목 모멘텀[이미 로드된 시세] + ADR 종목만 ADR)로 종목별 {direction, one_reason}. 60초 캐시·동시성 상한.
- `get_stock_detail(code)`(기존): valuation·financials에 **`outlook`(풀) + `explains`(3.1 쉬운말 맵)** 추가.

### 3.4 엔드포인트
- `/api/financials/{code}`(기존 확장): `{valuation, financials, outlook, explains}` — /live가 fetch.
- `/api/outlook`(신설): 관심종목 코드들의 경량 outlook 배치 — 대시보드가 fetch(‌/api/fundamentals와 별개).

### 3.5 렌더
- **/live**: hero 아래 "🔮 내일 예상" 카드 = 배지 + framing 한 줄 + 근거 3~4줄 + ⚠주의 + 면책.
  기존 📊재무·📖호가 라인에 3.1 쉬운말 병기.
- **대시보드 카드**: `내일 🔴강세 우세 · <근거 한 줄>` 배지 라인(‌/api/outlook에서 주입).

## 4. 안전 프레이밍 (필수)
- 모든 예상에 **"시나리오일 뿐, 확정 아님 · 빗나갈 수 있어요"** + 근거 공개(오라클 아님) + 리스크 한 줄.
- 기존 면책("모든 정보는 참고용 · 매매 권유 아님") 유지. 규칙 기반이라 빗나가도 근거가 남는다.
- 개인용 범위 유지(상업화 시 유사투자자문 이슈 별도 — 이 스펙은 개인용 전제).

## 5. 데이터 흐름
```
[semi.get_overview]  [adr.get_quote]  [KIS 수급/시세]        (신호 수집: marketdata)
        \                 |                /
         → get_outlook(code) → nextday.outlook(signals) → {direction,reasons,caution}
                                                         ↓
   /api/financials/{code}(풀) → /live 렌더    /api/outlook(경량) → 대시보드 배지
   glossary.read_*(값) → explains 맵 → 지표 옆 쉬운말
```

## 6. 오류 처리
- 신호 부분 실패: 그 신호만 빼고 남은 것으로 산출(전멸이면 outlook=null → 카드 숨김, 조용히).
- KIS 키 없음/캐시 만료: outlook 생략(에러 대신 없는 것처럼). 토큰 재발급 금지 원칙 유지.

## 7. 테스트
- `nextday.outlook`: 대표 시나리오 TDD — (a)간밤 미국↑+동반순매수→강세, (b)급등+외국인매도→중립+과열주의,
  (c)ADR 갭업→강세, (d)미국↓+수급이탈→약세, (e)신호 결측→중립/생략.
- `glossary.read_*`: 값 밴드 경계 TDD.
- `marketdata.get_outlook/brief`: 가짜 클라이언트 조립·캐시 테스트.
- 렌더: /live 구조 렌더 + node render 하니스 + JS 문법. 대시보드 구조 렌더.
- 라이브: 마스터 키 캐시 토큰으로 실신호 1회 확인(재발급 0·WS 미접촉).

## 8. YAGNI / 범위 밖(v1)
- LLM 문장 생성 없음 · 업종 상대 밸류 없음(절대 밴드) · 예측 정확도 백테스트 없음(추후) ·
  대시보드는 경량 신호만(풀 outlook은 /live).

## 9. 커밋 단위(예정)
glossary 쉬운말 → nextday 엔진 → marketdata 수집/엔드포인트 → /live 렌더 → 대시보드 배지 → 문서.
각 단계 green 커밋(advisor: feature당 1커밋), 라이브 검증 후 배포.
