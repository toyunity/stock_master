# 판정 기록과 적중률 — 앱이 한 말을 적어두고 채점한다 (2026-11-02)

## 왜

앱은 매일 두 가지 판단을 내보낸다. 홈 카드의 **내일 예상**(`/api/outlook`, 강세/약세/중립)과
**매매 판정**(`signals/rules.py`, 매수/매도/관망). 둘 다 다음 날 결과와 대조하는 코드가 없다.
그래서 몇 달을 써도 "이 배지를 믿어도 되나"에 답이 안 나오고, 규칙은 영원히 "검증 안 됨"에
머문다(README 알려진 한계 1번). 가장 작은 비용으로 조언의 뿌리를 만드는 작업이다.

채점 대상은 **마스터가 실제로 본 판단**이다. 앱을 안 연 날은 기록이 없고, 그게 맞다 —
보지 않은 예측을 채점할 이유가 없다.

## 결정 (마스터가 질문 생략, 아래는 전부 Claude의 선택)

- **원천 2종만** 기록한다: `outlook`(내일 예상 방향)과 `signal`(일봉 규칙 판정).
  코스피 온도·주봉 MACD·`/live` 패널별 판정은 기록하지 않는다 — 기간(horizon)이 정의돼
  있지 않아 채점 기준을 세울 수 없다. 나중에 붙일 때는 같은 장부에 `kind`만 추가한다.
- **채점 기준**
  - `outlook`: 목표일 T(기록 시점 이후 첫 국내 개장일)의 종가 대 기록 시 가격.
    `up`은 수익률 > 0이면 적중, `down`은 < 0이면 적중. `neutral`은 적중률에서 **제외**하고
    횟수만 센다(중립을 맞았다/틀렸다로 가르면 숫자가 그럴듯해지기만 한다).
  - `signal`: 기록일 D로부터 **10 거래일 뒤** 종가 대 기록 시 가격(백테스트의 `hold_days=10`과
    같은 기간이라 "검증 배지"와 같은 잣대로 비교된다). `buy`는 > 0, `sell`은 < 0이면 적중.
    `hold`는 제외하고 횟수만.
- **가격은 기록 시점의 값을 장부에 박는다**(`px`). "어느 봉의 종가인가"를 나중에 따지지
  않기 위해서다. FDR 일봉은 마지막 봉이 어제 날짜 라벨에 오늘 현재가라서
  ([[fdr-daily-last-bar-is-live]]) 봉 날짜로 역산하면 틀린다.
- **채점은 읽을 때 한다.** 결과를 채우는 두 번째 배치는 없다. 홈을 그릴 때 이미 손에 있는
  일봉 DataFrame(`build_dashboard`의 `frames`)으로 그 자리에서 계산한다.
- **같은 키는 마지막 기록이 이긴다.** 저녁의 예상과 아침(미국장 마감 후)의 예상은 같은
  목표일을 가리키며, 더 많은 정보를 본 쪽이 남는 게 맞다.
- **창은 최근 60 거래일 기준으로 보여주고, 저장은 400일치**를 넘기면 오래된 것부터 버린다.
- **표본이 10 미만이면 비율 대신 "표본 부족 (n/10)"**을 보여준다. 3/4 = 75%는 정보가 아니다.
- **데모 모드(`settings.flow_mode == "demo"`)에서는 쓰지 않는다.** 하네스 데모 서버가
  실계정 `data/`를 읽으므로 가짜 판정이 진짜 장부에 섞인다. 읽기(채점·표시)는 허용.

## 목표 · 비목표

목표: 홈을 열면 "내일 예상이 최근 60일에 몇 번 맞았나", "매수 판정이 10일 뒤 몇 번
올랐나"가 숫자로 보인다. 종목별로도 보인다.

비목표: 매매 일지(내가 실제로 산 기록), 수익률 곡선, 전략 재조정 자동화, 과거 소급 채점
(장부는 오늘부터 쌓인다 — 소급은 "마스터가 본 판단"이라는 정의와 충돌한다).

실패 조건: 기록이 하루에 여러 번 중복으로 쌓인다 · 미확정 봉으로 채점해 다음 날 숫자가
바뀐다 · 데모 서버가 장부를 오염시킨다 · 홈 렌더가 장부 때문에 느려지거나 깨진다.

## 데이터

