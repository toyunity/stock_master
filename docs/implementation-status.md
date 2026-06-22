# Stock Master — 구현 현황 (S0–S2 MVP)

| 항목 | 값 |
|---|---|
| 갱신일 | 2026-06-22 |
| 브랜치 | `feature/s3-news` (S3 뉴스/공시 — 병합 대기) · 베이스 `main` |
| 상태 | ✅ S0·S1·S2 + 교육 레이어 + **S3 뉴스/공시** 완료 |
| 테스트 | **90 passed** (pytest) |
| 실행 | 실제 시장 데이터(FDR) + 라이브 RSS(한경·연합)로 end-to-end 확인 |

## 무엇이 동작하나
명령 한 번으로 관심종목 일일 HTML 리포트를 생성한다:
```bash
source .venv/bin/activate
python -m backend.cli report          # 캐시 우선 → docs/report-daily.html
python -m backend.cli report --force  # 캐시 무시하고 새로 받기
python -m backend.cli glossary        # 용어·개념 학습 페이지 → docs/glossary.html
```
파이프라인: **FDR(캐시 우선 어댑터) → `ta` 지표(MA20/MA60/RSI14/MACD) → 규칙 신호(신선한 골든/데드크로스 + RSI 30/70) → 백테스트 게이트(통과 시에만 "조언") → Jinja2 HTML 리포트**.

리포트에는 종목별 {매수관심/매도고려/관망 + 신뢰도 + 근거}와, 게이트를 통과한 매수 신호에는 **백테스트 성과(승률·거래수·손익비·MDD)**와 "검증됨" 배지, 그리고 §16 투자 유의 고지문이 표시된다.

### 📚 교육 레이어 (구현됨 — 초보자 학습용)
- **용어 사전**: 매수/매도·골든크로스·RSI·손절·백테스트 등 **24개 용어**를 "한 줄 뜻 + 공부용 설명"으로 (`backend/education/glossary.py`).
- **리포트 자동 용어 설명**: 그날 리포트에 등장한 용어만 골라 펼침(▶) 설명 + **6개 기초 개념 레슨**("참고 vs 지시", "신뢰도 별의 뜻", "검증됨의 뜻", 손절·분산투자, "관망도 정답").
- **독립 학습 페이지**: `glossary` 명령으로 전체 용어집+개념을 공부용 HTML(`docs/glossary.html`)로 생성.

### 📰 S3 뉴스·이슈 레이어 (구현됨 — 처음 강조한 "이슈 종목" 충족)
- **RSS 수집** (`backend/ingest/rss_source.py`): 한경(증권)·연합(경제·마켓) 피드 → 제목/요약/링크/시각/출처만 보관(본문 미저장, 원문 딥링크). 라이브 **249건** 확인. ⚠️ 한경은 feedparser 기본 UA에 **403** → 브라우저 UA로 우회(회귀 테스트로 고정).
- **DART 공시** (`backend/ingest/dart_source.py`): corpCode 매핑 후 종목별 `list.json` 조회. `SM_DART_API_KEY` 없으면 빈 결과(**키 없이도 가동**). **⚠️ 라이브 미검증** — 목(mock) 응답으로만 테스트됨. 키 발급 후 실응답 1회 검증 필요(status·필드명).
- **정밀 매칭** (`backend/news/match.py`): 회사명 **경계 인식 매칭**(조사 허용, 복합어 배제) — `삼성전자⊄삼성전자서비스`, `현대차⊄현대차증권`, `네이버⊄네이버웹툰`. 공시는 stock_code 정확 일치. **호재/악재 감성태깅은 의도적 제외**(초보자 오해·무자문 설계 충돌). 라이브에서 '삼전'(슬랭)·'현대차증권'(타사) 오매칭 0 확인.
- **리포트 통합**: 종목 카드에 "📌 관련 이슈(참고 정보·자동 수집·**매매 권유 아님**)" 섹션 — 공시(DART 출처)·뉴스(출처·시각) 딥링크. autoescape로 XSS 방어(인용부호/태그 이스케이프 확인).
- **CLI**: `report`가 뉴스/공시를 자동 포함, 수집 실패는 **그레이스풀**(리포트 안 죽음). `--no-news`로 생략 가능.

## 모듈 구조 (구현됨)
```
backend/
├── config.py            # 관심종목·경로 설정 (pydantic-settings)
├── cli.py               # `report` 진입점 (+ --force)
├── adapters/
│   ├── cache.py         # parquet OHLCV 캐시
│   ├── prices.py        # 캐시 우선 + end날짜 커버 검증 (stale 방지)
│   └── db.py            # SQLite 스키마(현재 미연결 — S3+ 사용 예정)
├── ingest/fdr_source.py # FinanceDataReader 래퍼(주입 가능)
├── analysis/
│   ├── indicators.py    # add_indicators()
│   └── backtest.py      # backtest_strategy() + BacktestResult
├── signals/rules.py     # Signal, evaluate(), evaluate_with_gate()
├── report/
│   ├── render.py        # render_daily_report() + render_glossary_page()
│   └── templates/{daily,glossary}.html.j2
└── education/           # 📚 교육 레이어
    ├── glossary.py      # 24개 용어(Term: key/short/long/aliases) + terms_in()
    └── lessons.py       # 6개 기초 개념 레슨
```

