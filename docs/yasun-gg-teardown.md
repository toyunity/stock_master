# yasun.gg(야선지지) 데이터 파이프라인 분석 — 2026-07-30 실측

관측 시각: 2026-07-30 13:19~13:34 KST (KRX 정규장 + 선물 주간장 개장 중, 야간장은 닫힘)
방법: 공개 HTML/JS 번들 정적 분석 → 공개 `/api/*` 엔드포인트 응답 관찰 → socket.io 스트림 45초 청취 → KIS 공개 종목마스터·오픈API 예제와 필드 대조

---

## 1. 결론: 레이어별 소스 맵

| 화면 | 심볼 | 실제 공급원 | 확정도 |
|---|---|---|---|
| 코스피200 선물/야간선물 | `^KS200` | 국내 증권사 오픈API (KIS로 거의 확정) | 높음 (정황 일치 다중) |
| 코스닥150 선물/야간선물 | `^KQ150` | 동일 | 높음 |
| 코스피200 옵션 전광판 | `/api/options/board` | 동일 (KIS 국내옵션전광판 TR과 필드 1:1) | 높음 |
| 선물 투자자별 수급 | `/api/investor` | 동일 (투자자구분코드 0008/0009/0018…) | 중간 |
| 코스피/코스닥 지수 | `^KS11` `^KQ11` | 네이버 금융 계열로 추정 (m.stock.naver.com) | 중간 — 개별종목 naver는 확정, 지수는 별도 라인(10초 주기)이나 값 일치 미검증 |
| 개별 종목 시세 | `/api/stock/price/*` | **네이버** — 응답에 `"source":"naver"` 명시 | 확정 |
| 나스닥·S&P·VIX·환율·원자재 | `NQ=F` `^IXIC` `USDKRW=X` `GC=F` … | **Yahoo Finance** | 확정 |
| 코인·"위켄드" 프록시 | `BTCUSDT` `NAS100USDT` `EWYUSDT` `XAUTUSDT` | Binance USDⓈ-M (`fapi.binance.com`) + Hyperliquid | 높음 |
| 고객예탁금·신용잔고 | `/api/market-funds` | 금융투자협회 FREESIS (freesis.kofia.or.kr) | 높음 |
| 공시 | `/api/stock/quick/*` | DART (dart.fss.or.kr 원문 링크) | 확정 |
| 차트(TV 버튼) | — | TradingView **위젯/외부링크** (데이터 라이선스 아님) | 확정 |
| 뉴스 번역 | — | Microsoft Azure Translator (개인정보처리방침 수탁자 명시) | 확정 |

즉 **단일 벤더가 아니라, 무료로 얻을 수 있는 소스 4~5개를 심볼 단위로 스티칭**한 구조다.
심볼 네이밍은 Yahoo 티커 관례(`^KS200`, `NQ=F`, `-USD`)를 내부 키로 통일해 쓴다.

---

## 2. 선물·야간선물 레그의 증거 체인 (핵심)

### (a) Yahoo가 아니다
`/api/quote?symbols=^KS200,^KQ150,NQ=F` → Yahoo 프록시임이 응답으로 드러난다.
- `^KS200` → `"name":"KOSPI 200 Index"` (Yahoo shortName), 값 881.79 = **지수(현물)**
- `^KQ150` → `{"error":"HTTP 404"}` (Yahoo에 코스닥150 없음 → 상류 상태코드 그대로 노출)
- `NQ=F` → `"name":"Nasdaq 100 Sep 26"` (Yahoo 근월물 표기)

같은 시각 `/api/prices`의 `^KS200`은 883.65에 `oivolume`(미결제약정) 필드를 달고 있었다.
→ **`/api/quote`(Yahoo)와 `^KS200` 실시간 값은 다른 파이프라인**이며, Yahoo에는 코스피200 선물·미결제약정이 없다.

### (b) 실제로 스트리밍되는 KRX 선물 체결
socket.io(`wss://yasun.gg/socket.io`, `price:subscribe` → `price:update`) 45초 청취:

```
^KS200  px=883.65  vol=141137
^KS200  px=884.10  vol=141160   (+1.5s)
^KS200  px=884.40  vol=141174   (+5.2s)
^KS200  px=885.25  vol=141272   (+1.1s)
```
- 호가단위 0.05 pt, **누적거래량이 단조 증가** → 합성/보간이 아닌 실제 체결 스트림
- 대비: `^KS11`은 10초 주기 + `timestamp`/`name` 필드 동반 → 별도(네이버형) 폴링 라인
- 주의: 이는 *스트리밍*의 증거이지 *무지연*의 증거는 아니다. 사이트 자체 푸터도
  "모든 시세는 비공식이며 실시간이 아닐 수 있습니다"라고 고지한다.

