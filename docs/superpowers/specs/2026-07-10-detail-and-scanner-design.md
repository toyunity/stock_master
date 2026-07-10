# 기관 세부 분해 + 시장 스캐너 — 설계 추가분 (S5 확장 + S4)

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-07-10 (실키 장중 프로브로 TR·필드 확정) |
| 기반 | `2026-07-10-realtime-susub-monitor-design.md` (S5 본설계) |

## 1. 기관 세부 분해 (연기금/투신/금융투자 …)

- **소스**: `FHPTJ04160001` GET `/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily`
  (params: `FID_COND_MRKT_DIV_CODE=J, FID_INPUT_ISCD=code, FID_INPUT_DATE_1=YYYYMMDD, FID_ORG_ADJ_PRC='', FID_ETC_CLS_CODE=''`).
- **실측 확정 사실**: output2 = 요청일 이하 30거래일(최신순). 세부 필드(주 단위):
  연기금 `fund_ntby_qty` · 투신 `ivtr_ntby_qty` · 금융투자 `scrt_ntby_qty` · **사모 `pe_fund_ntby_vol`(접미사 예외)** · 보험 `insu_ntby_qty` · 은행 `bank_ntby_qty` · 기타금융 `mrbn_ntby_qty` · **기타법인 `etc_corp_ntby_vol`(접미사 예외)**. 금액은 같은 접두사 `_ntby_tr_pbmn`(**백만원**). 산술 불변식: 세부 7종 합 == `orgn_ntby_qty`(라이브 검증 404,365 정확 일치).
- **장중 제약(실측)**: `FID_INPUT_DATE_1=오늘`은 15:40까지 HTTP 200 + `rt_cd=2`('TIME LIMIT 00:00~15:40') → **오늘 시도 후 rt_cd=2면 전일로 폴백**. 호출자는 반드시 rt_cd=='0' 확인(HTTP 에러가 아님).
- **장중 세부 분해는 KIS에 존재하지 않음(확정)** — 잠정은 외국인/기관계뿐. 패널은 "확정 · {date} 기준" 라벨.
- **통합**: engine의 일별 폴 주기에 `investor_detail(code)` 1콜 추가(30분당 1건) → `snapshot["detail"] = {date, rows:[{name,qty,value}]}` → /live 페이지에 "🏛️ 기관 세부 수급" 패널(|qty| 내림차순). 데모 모드는 기관계를 세부로 랜덤 분배해 동일 스키마 생성.

## 2. 시장 스캐너 (/scanner — 오늘 수급 특이 종목)

- **5콜 세트(실측 검증, 새로고침당 <1s, 60s 캐시)**:
  1. 외국인 순매수상위: `FHPTJ04400000` `{V,16449,0000,DIV=1(금액),SORT=0,ETC=1}`
  2. 외국인 순매도상위: 〃 `SORT=1`
  3. 기관 순매수상위: 〃 `ETC=2, SORT=0`
  4. 거래대금 상위: `FHPST01710000` `/quotations/volume-rank` `{J,20171,0000,DIV=0,BLNG=3(거래금액순),TRGT=111111111,EXLS=0000001101(ETF/ETN/SPAC 제외)}`
  5. 급등 상위: `FHPST01700000` `/ranking/fluctuation` (**소문자 파라미터**, `fid_rank_sort_cls_code='0'` — 공식 예제의 '0000'은 실서버 OPSQ2002 거부(실측), `fid_vol_cnt=100000`, 동일 EXLS 마스크)
- **실측 필드**: 공통 name=`hts_kor_isnm`, price=`stck_prpr`, sign=`prdy_vrss_sign`(기존 _SIGN 재사용), rate=`prdy_ctrt`, vol=`acml_vol`. **코드 필드명 상이**: 1~4는 `mksc_shrn_iscd`, 5는 `stck_shrn_iscd`. 비 6자리 코드(ETN 'Q…') 방어 필터. 가집계 수량은 1,000주 반올림·**백만원 금액**(SK하이닉스 -1,792,896백만원=-1.79조 실측 일치). 갱신은 하루 4~5회(잠정) — 화면에 잠정 배지.
- **픽 로직**: `외인 순매수 ∩ (거래대금 TOP ∪ 급등 TOP)` + `기관 순매수 ∩ 〃` → "오늘의 수급 특이" 섹션(사유 칩: 외인매수·기관매수·거래대금·급등).
- **구조**: `backend/flow/scanner.py`(순수 파서 3종 + `fetch_scan(client)` + 60s 모듈 캐시) · `backend/report/scanner_page.py`(자기완결 HTML, fetch+60s 자동갱신) · 라우트 `GET /scanner`, `GET /api/scanner`. 각 행은 `/live/{code}` 딥링크. 키 없으면 안내 문구(스캐너는 데모 미제공 — 랭킹 시뮬레이션은 무의미).
- 대시보드 상단에 "🔍 수급 스캐너" 링크.

## 3. 테스트

- 파서: 실응답 기반 픽스처(가집계/거래대금/급등 각 1행 이상, Q코드 필터, 세부 불변식 검증).
- detail: rt_cd=2 폴백 경로, FakeClient로 engine 통합(snapshot["detail"]).
- scanner: fetch_scan 모킹으로 픽 교차 로직·캐시 TTL·라우트 응답.
- e2e: 장중 실서버에서 /scanner·/live 검증 후 main 병합.