## 계획서 대비 변경사항 (실행 환경 적응 + 리뷰 반영)
- **런타임 Python 3.9.6** (환경에 3.13 없음). MVP 의존성 전부 3.9 호환. 모든 모듈에 `from __future__ import annotations` 적용. → S3(DART)는 3.13 또는 **DART REST 직접 호출**로 진행 예정.
- **Jinja2 `autoescape=True`** — 템플릿명이 `.j2`라 `select_autoescape(["html"])`가 비활성이던 결함을 수정(XSS 방어).
- **캐시 날짜 인지** — `code`만으로 캐싱하던 stale 버그 수정: 캐시가 요청 `end` 날짜를 커버할 때만 사용, 아니면 재수집. `--force` 추가.
- **백테스트 성과 첨부** — 게이트 통과 신호에 승률·손익비·MDD를 리포트에 표시(S2 §13 완료기준 충족).
- **§16 정식 고지문** 반영.

## ⚠️ 알려진 한계 & 후속 과제 (우선순위순)
> 신뢰하고 쓰기 전에 반드시 인지할 것.

1. **전략은 아직 실제 검증(out-of-sample)되지 않음.** 백테스트 게이트는 *배관(machinery)*이 동작함을 증명할 뿐, 골든크로스/RSI 전략이 실제로 수익적이라는 보장이 아니다. "검증됨" 배지를 **에지(우위)로 오해하지 말 것**. (설계 §14 과최적화 경고) → 후속: 다양한 종목·기간으로 백테스트, walk-forward 검증.
2. **캐시 증분 수집 없음.** 날짜 커버 검증은 있으나, 뒤처졌을 때 누락분만 append하지 않고 전체 범위를 재수집한다(비효율, 비정상 아님). 휴장일엔 매 실행 재수집 가능. → 후속: 마지막 봉 이후만 incremental fetch.
3. **RSI=100 엣지.** 무손실(단조 상승) 시계열에서 `ta`의 RSI가 100을 반환 → 가짜 "매도" 신호 가능(지표 특성). 실데이터에선 드묾. → 후속: degenerate 입력 가드.
4. **SQLite(db.py) 미연결.** 스키마·테스트는 있으나 파이프라인이 신호/백테스트를 아직 저장하지 않음. → 후속: 신호 이력·모의매매일지 영속화.
5. **라이브 FDR 취약성 미검증.** KRX 로그인 의무화('25.12.27)로 스크래퍼가 깨질 수 있음. 어댑터가 상위를 보호하지만 실패 시 폴백/모니터링은 아직 없음. → 후속: 폴백 소스·헬스체크.
6. **sell/hold 경로 테스트 미고정.** 수동 확인은 했으나 자동 테스트로 잠그지 않음. → 후속: sell/hold/RSI엣지 단위 테스트 추가.
7. **payoff = ∞** — 손실 거래가 0이면 손익비가 무한대로 표시됨(게이트엔 영향 없음). → 후속: 표기 정책 정리.
8. **DART 공시 라이브 미검증.** corpCode/list.json 파싱이 목 응답으로만 테스트됨(키 미발급). status 코드는 int/str 양쪽 방어했으나 실응답 필드명·구조는 미확인. → **마스터가 키(5분) 발급 후 1회 라이브 검증** 필요.
9. **RSS 피드 취약성.** 한경은 UA 차단(403)을 우회로 해결했으나 피드 구조/차단 정책은 예고 없이 변할 수 있음. 연합만으로도 가동되나 200응답·파싱 헬스체크 권장.

## 다음 슬라이스 (각자 별도 계획서로 확장)
- ✅ **교육 레이어** (S6 일부) — 용어 사전·리포트 용어설명·학습 페이지 **완료**.
- ✅ **S3 뉴스/이슈** — RSS(한경·연합) + DART 공시 **완료**(DART REST 직접; 라이브 키 검증 대기).
- **S4 시장 스캐너** — KIS 순위 API(등락률/거래량 Top30) 또는 FDR EOD.
- **S5 실시간** — KIS 웹소켓. **선행: 한국투자증권 실계좌 개설(본인인증, 수일 소요) → 모의투자 키 발급.**
- **S6 나머지** — PWA(모바일 설치), Lightweight Charts 차트, 웹푸시 알림. (교육 콘텐츠는 위에서 완료)

자세한 설계는 `docs/design.md`, 단계별 TDD 작업은 `docs/implementation-plan.md` 참조.