### (c) 세션 커버리지 = KRX 파생 주간 + 야간, 두 상품을 이어붙인 연속 시계열
`/api/candles?symbol=^KS200&interval=1m&limit=1500` (1,497봉, 07-29 03:36 ~ 07-30 13:21 KST) 갭 분석:

```
08:46 ~ 15:35 (+15:45 종가)   ← 주간 선물 (08:45 개장 / 15:45 마감)
갭 15:45 → 18:00
18:00 ~ 05:49                 ← KRX 야간 파생상품시장 (18:00~익일 06:00)
갭 05:49 → 08:46
```
06:00~08:45 구간이 완전히 비어 있어 **CME Globex 연계가 아님**(CME라면 07:00 KST 재개 데이터가 존재).
KRX 자체 야간시장 시간대와 정확히 일치한다.
→ 라벨은 "코스피200 야간선물"이지만 실제로는 **주간물 + 야간물을 하나의 차트로 스티칭**한 것.
   (사이드바 라벨도 "코스피 선물"로 다르게 표기된다.)

### (d) 종목코드가 KIS 종목마스터의 KRX 표준코드와 문자 단위로 일치
`/api/options/board?gubun=G` 응답: `nearMonthCode:"A0169000"`, `callCode:"B0168625"`, `putCode:"C0168625"`

KIS가 공개 배포하는 종목마스터(`new.real.download.dws.co.kr/common/master/fo_idx_code.mst.zip`,
`fo_eurex_code.mst.zip`)를 내려서 대조:
```
1A01609   KR4A01690002  F 202609            ← A0169000 = 코스피200 선물 2026-09
5B01608625KR4B01686256  C 202608  625.0     ← B0168625 = 콜 202608 행사가 625.0
6C01608625KR4C01686255  P 202608  625.0     ← C0168625 = 풋 202608 행사가 625.0
```
yasun의 코드는 KRX 표준코드(ISIN) 12자리에서 `KR4` 접두와 체크디짓을 뗀 본문 8자리다.
A=선물 / B=콜 / C=풋 접두, `016`=코스피200 계열, 뒤 4자리=만기월+행사가.
(KIS 문서의 야간선물 샘플 `101W9000`은 구식 단축코드 표기로, 마스터 파일에는 존재하지 않는다.)

### (e) 응답 필드가 KIS TR 출력과 1:1 대응
| yasun 필드 | KIS 필드 (koreainvestment/open-trading-api) |
|---|---|
| `strike` | `acpr` (행사가) |
| `callCode`/`putCode` | `optn_shrn_iscd` (옵션 단축 종목코드) |
| `callBidRem` | `shnu_rsqn` (매수 잔량) — **Rem = 잔량** |
| `callOfferRem` | `seln_rsqn` (매도 잔량) |
| `callOI`/`putOI`, `oivolume` | `hts_otst_stpl_qty` (HTS 미결제약정수량) |
| `atmType` | `atm_cls_code`/`atm_cls_name` (ATM 구분) |
| `price` / `volume` | `futs_prpr` (선물 현재가) / `acml_vol` (누적거래량) |

그리고 KIS 오픈API에는 이 세트가 정확히 다 있다:
- `H0MFCNT0` KRX 야간선물 실시간체결 (`krx_ngt_futures_ccnl`)
- `H0EUCNT0` 야간옵션 실시간체결, `krx_ngt_futures_asking_price` 등 야간 TR 일습
- `FHPIF05030100` 국내옵션전광판_콜풋, `FHPIF05030200` 국내옵션전광판_선물

→ **KRX 야간선물 실시간을 무료로 주는 사실상 유일한 경로가 국내 증권사 오픈API이고, 그중 KIS의
필드/코드 체계와 관측값이 전부 맞아떨어진다.** 계약 주체를 외부에서 100% 단정할 수는 없으나
(LS증권 등도 유사 TR 보유), KIS 계열로 보는 것이 합리적이다.

### (f) 미확정: 선물 투자자별 수급
`/api/investor?symbol=^KS200` → `[{tjjcode:"0008",name:"개인",msvol:59,msval:177}, …]`
투자자구분 12종(0008 개인 / 0009 외국인 / 0011 금융투자 / 0012 사모 / 0013 보험 / 0014 투신 /
0015 은행 / 0016 기타금융 / 0017 국가 / 0018 기관 / 0019 연기금 / 0020 기타법인).
`tjjcode`(투자자코드), `msvol/msval`(매수 수량/금액), `mdvolume/mdvalue`(매도) 네이밍은
증권사 HTS TR 계열 관례지만 특정 벤더로 못 좁혔다.
socket의 `ij:breadth`(`up/flat/down` + `frgsVol/orgsVal/indVol`)도 같은 라인으로 보인다.