파일 `data/cache/verdicts.json` (gitignore 영역). 한 객체, 키 = `"{kind}:{code}:{date}"`.

```json
{
  "outlook:000660:2026-11-03": {"dir": "up", "px": 412000, "at": "2026-11-02T18:40:11+09:00"},
  "signal:000660:2026-11-02":  {"dir": "buy", "px": 410500, "advice": true, "at": "..."}
}
```

- `dir` ∈ up/down/neutral(outlook) · buy/sell/hold(signal). `advice`는 signal만(검증 배지 여부 —
  "검증 배지가 붙은 판정이 안 붙은 것보다 나은가"를 나중에 볼 수 있게).
- 쓰기는 `watch.py`와 같은 관용구: 모듈 Lock + temp 파일 + `os.replace`.
- 400일 초과분 정리는 쓰기 때마다 키의 date로 자른다(정렬 1회, 항목 수천 개 — 충분).

## 어디서 쓰나

`backend/flow/verdicts.py` (신규, 순수 함수 위주):

- `record(kind, code, date, dir, px, **extra)` — 위 키로 upsert. `settings.flow_mode == "demo"`면
  no-op. `px`가 None이면 기록하지 않는다(채점 불가한 기록은 소음).
- `score(entries, closes_by_code, today)` — 순수 함수. `closes_by_code[code]`는
  `[(date, close), ...]` 오름차순. 반환은 종목별·전체의 `{n, hit, neutral, pending}`.
- `scorecard(frames, today, window_days=60)` — 장부를 읽고 `frames`(code→DataFrame)를
  `closes_by_code`로 바꿔 `score`를 부른다. 홈 렌더용 dict 반환.

**계정 범위(검토 질문에 대한 결정)**: 장부는 전역 1파일이고 **마스터 계정
(`userstore.default_account()`)이 본 판단만** 기록한다. 계정이 3개라 다른 계정의 관심종목이
섞이면 "내가 본 판단"이 아니다. `get_outlook`·`build_dashboard`에는 email이 없으므로 **라우트가
`ledger=(email == default_account())` 플래그를 넘긴다**(`/`는 `build_dashboard(..., ledger=)`,
`/api/outlook`은 `get_outlook_brief(codes, ledger=)`). 기본값 False — CLI·MCP·테스트 경로는 안 쓴다.

호출 지점 두 곳:

1. **outlook** — `get_outlook`이 `o`에 `session`(이미 있음)과 `px`를 실어 돌려주고,
   `get_outlook_brief(ledger=True)`가 종목마다 `record`를 부른다.
   `session != "kr_open"`일 때만(장중 배지는 "오늘 흐름"이지 예측이 아니다).
   목표일 = `market_status`의 개장일 달력(`_get_open_days(client, now)`)으로 구한 다음 개장일
   (`next_open_sec`의 걸음을 날짜 반환 함수로 뽑아 공유 — `_is_open_day` 재사용).
   `px` = `_gather_signals`가 `client.price()`로 받은 `p["price"]`를 `sig["px"]`로 함께 실어 온다.
2. **signal** — `build_dashboard(ledger=True)`의 종목 루프에서 `evaluate_with_gate` 직후.
   - **date = 그 DataFrame 마지막 봉의 날짜**(`df.index[-1]`), `kst.today()`가 아니다
     (검토 질문에 대한 결정). 금·토·일에 각각 열어도 같은 봉이면 같은 키 → 한 판정이 3표본이
     되지 않는다.
   - **`px` = `build_dashboard`가 이미 쥔 `pm[code]["close"]`**(세션 중엔 KIS 현재가), 없으면
     마지막 `Close`. **정정(리뷰 2026-11-02)**: 장외의 `pm`은 "종가"가 아니라 universe 캐시
     (StockListing, 최대 12h 묵은 전일 종가)다 — 그대로 쓰면 저녁 기록이 장중의 정확한 기록을
     하루 어긋난 값으로 덮어쓴다. 구현은 ledger 경로에서만 장외에도 `_live_prices(kr)`(KIS
     현재가 = 그날 종가)를 px로 쓴다(마스터 홈·국내 ≤12콜, 화면 가격은 불변). 미국 티커는
     기록·채점 모두 제외(국내 적중률에 섞이고 미국 봉 날짜가 60거래일 창을 오염). 검토 실측(2026-11-02 14:05): 일봉 캐시는 그날 첫 로드의
     **부분봉을 하루 종일 서빙**한다(`PriceAdapter._covers_end`가 오늘 라벨이면 재조회 안 함).
     그래서 마지막 `Close`는 "오전 스냅샷"이고, 사용자가 실제로 본 가격은 `pm`이다.
   - 세션 중에도 기록한다. 장중 판정이 부분봉 기반인 건 **앱의 기존 동작**이고, 장부는
     그걸 그대로 재는 게 맞다(마지막 기록이 이기므로 저녁에 다시 열면 그 값이 남는다).
   - `advice` = `signal.advice`.

## 채점 규칙(확정 봉만)

- `outlook`은 **T 날짜의 봉**(목표일 당일 종가), `signal`은 **D 이후 10번째 봉**(백테스트의
  `i + hold_days`와 같은 셈 — D 봉 자체는 기록 시점에 부분봉이라 제외).
- **그 봉 다음 봉이 존재할 때만 확정**으로 본다(FDR 마지막 봉은 진행 중 값). 없으면
  `pending`으로 센다. 다음 날 숫자가 뒤집히지 않게 하는 유일한 장치다.
- 봉이 모자라면(상장 직후·캐시 짧음) pending.

## 화면

홈 `관심종목 분석` 그룹 헤더의 `seccap` 한 줄 + 카드마다 작은 한 줄. 색은 `theme.py`
토큰만 쓴다(비율 ≥ 55% `--good`, ≤ 45% `--down`, 그 사이 `--text-2` — 임계는 Claude의 선택.
`--bad` 토큰은 없다).

```
관심종목 분석   내일예상 적중 17/30 · 매수판정 3/5 (10일) · 중립 12
```

카드(국내만 — 미국 카드는 내일 예상이 없다):

```
🔮 내일 🔴강세 · 간밤 미국 반도체 강세     예상 적중 6/9 · 대기 1
```

표본 10 미만: `내일예상 표본 부족 (4/10)`. 장부 파일이 없으면 줄 자체를 그리지 않는다.
데이터는 `render_dashboard`에 `scorecard`로 넘겨 `D.scorecard`로 베이크한다(새 엔드포인트 없음).

## 테스트 (먼저 빨간 뒤 통과)

`tests/test_verdicts.py`
- 같은 키 두 번 `record` → 항목 1개, 나중 값.
- `px=None` → 기록 없음. `flow_mode="demo"` → 파일 생성 안 됨.
- `score`: up 뒤 상승 = hit, down 뒤 상승 = miss, neutral = 제외·카운트, 다음 봉 없으면 pending.
- `signal`은 10번째 봉으로 채점되고 11번째 봉이 없으면 pending.
- 400일 초과 키 정리.
- `get_outlook_brief(ledger=True)`가 `kr_open` 세션에서는 기록하지 않고, `us_closed`에서는
  다음 개장일 키로 기록(KIS 클라이언트는 기존 테스트 패턴대로 스텁). `ledger=False`(기본)면
  어떤 세션에서도 파일이 안 생긴다.
- `build_dashboard`: 같은 마지막 봉으로 두 번 부르면 키 1개. `px`는 `pm`의 값.
- 모든 테스트는 `cache_dir`를 tmp로 격리한다 — 실 `data/cache/verdicts.json`을 건드리면 안 된다.

`tests/test_dashboard.py` 추가: `scorecard`가 들어오면 헤더 문자열이 렌더되고, 없으면 안 그려진다.
화면 변경이므로 `make verify`까지 돈다(390px 가로 오버플로).

## 빌더에게 맡기는 것

- `next trade date` 헬퍼의 이름과 위치(`market_status` 안이 자연스럽다).
- `score`의 반환 dict 정확한 모양. 화면이 필요로 하는 건 위 숫자뿐이다.
- 홈 카드 한 줄의 정확한 마크업(기존 `.cnd` 배지 옆이면 된다).

## 운영

Python 변경이라 **8000 재기동이 필요하다**(마스터 확인 후, `.venv/bin/python`). 재기동 전까지
장부는 쌓이지 않는다. 3개 설계([[2026-11-02-watch-alert-telegram-design]],
[[2026-11-02-portfolio-line-design]])를 한 번의 재기동으로 묶는 게 좋다.