---

## 3. 아키텍처 (재현 관점)

```
Cloudflare (CDN/WAF)
 └ Next.js App Router (SSR, buildId bms5qx1vj)  +  Express API (x-powered-by: Express)
    ├ socket.io  (wss://yasun.gg/socket.io, transports websocket→polling, auth.deviceKey)
    │   events: price:subscribe / price:unsubscribe / price:update / price:batch
    │           ij:breadth / investor:update / chat:* / users:count / server:migrate
    └ REST: /api/prices (전 심볼 스냅샷, 클라이언트 5분 폴링 fallback = setInterval 300000)
            /api/candles, /api/quote(Yahoo), /api/investor, /api/options/board,
            /api/market-funds(KOFIA), /api/stock/price(naver), /api/*-fear-greed(자체 산출)
```

설계상 눈여겨볼 점:
1. **2단 구조** — 얇은 틱 스트림(price/change/volume)을 소켓으로 밀고, 미결제약정 같은 무거운
   필드는 REST 스냅샷에서 채운다. 그래서 `oivolume`이 `/api/prices`엔 있고 `price:update`엔 없다.
2. **소스별 신선도가 제각각** — KRX 심볼은 초 단위로 살아 있는데 `NQ=F`·`USDKRW=X`·`KR10Y`는
   관측 시점에 11시간 묵어 있었다(02:29 KST). Yahoo 레그는 배치성이고 잘 끊긴다.
   `x-cache-status: HIT` — 자체 캐시로 상류 호출량을 줄인다.
3. `server:migrate` 이벤트로 클라이언트를 랜덤 지연 후 재접속시킨다(무중단 배포용).
4. 서버 렌더 HTML이 캐시되어, 새벽에 받아온 페이지에 "야간 개장까지 1시간 49분" 같은 과거 문구가 남는다.

부가: 동시 접속 2,690명 / 채팅 1,225명이 소켓 이벤트로 노출된다. 채팅 메시지에 그 시점 시세
스냅샷(`price`,`changePercent`,`symbol`)이 함께 실려 온다.

---

## 4. 우리 프로젝트(stock_master)에 대한 시사점

**기술적으로는 이미 재현 가능하다.** 우리가 쓰는 KIS 키로 `H0MFCNT0`(야간선물 실시간체결) +
주간 지수선물 체결을 구독해 18:00~06:00 / 08:45~15:45을 이어붙이면 yasun의 `^KS200` 차트와
같은 시계열이 나온다. docs/futures-plan.md의 "평일 실검증 대기" 항목이 바로 이 경로다.
야간 세션 검증은 18:00 이후에만 가능하다.

**법적으로는 그대로 베끼면 안 된다.** 이미 확인해 둔 결론(commercialization-verdict)과 정면으로 만난다:
- yasun은 증권사 오픈API 시세를 2,690명 동시 접속자에게 **재배포**하고 있고, 개별종목은
  `"source":"naver"`로 네이버를 긁어 재배포한다.
- 개인정보처리방침의 수탁자 목록에 Google·Cloudflare·**TradingView(차트 위젯)**·Azure만 있다.
  코스콤·KRX·증권사 시세 계약 흔적이 없다.
- 즉 "남이 하고 있다"는 건 허용된다는 증거가 아니다. 개인용 대시보드(현 우리 포지션)와
  공개 서비스는 선이 다르다.

**깔끔하게 베낄 수 있는 하나**: 차트를 직접 그려 재배포하지 않고 **TradingView로 내보내는 "TV" 버튼**
패턴. 데이터 라이선스 없이 차트 UX를 제공하는 정공법이다.

---

## 5. 재현용 명령 모음

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'
curl -sS -A "$UA" -H 'Referer: https://yasun.gg/' https://yasun.gg/api/prices | jq '.[]|select(.symbol=="^KS200")'
curl -sS -A "$UA" 'https://yasun.gg/api/candles?symbol=%5EKS200&interval=1m&limit=1500' | jq length
curl -sS -A "$UA" 'https://yasun.gg/api/quote?symbols=%5EKS200,%5EKQ150,NQ%3DF'
curl -sS -A "$UA" 'https://yasun.gg/api/options/board?gubun=G' | head -c 400
# 소켓: wss://yasun.gg/socket.io/?EIO=4&transport=websocket → '40{"deviceKey":"…"}' → '42["price:subscribe",{"symbols":["^KS200"]}]'
# KRX 표준코드 대조: https://new.real.download.dws.co.kr/common/master/fo_idx_code.mst.zip
```
