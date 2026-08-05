# 지수 선물(코스피200 주간·야간 + 나스닥) 대시보드 표시 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대시보드 상단 지수 칩 스트립에 코스피200 선물(주간↔야간 자동 전환) 칩과 나스닥 선물 칩을 추가한다.

**Architecture:** 기존 지수 라인과 동일한 4계층 — 순수 파서(`flow/futures.py`) → KIS REST(`flow/kis.py`) → TTL 캐시(`api/marketdata.py`) → 칩 렌더(`report/dashboard.py`). 세션 판정 함수 하나가 "지금 주간인가 야간인가"를 정하고 나머지는 그 결과를 따른다. 실시간 웹소켓은 T6(야간 REST 실측)이 실패로 나올 때만 도입한다.

**Tech Stack:** Python 3.9 · FastAPI · httpx · pytest · 바닐라 JS(빌드 스텝 없음)

**Spec:** `docs/superpowers/specs/2026-07-31-index-futures-design.md`

## 진행 상태 (2026-08-05 마감)

| 태스크 | 상태 | 비고 |
|---|---|---|
| T1 세션 판정 + 전광판 파서 | ✅ | `flow/futures.py` |
| T2 KIS 조회 + 캐시 + `/api/futures` | ✅ | |
| T3 대시보드 칩 렌더 + G1 | ✅ | G1 장중 실측 `cls=""` 확정 |
| T4 해외선물 마스터 + 나스닥 월물 | ✅ → **폐기** | G3 계정 차단(CME 유료)으로 코드 삭제(`14ad32d`) |
| T5 나스닥 칩 + G3 | ✅ | QQQ 프록시 → **NQ=F(FinanceDataReader)** 재피벗 |
| T6 G2 실측 (야간 REST 갈림길) | ✅ **해결 2026-08-05 18:10** | **REST는 야간가를 안 준다** → T9 필요 |
| T7 wsbus 세션 버스 | ✅ 배포 | `05b05bb`. G2가 아니라 `OPSP8996` 실사고로 착수 |
| T8 engine → wsbus 이관 + G4 | ✅ 배포·실측 | `ec570cd`. 연결 1개·2종목 동시·오류 0건 |
| T9 야간선물 실시간 등록 | ✅ **배포·실측 2026-08-05 18:30** | `efdb2aa`+`f3abf1f`. 야간선물 1,025.85 |
| T10 문서 마무리 | ✅ | 이 표 + 스펙·`futures-plan.md` 갱신 |

**이 계획서는 T1~T10 전부 닫혔다(2026-08-05).**

**G2 실측 결과(2026-08-05)** — 기준선 17:02(gap=주간 종가) `1042.05 · 4.2% · 117,848`에 대해
18:01·18:04·18:07·18:10 네 샘플이 **세 필드 모두 완전히 동일**했다. 전광판은 야간에도 15:45
스냅샷을 되풀이한다. 기준선을 먼저 찍은 덕에 "야간 유동성이 얇아 체결이 없는 것"과 구분됐다.

**T9 라이브 실측(2026-08-05 18:30)** — 대시보드에 `야간선물 1,025.85 ▼1.55%`. REST가 물고 있던
주간 종가 1042.05가 아니다. **필드 매핑이 스스로 증명됐다**: `price`(인덱스 5)와 `rate`(인덱스 4)를
따로 읽는데 `(1025.85−1042.05)÷1042.05 = −1.555%`로 서로 정확히 맞는다. 매핑이 틀렸다면 두 값이
이렇게 맞아떨어질 이유가 없다. 서버 측은 웹소켓 연결 1개 · 관문 0회 발동 · 오류 0건.
부수 확인: **KRX 야간선물의 '전일대비'는 오늘 주간 종가 기준**(주간 +4.2% → 야간 −1.55%)이다.

**T7·T8은 "조건부"였는데 왜 했나** — G2를 기다리는 동안, 조건부 근거로 적어 둔 1키1세션 위반이
실사고임이 드러났다. `/live` 2종목 동시 열기 → 뒤쪽 종목 `OPSP8996` 영구 차단(직전 프로세스 로그
6,449건). 야간선물과 무관하게 기존 기능이 이미 깨져 있어 G2 결과를 기다리지 않았다.

**남은 것은 T9 하나**이고, 그 착수 여부는 T6(G2) 측정에 달렸다. 순서는 T6 → (필요시) T9.

## Global Constraints

- **Python 3.9 호환** — `X | Y` 타입 문법·`match`·`str.removeprefix` 금지. `Optional[...]`, `from __future__ import annotations` 사용.
- **시각은 전부 KST** — `datetime.now()` 금지, `backend.flow.kst.now()` 사용.
- **테스트는 KIS 미접촉** — 네트워크 호출 없음. 가짜 클라이언트/주입 함수로만 테스트한다(하네스가 테스트 실행 시 KIS 키를 차단한다).
- **웹소켓은 T6 이전까지 미접촉** — KIS는 1키 1세션이고 `/live` 수급이 그 세션을 쓴다.
- **8000 실서버 불가침** — 재기동이 필요하면 `.venv/bin/python`으로만(시스템 python3.9엔 pydantic_settings 없음).
- **개인용 유지** — 시세 재배포 금지.
- **색 관례** — 상승=빨강(`--up`), 하락=파랑(`--down`). 미국식 반대 색 금지.
- **테스트 실행** — `make test` (= `.venv/bin/python -m harness test`). 단일 파일은 `.venv/bin/python -m pytest tests/test_futures.py -v`.
- **커밋 메시지** — 한국어 요약 + `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## File Structure

| 파일 | 상태 | 책임 |
|---|---|---|
| `backend/flow/futures.py` | 신설 | 세션 판정 + 전광판/해외선물마스터 파서. 순수 함수, 네트워크 없음 |
| `backend/flow/kis.py` | 수정 | `futures_board()`, `overseas_futures()`, `download_ff_master()` 추가 |
| `backend/api/marketdata.py` | 수정 | `get_futures()` — 세션별 TTL 캐시 |
| `backend/api/app.py` | 수정 | `GET /api/futures` 라우트 |
| `backend/report/dashboard.py` | 수정 | `#market` 칩 스트립에 선물 칩 2개 + `지연` 배지 CSS |
| `tests/test_futures.py` | 신설 | 세션 경계·파서·월물 선택 |
| `tests/test_marketdata.py` | 수정 | `get_futures` 캐시/세션 분기 |
| `tests/test_dashboard.py` | 수정 | 칩 렌더 스모크 |
| `backend/flow/wsbus.py` | **조건부 신설**(T7) | 웹소켓 세션 단독 소유 — 연결 1개·등록 N건 |

`futures.py`가 `kis.py`의 `_f`/`_i`를 재사용하지 않고 자체 헬퍼를 두는 이유: `kis.py`가 `futures.parse_board()`를 부르므로 반대 방향 임포트를 만들면 순환이 된다. 6줄 중복이 순환보다 싸다.

---

### Task 1: 세션 판정 + 전광판 파서

**Files:**
- Create: `backend/flow/futures.py`
- Test: `tests/test_futures.py`

**Interfaces:**
- Consumes: `backend.flow.kst.now()`, `backend.flow.kst.KST`
- Produces: `session_of(now=None) -> str` (`'day'|'gap'|'night'|'closed'`) · `parse_board(js: dict) -> list[dict]` (각 행 `{code,name,price,rate,sign,volume}`) · `pick_front_month(rows: list) -> Optional[dict]` · 상수 `BOARD_CLS: str`

- [ ] **Step 1: 세션 판정 실패 테스트 작성**

`tests/test_futures.py` 신규 생성:

```python
"""선물 세션 판정 + 전광판/해외선물 마스터 파서 — 네트워크 없음."""
import datetime as dt

from backend.flow import futures as fx
from backend.flow.kst import KST


def _at(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=KST)


def test_session_boundaries_on_weekday():
    """2026-07-30은 목요일. 주간 08:45~15:45, 야간 18:00~."""
    assert fx.session_of(_at(2026, 7, 30, 8, 44)) == "closed"
    assert fx.session_of(_at(2026, 7, 30, 8, 45)) == "day"
    assert fx.session_of(_at(2026, 7, 30, 15, 44)) == "day"
    assert fx.session_of(_at(2026, 7, 30, 15, 45)) == "gap"
    assert fx.session_of(_at(2026, 7, 30, 17, 59)) == "gap"
    assert fx.session_of(_at(2026, 7, 30, 18, 0)) == "night"
    assert fx.session_of(_at(2026, 7, 30, 23, 59)) == "night"


def test_session_night_spans_midnight_and_ends_at_six():
    """야간은 자정을 넘겨 아침 6시에 닫힌다(5시가 아니다 — teardown 실측)."""
    assert fx.session_of(_at(2026, 7, 31, 0, 30)) == "night"
    assert fx.session_of(_at(2026, 7, 31, 5, 59)) == "night"
    assert fx.session_of(_at(2026, 7, 31, 6, 0)) == "closed"


def test_session_weekend():
    """토요일 새벽은 금요일 야간의 연장이고, 토요일 저녁엔 열지 않는다."""
    assert fx.session_of(_at(2026, 8, 1, 3, 0)) == "night"
    assert fx.session_of(_at(2026, 8, 1, 10, 0)) == "closed"
    assert fx.session_of(_at(2026, 8, 1, 19, 0)) == "closed"
    assert fx.session_of(_at(2026, 8, 2, 3, 0)) == "closed"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.flow.futures'`

- [ ] **Step 3: 최소 구현**

`backend/flow/futures.py` 신규 생성:

```python
from __future__ import annotations

"""지수 선물 순수 파서 + 세션 판정 — 네트워크·KIS 미접촉.

선물은 주식과 여는 시간이 다르고(주간 08:45~15:45 / 야간 18:00~익일 06:00) 월물이
롤오버되므로, "지금 어느 세션인가"와 "어느 월물인가"를 여기서만 판단한다.
kis.py에 넣지 않은 이유: kis가 이 모듈의 파서를 부르므로 반대 임포트는 순환이 된다.
Python 3.9 호환."""

import datetime as dt
from typing import Optional

from backend.flow import kst

DAY_OPEN, DAY_CLOSE = 8 * 60 + 45, 15 * 60 + 45      # 08:45 / 15:45
NIGHT_OPEN, NIGHT_CLOSE = 18 * 60, 6 * 60            # 18:00 / 익일 06:00
BOARD_CLS = "MKI"    # 전광판 시장구분(MKI=미니). 정규 코드는 G1에서 확정해 교체.

_SIGN = {"1": "up", "2": "up", "3": "flat", "4": "down", "5": "down"}


def _f(v) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


def _i(v) -> int:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def session_of(now: Optional[dt.datetime] = None) -> str:
    """'day'|'gap'|'night'|'closed' — KST 벽시계 기준.

    공휴일은 보지 않는다(휴장일엔 마지막 성공값이 '마감'으로 남는다 — 지수 칩과 같은 관행)."""
    now = now or kst.now()
    hm, wd = now.hour * 60 + now.minute, now.weekday()   # 월=0 … 일=6
    if hm < NIGHT_CLOSE:              # 00:00~05:59 = 전날 18:00에 열린 야간장의 연장
        return "night" if 1 <= wd <= 5 else "closed"     # 화~토 새벽 = 월~금 야간
    if wd >= 5:                       # 토·일 06:00 이후는 전부 휴장
        return "closed"
    if hm < DAY_OPEN:                 # 06:00~08:44
        return "closed"
    if hm < DAY_CLOSE:                # 08:45~15:44
        return "day"
    if hm < NIGHT_OPEN:               # 15:45~17:59
        return "gap"
    return "night"                    # 18:00~23:59
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 전광판 파서 실패 테스트 추가**

`tests/test_futures.py`에 append:

```python
_BOARD_JS = {"rt_cd": "0", "output": [
    {"futs_shrn_iscd": "101W09", "hts_kor_isnm": "미니F 202609", "futs_prpr": "885.25",
     "futs_prdy_ctrt": "-1.49", "prdy_vrss_sign": "5", "acml_vol": "141272"},
    {"futs_shrn_iscd": "101W12", "hts_kor_isnm": "미니F 202612", "futs_prpr": "889.00",
     "futs_prdy_ctrt": "-1.40", "prdy_vrss_sign": "5", "acml_vol": "312"},
]}


def test_parse_board_maps_documented_fields():
    rows = fx.parse_board(_BOARD_JS)
    assert len(rows) == 2
    assert rows[0] == {"code": "101W09", "name": "미니F 202609", "price": 885.25,
                       "rate": -1.49, "sign": "down", "volume": 141272}


def test_parse_board_returns_empty_on_failure_response():
    assert fx.parse_board({"rt_cd": "1", "msg1": "조회할 자료가 없습니다"}) == []
    assert fx.parse_board({}) == []


def test_pick_front_month_is_the_most_traded_row():
    """월물은 롤오버되므로 코드가 아니라 거래량으로 고른다."""
    assert fx.pick_front_month(fx.parse_board(_BOARD_JS))["code"] == "101W09"
    assert fx.pick_front_month([]) is None
```

- [ ] **Step 6: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v`
Expected: FAIL — `AttributeError: module 'backend.flow.futures' has no attribute 'parse_board'`

- [ ] **Step 7: 파서 구현**

`backend/flow/futures.py`에 append:

```python
def parse_board(js: dict) -> list:
    """display-board-futures(FHPIF05030200) → 월물 행 리스트.

    한 콜에 목록+시세가 같이 온다(2026-07-19 라이브 실측) → 개별 inquire-price 불필요."""
    if js.get("rt_cd") != "0":
        return []
    rows = js.get("output") or js.get("output1") or js.get("output2") or []
    out = []
    for r in rows:
        code = (r.get("futs_shrn_iscd") or "").strip()
        if not code:
            continue
        out.append({"code": code,
                    "name": (r.get("hts_kor_isnm") or "").strip(),
                    "price": _f(r.get("futs_prpr")),
                    "rate": _f(r.get("futs_prdy_ctrt")),
                    "sign": _SIGN.get(str(r.get("prdy_vrss_sign", "")), ""),
                    "volume": _i(r.get("acml_vol"))})
    return out


def pick_front_month(rows: list) -> Optional[dict]:
    """최근월물 = 거래량 최다 행. 만기가 다가오면 거래가 다음 월물로 옮겨가므로
    코드를 하드코딩하지 않고 매번 여기서 다시 고른다(롤오버 자동 대응)."""
    live = [r for r in rows if r.get("price")]
    if not live:
        return None
    return max(live, key=lambda r: r.get("volume", 0))
```

- [ ] **Step 8: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v`
Expected: PASS (6 passed)

- [ ] **Step 9: 커밋**

```bash
git add backend/flow/futures.py tests/test_futures.py
git commit -m "feat(futures): 선물 세션 판정 + 전광판 파서 (순수 함수)

- session_of: 주간 08:45~15:45 / 야간 18:00~익일 06:00, 주말 경계 포함
- parse_board/pick_front_month: 거래량 최다 = 최근월물(롤오버 자동)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: KIS 조회 + 캐시 + API 라우트

**Files:**
- Modify: `backend/flow/kis.py` (KisClient 메서드 추가 — `index()` 바로 뒤)
- Modify: `backend/api/marketdata.py` (`get_indices` 블록 아래)
- Modify: `backend/api/app.py` (`/api/market` 라우트 바로 뒤)
- Test: `tests/test_marketdata.py`

**Interfaces:**
- Consumes: T1의 `futures.parse_board`, `futures.pick_front_month`, `futures.session_of`, `futures.BOARD_CLS`
- Produces: `KisClient.futures_board(cls_code: str) -> list` · `marketdata.get_futures(client=None, now=None) -> Optional[dict]` — 반환 `{"k200": {"label","session","code","name","price","rate","sign","volume"}}` · `GET /api/futures`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_marketdata.py`에 append:

```python
class _FakeFut:
    """선물 전광판만 답하는 가짜 클라이언트."""
    def __init__(self):
        self.calls = 0

    async def futures_board(self, cls_code):
        self.calls += 1
        return [{"code": "101W09", "name": "미니F 202609", "price": 885.25,
                 "rate": -1.49, "sign": "down", "volume": 141272},
                {"code": "101W12", "name": "미니F 202612", "price": 889.0,
                 "rate": -1.40, "sign": "down", "volume": 312}]


def _reset_fut(md):
    md._fut_cache["ts"], md._fut_cache["data"] = 0.0, None


def test_get_futures_picks_front_month_and_labels_day_session():
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST
    _reset_fut(md)
    c = _FakeFut()
    d = asyncio.run(md.get_futures(client=c, now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["k200"]["code"] == "101W09"           # 거래량 최다
    assert d["k200"]["price"] == 885.25
    assert d["k200"]["label"] == "K200선물"
    assert d["k200"]["session"] == "day"


def test_get_futures_labels_night_session_and_caches():
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST
    _reset_fut(md)
    c = _FakeFut()
    night = dt.datetime(2026, 7, 30, 21, 0, tzinfo=KST)
    d = asyncio.run(md.get_futures(client=c, now=night))
    assert d["k200"]["label"] == "야간선물" and d["k200"]["session"] == "night"
    assert c.calls == 1
    asyncio.run(md.get_futures(client=c, now=night))   # 30초 캐시 → 재호출 없음
    assert c.calls == 1


def test_get_futures_keeps_last_value_on_failure():
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _Boom(_FakeFut):
        async def futures_board(self, cls_code):
            raise RuntimeError("KIS 500")

    _reset_fut(md)
    md._fut_cache["ts"], md._fut_cache["data"] = 0.0, {"k200": {"price": 1.0}}
    d = asyncio.run(md.get_futures(client=_Boom(),
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d == {"k200": {"price": 1.0}}          # 직전값 유지(칩이 사라지지 않음)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_marketdata.py -v -k futures`
Expected: FAIL — `AttributeError: module 'backend.api.marketdata' has no attribute '_fut_cache'`

- [ ] **Step 3: KisClient 메서드 추가**

`backend/flow/kis.py`의 `async def index(...)` 메서드 바로 아래에 삽입:

```python
    async def futures_board(self, cls_code: str) -> list:
        """지수선물 전광판 — 월물 목록과 시세가 한 콜에 같이 온다(FHPIF05030200).
        cls_code: MKI=미니. 정규(대형) 코드는 G1 실측에서 확정."""
        from backend.flow import futures as _fx      # 순환 임포트 회피(모듈 로드 시점 분리)
        js = await self._get("/uapi/domestic-futureoption/v1/quotations/display-board-futures",
                             "FHPIF05030200",
                             {"FID_COND_MRKT_DIV_CODE": "F",
                              "FID_COND_SCR_DIV_CODE": "20503",
                              "FID_COND_MRKT_CLS_CODE": cls_code})
        return _fx.parse_board(js)
```

- [ ] **Step 4: marketdata 캐시 추가**

`backend/api/marketdata.py`의 `get_indices` 함수 아래(`_DETAIL_TTL = 300.0` 바로 위)에 삽입:

```python
_FUT_TTL_LIVE, _FUT_TTL_IDLE = 30.0, 300.0   # 세션 활성 30초 / 비활성 5분
_fut_cache = {"ts": 0.0, "data": None}
_FUT_LABEL = {"night": "야간선물"}


async def get_futures(client=None, now=None):
    """{'k200': {label,session,code,name,price,rate,sign,volume}} — 세션별 TTL 캐시.

    키없음이면 None, 조회 실패면 직전 성공값(칩이 깜빡이며 사라지지 않게)."""
    from backend.flow import futures as fx
    client = client or _client()
    if client is None:
        return None
    ses = fx.session_of(now)
    ttl = _FUT_TTL_LIVE if ses in ("day", "night") else _FUT_TTL_IDLE
    if _fut_cache["data"] is not None and time.time() - _fut_cache["ts"] < ttl:
        return _fut_cache["data"]
    try:
        rows = await client.futures_board(fx.BOARD_CLS)
    except Exception:
        return _fut_cache["data"]
    front = fx.pick_front_month(rows)
    if front is None:
        return _fut_cache["data"]
    k200 = dict(front)
    k200["session"] = ses
    k200["label"] = _FUT_LABEL.get(ses, "K200선물")
    data = {"k200": k200}
    _fut_cache["ts"], _fut_cache["data"] = time.time(), data
    return data
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_marketdata.py -v -k futures`
Expected: PASS (3 passed)

- [ ] **Step 6: 라우트 추가**

`backend/api/app.py`의 `market_api` 라우트 바로 아래에 삽입:

```python
    @app.get("/api/futures")
    async def futures_api():
        """지수 선물(코스피200 주간·야간) — 대시보드 칩. 키없음/실패면 {}."""
        from backend.api import marketdata
        return JSONResponse(await marketdata.get_futures() or {})
```

- [ ] **Step 7: 전체 테스트**

Run: `make test`
Expected: 전부 PASS (기존 테스트 회귀 없음)

- [ ] **Step 8: 커밋**

```bash
git add backend/flow/kis.py backend/api/marketdata.py backend/api/app.py tests/test_marketdata.py
git commit -m "feat(futures): 전광판 조회 + 세션별 TTL 캐시 + /api/futures

- KisClient.futures_board(FHPIF05030200) — 목록+시세 한 콜
- get_futures: 활성 30초/비활성 300초, 실패 시 직전값 유지

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 대시보드 칩 렌더 + G1 실검증

**Files:**
- Modify: `backend/report/dashboard.py` (CSS `.mchip` 블록 / `loadMarket()` 함수)
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: T2의 `GET /api/futures` 응답 `{"k200": {...}}`
- Produces: `#market` 스트립에 `.mchip` 2개(선물). 이후 T5가 같은 `fxchip()` JS 함수에 나스닥을 얹는다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_dashboard.py`에 append:

```python
def test_dashboard_polls_futures_and_has_stale_badge_style():
    """선물 칩은 지수 칩과 같은 스트립(#market)에 붙고, '지연' 배지 스타일을 갖는다."""
    html = render_dashboard([_stock()], [{"code": "005930", "name": "삼성전자",
                            "close": 71000, "change": -2.1}], "2026-06-22")
    assert "/api/futures" in html
    assert "fxchip" in html          # 선물 칩 렌더 함수
    assert ".mbadge" in html         # 지연 배지 CSS
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v -k futures`
Expected: FAIL — `assert '/api/futures' in html`

- [ ] **Step 3: CSS 추가**

`backend/report/dashboard.py`의 `.mchip .mr.up{...}` 줄 바로 아래에 삽입:

```css
.mchip .mbadge{margin-left:5px;font-family:var(--font-mono);font-size:9px;font-weight:800;
  letter-spacing:.04em;padding:1px 5px;border-radius:var(--r-pill);
  background:var(--warn-bg);color:var(--warn)}
```

- [ ] **Step 4: loadMarket 확장**

`backend/report/dashboard.py`의 `loadMarket` 함수 전체를 아래로 교체:

```javascript
// ── 시장 지수(코스피·코스닥) + 선물 상단 컨텍스트 — 30초. 장외에도 캐시 직전값. ──
async function loadMarket(){
  try{
    const [rm,rf]=await Promise.all([fetch('/api/market'),
                                     fetch('/api/futures').catch(function(){return null;})]);
    if(!rm||!rm.ok)return;
    const d=await rm.json(); const el=document.getElementById('market');
    const f=(rf&&rf.ok)?await rf.json():{};
    function ix(o,label){
      if(!o||o.price==null)return '';
      const cls=o.rate>0?'up':(o.rate<0?'down':'flat');
      const ar=o.rate>0?'▲':(o.rate<0?'▼':'·');
      return '<div class="mchip"><div class="ml">'+label+'</div>'
        +'<div class="mv">'+o.price.toLocaleString()
        +'<span class="mr '+cls+'">'+ar+Math.abs(o.rate||0).toFixed(2)+'%</span></div></div>';
    }
    function fxchip(o){
      if(!o||o.price==null)return '';
      const cls=o.rate>0?'up':(o.rate<0?'down':'flat');
      const ar=o.rate>0?'▲':(o.rate<0?'▼':'·');
      const badge=o.stale?'<span class="mbadge">지연</span>':'';
      return '<div class="mchip"><div class="ml">'+o.label+badge+'</div>'
        +'<div class="mv">'+o.price.toLocaleString()
        +'<span class="mr '+cls+'">'+ar+Math.abs(o.rate||0).toFixed(2)+'%</span></div></div>';
    }
    const parts=[ix(d.kospi,'코스피'),ix(d.kosdaq,'코스닥'),
                 fxchip(f.k200),fxchip(f.nq)].filter(Boolean);
    if(parts.length){ el.innerHTML=parts.join(''); el.style.display='flex'; }
  }catch(e){}
}
loadMarket(); setInterval(loadMarket,30000);
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: PASS (기존 테스트 포함 전부)

- [ ] **Step 6: 데모 서버로 화면 확인**

Run: `make verify`
Expected: 데모 서버가 뜨고 대시보드가 렌더된다. 데모엔 KIS 키가 없어 선물 칩은 **표시되지 않는 것이 정상**(칩 단위 독립 실패). 코스피/코스닥 칩과 기존 화면이 그대로인지만 확인한다.

- [ ] **Step 7: 커밋**

```bash
git add backend/report/dashboard.py tests/test_dashboard.py
git commit -m "feat(futures): 지수 칩 스트립에 선물 칩 합류 + 지연 배지

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: G1 실검증 — 정규(대형) 선물 코드 확정 (평일 08:45~15:45에만 가능)**

`futures.BOARD_CLS`의 후보를 바꿔가며 어떤 값이 정규 선물을 주는지 확인한다.
아래 스크립트를 `scratchpad/g1_board.py`로 저장하고 실행:

```python
"""G1 — 전광판 시장구분 코드별 응답 비교. REST만 사용(웹소켓 미접촉, 1키1세션 안전)."""
import asyncio

from backend.flow.candles import _get_client
from backend.flow import futures as fx


async def main():
    c = _get_client()
    for cls in ("MKI", "", "MKS", "F"):
        try:
            rows = await c.futures_board(cls)
        except Exception as e:
            print(f"{cls!r:6} → 예외 {e}")
            continue
        top = fx.pick_front_month(rows)
        print(f"{cls!r:6} → {len(rows):3}행  최다월물={top and top['name']}  "
              f"가격={top and top['price']}  거래량={top and top['volume']}")


asyncio.run(main())
```

Run: `.venv/bin/python scratchpad/g1_board.py`
Expected: 어느 한 값이 `"미니F …"`가 아닌 정규 선물명(예 `"F 202609"`)을 돌려준다.
그 값으로 `futures.BOARD_CLS`를 교체하고, 전부 미니만 나오면 `MKI`를 유지한다(같은 코스피200 추종).

- [ ] **Step 9: G1 결과 반영 커밋**

```bash
git add backend/flow/futures.py
git commit -m "fix(futures): G1 실측 — 전광판 시장구분 코드 확정

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 해외선물 종목마스터 파싱 + 나스닥 월물 선택

**Files:**
- Modify: `backend/flow/futures.py`
- Modify: `backend/flow/kis.py` (모듈 레벨 함수 — 클래스 밖, 파일 끝)
- Test: `tests/test_futures.py`

**Interfaces:**
- Consumes: T1의 `futures` 모듈
- Produces: `futures.parse_ff_master(text: str) -> list[dict]` (`{code,name}`) · `futures.pick_nq_series(rows, now=None) -> Optional[str]` · `kis.download_ff_master(cache_dir, ttl_sec=43200.0, fetch=None) -> str`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_futures.py`에 append:

```python
# ffcode.mst 실제 레이아웃(2026-07-31 실측): 종목코드 0:32, 시리즈명 82:132, 총 223자
def _ff_row(code, name):
    return code.ljust(32) + "YYN" + " " * 47 + name.ljust(50) + " " * 91


_FF_TEXT = "\n".join([
    _ff_row("NQU26", "E-mini Nasdaq100-202609"),
    _ff_row("NQZ26", "E-mini Nasdaq100-202612"),
    _ff_row("NQU26-Z26", "E-mini Nasdaq100-2609-2612"),   # 스프레드
    _ff_row("MNQU26", "Micro E-mini Nasdaq100-202609"),   # 마이크로
    _ff_row("MNDU26", "MSCI Indonesia-202609"),           # 이름이 나스닥이 아님
])


def test_parse_ff_master_reads_fixed_width_fields():
    rows = fx.parse_ff_master(_FF_TEXT)
    assert len(rows) == 5
    assert rows[0] == {"code": "NQU26", "name": "E-mini Nasdaq100-202609"}


def test_pick_nq_series_takes_nearest_expiry_emini():
    """코드 접두로 고르면 안 된다 — MND*는 나스닥이 아니라 MSCI Indonesia다."""
    import datetime as dt
    rows = fx.parse_ff_master(_FF_TEXT)
    got = fx.pick_nq_series(rows, now=dt.datetime(2026, 7, 31, 12, 0, tzinfo=KST))
    assert got == "NQU26"


def test_pick_nq_series_rolls_to_next_when_current_expired():
    import datetime as dt
    rows = fx.parse_ff_master(_FF_TEXT)
    got = fx.pick_nq_series(rows, now=dt.datetime(2026, 10, 1, 12, 0, tzinfo=KST))
    assert got == "NQZ26"


def test_pick_nq_series_returns_none_when_absent():
    assert fx.pick_nq_series([]) is None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v -k ff_master or nq_series`
Expected: FAIL — `AttributeError: ... has no attribute 'parse_ff_master'`

- [ ] **Step 3: 파서 구현**

`backend/flow/futures.py`에 append (`import re`를 상단 import 블록에 추가):

```python
# ffcode.mst 고정폭 레이아웃 — KIS 공개 헤더(해외선물정보.h) 기준:
# 종목코드 32 + 자동주문플래그 3 + 필러 47 = 82부터 시리즈명 50
_FF_CODE, _FF_NAME = slice(0, 32), slice(82, 132)
_NQ_PREFIX = "E-mini Nasdaq100-"
_EXPIRY_RE = re.compile(r"-(\d{6})$")


def parse_ff_master(text: str) -> list:
    """해외선물 종목마스터(ffcode.mst) 원문 → [{'code','name'}]."""
    out = []
    for row in text.splitlines():
        if len(row) < _FF_NAME.stop:
            continue
        code, name = row[_FF_CODE].strip(), row[_FF_NAME].strip()
        if code and name:
            out.append({"code": code, "name": name})
    return out


def pick_nq_series(rows: list, now: Optional[dt.datetime] = None) -> Optional[str]:
    """나스닥 E-mini 최근월물 SRS_CD.

    만기는 시리즈명 접미사('-YYYYMM')에서 읽는다. 코드 접두로 고르면 안 된다 —
    MND*는 나스닥이 아니라 MSCI Indonesia다(2026-07-31 마스터 실측).
    마이크로(Micro E-mini)와 스프레드(코드에 '-')는 제외한다."""
    now = now or kst.now()
    ym = now.strftime("%Y%m")
    best = None
    for r in rows:
        if "-" in r["code"] or not r["name"].startswith(_NQ_PREFIX):
            continue
        m = _EXPIRY_RE.search(r["name"])
        if not m or m.group(1) < ym:
            continue
        if best is None or m.group(1) < best[0]:
            best = (m.group(1), r["code"])
    return best[1] if best else None
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: 마스터 다운로드 실패 테스트 추가**

`tests/test_futures.py`에 append:

```python
def test_download_ff_master_caches_and_reuses(tmp_path):
    """공개 파일이라 인증 불필요. 12시간 캐시 — 두 번째 호출은 네트워크를 타지 않는다."""
    from backend.flow import kis
    calls = []

    def _fetch(url):
        calls.append(url)
        return _FF_TEXT

    t1 = kis.download_ff_master(str(tmp_path), fetch=_fetch)
    t2 = kis.download_ff_master(str(tmp_path), fetch=_fetch)
    assert t1 == t2 == _FF_TEXT
    assert len(calls) == 1                       # 두 번째는 캐시


def test_download_ff_master_keeps_stale_cache_on_failure(tmp_path):
    """월물 코드는 만기 전까지 유효 — 낡은 캐시가 무응답보다 낫다."""
    from backend.flow import kis

    def _boom(url):
        raise RuntimeError("network down")

    kis.download_ff_master(str(tmp_path), fetch=lambda url: _FF_TEXT)
    assert kis.download_ff_master(str(tmp_path), ttl_sec=0.0, fetch=_boom) == _FF_TEXT
```

- [ ] **Step 6: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v -k download_ff`
Expected: FAIL — `AttributeError: module 'backend.flow.kis' has no attribute 'download_ff_master'`

- [ ] **Step 7: 다운로드 구현**

`backend/flow/kis.py` 파일 끝(클래스 밖)에 append:

```python
FF_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/ffcode.mst.zip"


def _fetch_ff_master(url: str) -> str:
    import io
    import zipfile

    import httpx
    r = httpx.get(url, timeout=20.0)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = z.namelist()[0]
        return z.read(name).decode("cp949", errors="replace")


def download_ff_master(cache_dir: str, ttl_sec: float = 43200.0, fetch=None) -> str:
    """해외선물 종목마스터(ffcode.mst) 원문 — 인증 불필요 공개 파일, 12h 파일 캐시.

    받기 실패하면 낡은 캐시라도 돌려준다(월물 코드는 만기 전까지 유효). 캐시도 없으면 ''."""
    import os

    path = os.path.join(cache_dir, "ffcode.mst")
    fresh = (os.path.exists(path)
             and time.time() - os.path.getmtime(path) < ttl_sec)
    if fresh:
        with open(path, encoding="utf-8") as f:
            return f.read()
    try:
        text = (fetch or _fetch_ff_master)(FF_MASTER_URL)
    except Exception:
        log.warning("해외선물 마스터 갱신 실패 — 기존 캐시 사용", exc_info=True)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
        return ""
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return text
```

`kis.py` 상단 import에 `time`이 없으면 추가한다(`import time`).

- [ ] **Step 8: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v`
Expected: PASS (13 passed)

- [ ] **Step 9: 커밋**

```bash
git add backend/flow/futures.py backend/flow/kis.py tests/test_futures.py
git commit -m "feat(futures): 해외선물 종목마스터 파싱 + 나스닥 최근월물 선택

- ffcode.mst 고정폭(코드 0:32, 시리즈명 82:132), 12h 파일 캐시·실패 시 stale 유지
- 만기는 시리즈명 접미사로 판정 — MND*는 MSCI Indonesia라 코드 접두 추측 금지

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 나스닥 선물 조회 + 칩 + G3 실검증

**Files:**
- Modify: `backend/flow/futures.py` (`parse_overseas`)
- Modify: `backend/flow/kis.py` (`KisClient.overseas_futures`)
- Modify: `backend/api/marketdata.py` (`get_futures`에 `nq` 추가)
- Test: `tests/test_futures.py`, `tests/test_marketdata.py`

**Interfaces:**
- Consumes: T4의 `parse_ff_master`/`pick_nq_series`/`download_ff_master`, T2의 `get_futures`
- Produces: `futures.parse_overseas(js) -> Optional[dict]` (`{price,rate,at}`) · `KisClient.overseas_futures(srs_cd) -> Optional[dict]` · `get_futures` 반환에 `"nq": {label,price,rate,stale}` 추가

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_futures.py`에 append:

```python
def test_parse_overseas_reads_price_and_rate():
    """HHDFC55010000 응답. 실제 키 이름은 G3에서 확인해 좁힌다(현재는 후보 중 첫 존재 키)."""
    js = {"rt_cd": "0", "output1": {"last": "27713.25", "prdy_ctrt": "-0.75"}}
    assert fx.parse_overseas(js) == {"price": 27713.25, "rate": -0.75}


def test_parse_overseas_returns_none_on_failure():
    assert fx.parse_overseas({"rt_cd": "1"}) is None
    assert fx.parse_overseas({"rt_cd": "0", "output1": {}}) is None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v -k overseas`
Expected: FAIL — `AttributeError: ... has no attribute 'parse_overseas'`

- [ ] **Step 3: 파서 구현**

`backend/flow/futures.py`에 append:

```python
# 해외선물 현재가 응답 키 — G3 실측에서 확인되는 대로 하나로 좁힌다.
_OVS_PRICE_KEYS = ("last", "ovrs_prpr", "prpr", "futs_prpr")
_OVS_RATE_KEYS = ("prdy_ctrt", "prdy_rate", "rate")


def _first(d: dict, keys) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def parse_overseas(js: dict) -> Optional[dict]:
    """해외선물 현재가(HHDFC55010000) → {price, rate}. 실패/빈 응답이면 None."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output1") or js.get("output") or js.get("output2") or {}
    px = _first(o, _OVS_PRICE_KEYS)
    if px is None:
        return None
    return {"price": _f(px), "rate": _f(_first(o, _OVS_RATE_KEYS) or 0)}
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v -k overseas`
Expected: PASS (2 passed)

- [ ] **Step 5: KisClient 메서드 추가**

`backend/flow/kis.py`의 `futures_board` 바로 아래에 삽입:

```python
    async def overseas_futures(self, srs_cd: str) -> Optional[dict]:
        """해외선물 현재가(HHDFC55010000) — 나스닥 E-mini 등. srs_cd는 ffcode.mst의 종목코드."""
        from backend.flow import futures as _fx
        js = await self._get("/uapi/overseas-futureoption/v1/quotations/inquire-price",
                             "HHDFC55010000", {"SRS_CD": srs_cd})
        return _fx.parse_overseas(js)
```

- [ ] **Step 6: marketdata 확장 — 실패 테스트 먼저**

`tests/test_marketdata.py`에 append:

```python
def test_get_futures_includes_nasdaq_chip():
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST

    class _C(_FakeFut):
        async def overseas_futures(self, srs_cd):
            assert srs_cd == "NQU26"
            return {"price": 27713.25, "rate": -0.75}

    _reset_fut(md)
    md._nq_code = "NQU26"                       # 마스터 조회를 건너뛰는 주입점
    d = asyncio.run(md.get_futures(client=_C(),
                                   now=dt.datetime(2026, 7, 30, 11, 0, tzinfo=KST)))
    assert d["nq"]["price"] == 27713.25
    assert d["nq"]["label"] == "나스닥선물"
```

- [ ] **Step 7: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_marketdata.py -v -k nasdaq`
Expected: FAIL — `KeyError: 'nq'`

- [ ] **Step 8: get_futures에 나스닥 추가**

`backend/api/marketdata.py`의 `_fut_cache` 아래에 `_nq_code = None`을 추가하고,
`get_futures`의 `data = {"k200": k200}` 줄을 아래로 교체:

```python
    data = {"k200": k200}
    nq = await _nq_quote(client)
    if nq:
        data["nq"] = nq
```

그리고 `get_futures` 함수 아래에 append:

```python
_nq_code = None      # ffcode.mst에서 고른 나스닥 최근월물 — 프로세스 수명 동안 재사용


async def _nq_quote(client):
    """나스닥 선물 칩 데이터. 마스터 조회·조회 실패는 이 칩만 죽인다(K200 칩은 유지)."""
    global _nq_code
    from backend.flow import futures as fx, kis
    if _nq_code is None:
        text = await asyncio.get_event_loop().run_in_executor(
            None, kis.download_ff_master, settings.cache_dir)
        _nq_code = fx.pick_nq_series(fx.parse_ff_master(text))
    if not _nq_code:
        return None
    try:
        q = await client.overseas_futures(_nq_code)
    except Exception:
        return None
    if not q:
        return None
    return {"label": "나스닥선물", "code": _nq_code, "price": q["price"], "rate": q["rate"]}
```

- [ ] **Step 9: 통과 확인**

Run: `make test`
Expected: 전부 PASS

- [ ] **Step 10: 커밋**

```bash
git add backend/flow/futures.py backend/flow/kis.py backend/api/marketdata.py tests/
git commit -m "feat(futures): 나스닥 선물 칩 — 해외선물 현재가 + 최근월물 자동 선택

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 11: G3 실검증 — 응답 필드명 확정 + 지연 여부**

`scratchpad/g3_nq.py`로 저장하고 실행:

```python
"""G3 — 나스닥 선물 실제 응답 확인. 키 이름과 값의 신선도를 눈으로 본다."""
import asyncio
import json

from backend.config import settings
from backend.flow import futures as fx, kis
from backend.flow.candles import _get_client


async def main():
    rows = fx.parse_ff_master(kis.download_ff_master(settings.cache_dir))
    srs = fx.pick_nq_series(rows)
    print("고른 월물:", srs)
    c = _get_client()
    js = await c._get("/uapi/overseas-futureoption/v1/quotations/inquire-price",
                      "HHDFC55010000", {"SRS_CD": srs})
    print(json.dumps(js, ensure_ascii=False, indent=2)[:2000])


asyncio.run(main())
```

Run: `.venv/bin/python scratchpad/g3_nq.py`
Expected: `rt_cd: "0"`과 현재가가 나온다. 실제 키 이름을 확인해 `_OVS_PRICE_KEYS`/`_OVS_RATE_KEYS`를
확인된 키 하나로 좁히고 `test_parse_overseas_reads_price_and_rate`의 목 JSON도 같이 고친다.
값이 야후(무료 지연 시세)보다 눈에 띄게 늦으면 `_nq_quote`가 `"stale": True`를 함께 넣어
"지연" 배지가 뜨게 한다.

- [ ] **Step 12: G3 반영 커밋**

```bash
git add backend/flow/futures.py backend/api/marketdata.py tests/test_futures.py
git commit -m "fix(futures): G3 실측 — 해외선물 응답 키 확정

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: G2 실검증 — 야간 REST 지원 여부 (갈림길)

**Files:** 없음(실측만). 결과에 따라 T7~T9 착수 여부가 갈린다.

**Interfaces:**
- Consumes: T2의 `KisClient.futures_board`
- Produces: 판정 결과 — REST가 야간 세션가를 주면 **T7~T9 전부 건너뛴다.**

- [ ] **Step 1: 야간 시간대(평일 18:00 이후)에 실측 스크립트 실행**

`scratchpad/g2_night.py`로 저장:

```python
"""G2 — 야간 시간대에 전광판이 야간 세션가를 주는가. REST만(웹소켓 미접촉)."""
import asyncio

from backend.flow import futures as fx
from backend.flow.candles import _get_client
from backend.flow import kst


async def main():
    print("지금 세션:", fx.session_of(), "|", kst.now().strftime("%m-%d %H:%M:%S"))
    c = _get_client()
    for cls in (fx.BOARD_CLS, "", "MKI"):
        try:
            rows = await c.futures_board(cls)
        except Exception as e:
            print(f"{cls!r:6} → 예외 {e}")
            continue
        top = fx.pick_front_month(rows)
        print(f"{cls!r:6} → {len(rows):3}행  {top and top['name']}  "
              f"가격={top and top['price']}  거래량={top and top['volume']}")


asyncio.run(main())
```

Run: `.venv/bin/python scratchpad/g2_night.py` (평일 18:00~24:00 사이)
그리고 **5분 뒤 한 번 더** 실행한다.

- [ ] **Step 2: 판정**

- **거래량이 두 실행 사이에 늘어난다** → 야간 세션가가 REST로 나온다.
  **T7~T9를 건너뛰고 T10(마무리)로 간다.** `/live` 2종목 동시 열기 버그는 별도 이슈로 남긴다.
- **가격·거래량이 15:45 종가에 멈춰 있다** → REST는 주간 값만 준다. **T7로 진행한다.**

- [ ] **Step 3: 판정 결과를 스펙에 기록하고 커밋**

`docs/superpowers/specs/2026-07-31-index-futures-design.md`의 검증 게이트 G2 항목 아래에
실측 결과 한 줄(날짜·시각·거래량 증가 여부·결론)을 추가한다.

```bash
git add docs/superpowers/specs/2026-07-31-index-futures-design.md
git commit -m "docs(spec): G2 실측 결과 기록 — 야간 REST 지원 여부

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7 (조건부): WsSession — 연결 1개·등록 N건

> **G2가 "REST는 주간 값만 준다"로 나왔을 때만 진행한다.**

**Files:**
- Create: `backend/flow/wsbus.py`
- Test: `tests/test_wsbus.py`

**Interfaces:**
- Consumes: `backend.flow.kis.build_subscribe`, `kis.split_frames`, `kis.is_pingpong`, `kis.subscribe_error`, `kis.is_invalid_approval`, `kis.WS_URL`
- Produces: `WsSession.get(client) -> WsSession` · `await session.register(tr_id, tr_key, handler)` · `await session.unregister(tr_id, tr_key, handler)` · `session.status -> dict` (`{"connected": bool, "note": str}`). 핸들러 시그니처는 `handler(record: list) -> None`.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_wsbus.py` 신규 생성:

```python
"""웹소켓 세션 버스 — 연결 1개에 등록 N건. 네트워크 없음(가짜 ws)."""
import asyncio

from backend.flow import wsbus


class _FakeWs:
    def __init__(self, inbox):
        self.sent = []
        self._inbox = list(inbox)

    async def send(self, msg):
        self.sent.append(msg)

    async def recv(self):
        if self._inbox:
            return self._inbox.pop(0)
        await asyncio.sleep(3600)          # 더 올 게 없으면 조용히 멈춘다


class _FakeClient:
    async def approval_key(self):
        return "KEY"

    def reset_approval(self):
        self.reset = True


def test_register_sends_subscribe_once_per_key():
    """같은 (tr_id, tr_key)에 핸들러가 둘 붙어도 구독 프레임은 한 번만 나간다."""
    s = wsbus.WsSession(_FakeClient())
    ws = _FakeWs([])
    s._ws = ws
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: None))
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: None))
    assert len(ws.sent) == 1
    assert "H0UNCNT0" in ws.sent[0] and "005930" in ws.sent[0]


def test_unregister_only_unsubscribes_when_last_handler_leaves():
    s = wsbus.WsSession(_FakeClient())
    ws = _FakeWs([])
    s._ws = ws
    h1, h2 = (lambda rec: None), (lambda rec: None)
    asyncio.run(s.register("H0UNCNT0", "005930", h1))
    asyncio.run(s.register("H0UNCNT0", "005930", h2))
    asyncio.run(s.unregister("H0UNCNT0", "005930", h1))
    assert len(ws.sent) == 1                       # 아직 해지 안 함
    asyncio.run(s.unregister("H0UNCNT0", "005930", h2))
    assert len(ws.sent) == 2                       # 마지막이 빠질 때만 해지


def test_resubscribe_all_after_reconnect():
    """재접속하면 살아 있는 등록을 전부 다시 구독해야 한다."""
    s = wsbus.WsSession(_FakeClient())
    s._ws = _FakeWs([])
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: None))
    asyncio.run(s.register("H0MFCNT0", "101W09", lambda rec: None))
    ws2 = _FakeWs([])
    s._ws = ws2
    asyncio.run(s._resubscribe_all("KEY"))
    assert len(ws2.sent) == 2


def test_dispatch_routes_records_to_matching_handler():
    got = {"stock": [], "futures": []}
    s = wsbus.WsSession(_FakeClient())
    s._ws = _FakeWs([])
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: got["stock"].append(rec)))
    asyncio.run(s.register("H0MFCNT0", "101W09", lambda rec: got["futures"].append(rec)))
    s._dispatch("H0UNCNT0", [["005930", "1", "2"]])
    s._dispatch("H0MFCNT0", [["101W09", "9", "8"]])
    s._dispatch("H0STASP0", [["005930", "x"]])      # 등록 안 한 TR은 무시
    assert got["stock"] == [["005930", "1", "2"]]
    assert got["futures"] == [["101W09", "9", "8"]]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_wsbus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.flow.wsbus'`

- [ ] **Step 3: 구현**

`backend/flow/wsbus.py` 신규 생성:

```python
from __future__ import annotations

"""KIS 웹소켓 세션 버스 — 연결 1개에 등록 N건.

KIS 제약은 '세션 수'(1키 1세션)지 구독 건수가 아니다. 종목 화면마다 연결을 새로 열면
서로를 걷어차므로, 연결은 이 모듈이 단독 소유하고 소비자는 (tr_id, tr_key)로 등록만 한다.
동작(백오프·핑퐁·구독거부·승인키 만료)은 기존 engine._ws_loop에서 그대로 옮겨왔다.
Python 3.9 호환."""

import asyncio
import logging
import random
from typing import Optional

from backend.flow import kis

log = logging.getLogger(__name__)

_INITIAL_BACKOFF = 5      # 재시작 직후 KIS가 이전 세션 정리 전까지 EOF로 거부(실측)
_MAX_BACKOFF = 60
_REJECT_BACKOFF = 30      # 구독 거부는 길게 물러난다


class WsSession:
    _inst: Optional["WsSession"] = None

    def __init__(self, client):
        self._client = client
        self._subs = {}          # (tr_id, tr_key) -> list[handler]
        self._ws = None
        self._task = None
        self._stop = asyncio.Event()
        self.status = {"connected": False, "note": ""}

    @classmethod
    def get(cls, client) -> "WsSession":
        if cls._inst is None:
            cls._inst = cls(client)
        return cls._inst

    async def register(self, tr_id: str, tr_key: str, handler) -> None:
        key = (tr_id, tr_key)
        first = key not in self._subs
        self._subs.setdefault(key, []).append(handler)
        if first and self._ws is not None:
            await self._send_sub(tr_id, tr_key, True)
        if self._task is None:
            self._task = asyncio.ensure_future(self._run())

    async def unregister(self, tr_id: str, tr_key: str, handler) -> None:
        key = (tr_id, tr_key)
        hs = self._subs.get(key)
        if not hs:
            return
        if handler in hs:
            hs.remove(handler)
        if not hs:
            self._subs.pop(key, None)
            if self._ws is not None:
                await self._send_sub(tr_id, tr_key, False)

    async def _send_sub(self, tr_id: str, tr_key: str, on: bool) -> None:
        key = await self._client.approval_key()
        await self._ws.send(kis.build_subscribe(key, tr_id, tr_key, on))

    async def _resubscribe_all(self, approval_key: str) -> None:
        for tr_id, tr_key in list(self._subs):
            await self._ws.send(kis.build_subscribe(approval_key, tr_id, tr_key, True))

    def _dispatch(self, tr_id: str, records: list) -> None:
        for rec in records:
            tr_key = rec[0] if rec else ""
            for h in self._subs.get((tr_id, tr_key), []):
                try:
                    h(rec)
                except Exception:
                    log.warning("웹소켓 핸들러 예외 — 건너뜀", exc_info=True)

    async def _run(self) -> None:
        import websockets
        backoff = _INITIAL_BACKOFF
        while not self._stop.is_set():
            try:
                key = await self._client.approval_key()
                async with websockets.connect(kis.WS_URL, ping_interval=None) as ws:
                    self._ws = ws
                    await self._resubscribe_all(key)
                    self.status = {"connected": True, "note": ""}
                    backoff = _INITIAL_BACKOFF
                    while not self._stop.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        if kis.is_pingpong(raw):
                            await ws.send(raw)      # 원문 그대로 에코(연결 유지 필수)
                            continue
                        parsed = kis.split_frames(raw)
                        if not parsed:
                            continue
                        kind, payload = parsed
                        if kind == "json":
                            err = kis.subscribe_error(payload)
                            if err:
                                backoff = max(backoff, _REJECT_BACKOFF)
                                if kis.is_invalid_approval(err):
                                    self._client.reset_approval()
                                raise RuntimeError("구독 거부: {}".format(err))
                            continue
                        if kind == "data":
                            self._dispatch(payload[0], payload[1])
            except asyncio.CancelledError:
                raise
            except Exception:
                self._ws = None
                log.warning("KIS 웹소켓 끊김 — %ds 후 재접속", backoff, exc_info=True)
                self.status = {"connected": False,
                               "note": "실시간 연결 끊김 — {}초 후 재접속".format(backoff)}
                try:
                    await asyncio.wait_for(self._stop.wait(),
                                           timeout=backoff + random.uniform(0, 3))
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, _MAX_BACKOFF)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_wsbus.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/flow/wsbus.py tests/test_wsbus.py
git commit -m "feat(wsbus): KIS 웹소켓 세션 버스 — 연결 1개·등록 N건

engine._ws_loop의 동작(백오프·핑퐁·구독거부·승인키 만료)을 그대로 옮김.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8 (조건부): FlowEngine을 WsSession으로 전환 + G4 회귀

> **T7을 진행한 경우에만.**

**Files:**
- Modify: `backend/flow/engine.py` (`_ws_loop` 제거 → 등록/해제)
- Test: `tests/test_wsbus.py` (엔진 연동 케이스 추가)

**Interfaces:**
- Consumes: T7의 `WsSession.register/unregister/status`
- Produces: 동작 변화 없음. `/live` 수급 화면이 리팩터 전과 동일해야 한다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_wsbus.py`에 append:

```python
def test_engine_registers_both_tr_ids_and_releases_on_stop(monkeypatch):
    """엔진은 체결·프로그램 두 건을 등록하고, 멈출 때 둘 다 해제한다."""
    from backend.flow import wsbus
    calls = {"reg": [], "unreg": []}

    class _Bus:
        async def register(self, tr_id, tr_key, handler):
            calls["reg"].append((tr_id, tr_key))

        async def unregister(self, tr_id, tr_key, handler):
            calls["unreg"].append((tr_id, tr_key))

        status = {"connected": True, "note": ""}

    monkeypatch.setattr(wsbus.WsSession, "get", classmethod(lambda cls, client: _Bus()))
    from backend.flow.engine import FlowEngine
    eng = FlowEngine("005930")
    asyncio.run(eng._ws_attach(_FakeClient()))
    assert len(calls["reg"]) == 2
    asyncio.run(eng._ws_detach(_FakeClient()))
    assert len(calls["unreg"]) == 2
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_wsbus.py -v -k engine`
Expected: FAIL — `AttributeError: 'FlowEngine' object has no attribute '_ws_attach'`

- [ ] **Step 3: 엔진 전환**

`backend/flow/engine.py`에서 `_ws_loop` 메서드 전체(292~347행)를 삭제하고 아래로 교체:

```python
    async def _ws_attach(self, client: "kis.KisClient") -> None:
        """웹소켓 세션에 체결·프로그램 두 건을 등록한다(연결은 wsbus가 단독 소유)."""
        from backend.flow import wsbus
        ccnl_tr, pgm_tr = kis.ws_tr_ids(settings.market_div)
        bus = wsbus.WsSession.get(client)
        self._ws_regs = [(ccnl_tr, self._on_ccnl), (pgm_tr, self._on_program)]
        for tr_id, handler in self._ws_regs:
            await bus.register(tr_id, self.code, handler)
        self.state.set_status(connected=bus.status["connected"], note=bus.status["note"])

    async def _ws_detach(self, client: "kis.KisClient") -> None:
        from backend.flow import wsbus
        bus = wsbus.WsSession.get(client)
        for tr_id, handler in getattr(self, "_ws_regs", []):
            await bus.unregister(tr_id, self.code, handler)
        self._ws_regs = []

    def _on_ccnl(self, rec: list) -> None:
        self.state.apply_tick(kis.parse_ccnl(rec))

    def _on_program(self, rec: list) -> None:
        self.state.apply_program(kis.parse_program(rec))
```

`_ws_loop`를 태스크로 띄우던 자리(엔진 시작/정지 지점)를 `_ws_attach`/`_ws_detach` 호출로 바꾼다.
정확한 위치는 `grep -n "_ws_loop" backend/flow/engine.py`로 찾는다.

- [ ] **Step 4: 통과 확인**

Run: `make test`
Expected: 전부 PASS

- [ ] **Step 5: G4 회귀 — 골든 + 화면 비교**

`harness verify`는 JSON이 아니라 스크린샷(`harness/artifacts/live-{light,dark}.png` 등)을 낸다.
회귀는 두 층으로 본다.

```bash
# 1) 순수 로직 골든 — 변경 없어야 한다
make ci                      # = harness test + harness eval

# 2) /live 화면 — 리팩터 직전 커밋과 픽셀 비교
make verify && cp harness/artifacts/live-light.png /tmp/live-before.png
git stash && make verify && cp harness/artifacts/live-light.png /tmp/live-base.png
git stash pop
cmp /tmp/live-before.png /tmp/live-base.png && echo "동일" || echo "차이 있음 — 육안 확인"
```

Expected: `make ci` 전부 PASS. 스크린샷은 데모 데이터가 시각을 포함하면 바이트가 달라질 수 있으므로,
차이가 나면 두 PNG를 열어 **패널 구성과 수급 숫자 자리**가 같은지 눈으로 확인한다.

- [ ] **Step 6: 커밋**

```bash
git add backend/flow/engine.py tests/test_wsbus.py
git commit -m "refactor(engine): 웹소켓 연결 소유를 wsbus로 이관 — 1키1세션 위반 제거

동작 보존: 백오프·핑퐁·구독거부·승인키 만료·상태 문구 동일.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: 실서버 반영**

`.venv/bin/python`으로 8000 서버를 graceful 재기동하고 `/live`에서 수급이 흐르는지 눈으로 확인한다.

---

### Task 9 (조건부): 야간선물 실시간 등록

> **T7~T8을 진행한 경우에만.**

**Files:**
- Modify: `backend/api/marketdata.py` (야간엔 WS 값 우선)
- Test: `tests/test_marketdata.py`

**Interfaces:**
- Consumes: T7의 `WsSession`, T1의 `session_of`
- Produces: `get_futures`가 야간에 WS 최신 틱을 쓰고, WS가 없으면 REST 값으로 조용히 강등

- [ ] **Step 1: 야간선물 틱 파서 실패 테스트 작성**

`kis.parse_ccnl`을 쓰면 안 된다 — 그건 주식(H0STCNT0)용이라 필드 순서가 다르고 가격이 정수다
(선물 883.40이 883으로 잘린다). 전용 파서를 만든다.

`tests/test_futures.py`에 append:

```python
def test_parse_ngt_ccnl_reads_futures_field_order():
    """H0MFCNT0 필드 순서(KIS 공식 예제 COLUMN_MAPPING 기준):
    0 종목코드 · 1 영업시간 · 2 전일대비 · 3 부호 · 4 전일대비율 · 5 현재가 ·
    … · 10 누적거래량 · … · 18 미결제약정."""
    rec = ["101W09", "210131", "-1.80", "5", "-0.20", "883.40",
           "885.00", "886.10", "882.05", "3", "141272", "1250000000",
           "884.10", "-0.70", "-0.08", "0", "0", "0", "170400"]
    t = fx.parse_ngt_ccnl(rec)
    assert t["price"] == 883.40          # 소수점 유지(정수 파서 쓰면 883이 된다)
    assert t["rate"] == -0.20
    assert t["change"] == -1.80
    assert t["sign"] == "down"
    assert t["acml_vol"] == 141272
    assert t["oi"] == 170400


def test_parse_ngt_ccnl_ignores_short_record():
    assert fx.parse_ngt_ccnl(["101W09", "210131"]) is None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v -k ngt_ccnl`
Expected: FAIL — `AttributeError: ... has no attribute 'parse_ngt_ccnl'`

- [ ] **Step 3: 틱 파서 구현**

`backend/flow/futures.py`에 append:

```python
# H0MFCNT0(KRX 야간선물 실시간체결) 레코드 인덱스 — KIS 공식 예제의 COLUMN_MAPPING 순서.
# 주식 H0STCNT0과 순서가 다르므로 kis.parse_ccnl을 재사용하면 안 된다(가격도 소수다).
_NGT_PRICE, _NGT_RATE, _NGT_CHANGE, _NGT_SIGN = 5, 4, 2, 3
_NGT_VOL, _NGT_OI = 10, 18


def parse_ngt_ccnl(rec: list) -> Optional[dict]:
    """야간선물 실시간체결 레코드 → {price, rate, change, sign, acml_vol, oi}."""
    if len(rec) <= _NGT_OI:
        return None
    return {"price": _f(rec[_NGT_PRICE]),
            "rate": _f(rec[_NGT_RATE]),
            "change": _f(rec[_NGT_CHANGE]),
            "sign": _SIGN.get(str(rec[_NGT_SIGN]), ""),
            "acml_vol": _i(rec[_NGT_VOL]),
            "oi": _i(rec[_NGT_OI])}
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_futures.py -v`
Expected: PASS

- [ ] **Step 5: 야간 우선 사용 실패 테스트 작성**

`tests/test_marketdata.py`에 append:

```python
def test_get_futures_prefers_ws_tick_at_night():
    """야간엔 실시간 틱이 있으면 그것을, 없으면 REST 값을 쓴다."""
    import datetime as dt
    from backend.api import marketdata as md
    from backend.flow.kst import KST
    _reset_fut(md)
    md._night_tick = {"price": 883.4, "rate": -0.2}
    d = asyncio.run(md.get_futures(client=_FakeFut(),
                                   now=dt.datetime(2026, 7, 30, 21, 0, tzinfo=KST)))
    assert d["k200"]["price"] == 883.4
    md._night_tick = None
    _reset_fut(md)
    d = asyncio.run(md.get_futures(client=_FakeFut(),
                                   now=dt.datetime(2026, 7, 30, 21, 0, tzinfo=KST)))
    assert d["k200"]["price"] == 885.25          # REST 폴백
```

- [ ] **Step 6: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_marketdata.py -v -k ws_tick`
Expected: FAIL — `AttributeError: ... has no attribute '_night_tick'`

- [ ] **Step 7: 구현**

`backend/api/marketdata.py`의 `_fut_cache` 아래에 추가:

```python
_night_tick = None     # 야간선물 실시간 최신 틱(WS) — 없으면 REST 값으로 강등


def _on_night_tick(rec):
    """H0MFCNT0 레코드 → 최신 틱 보관(선물 전용 파서 — 주식용과 필드 순서가 다르다)."""
    global _night_tick
    from backend.flow import futures as fx
    t = fx.parse_ngt_ccnl(rec)
    if t:
        _night_tick = {"price": t["price"], "rate": t["rate"]}
```

그리고 `get_futures`에서 `k200["label"] = ...` 다음 줄에 추가:

```python
    if ses == "night" and _night_tick and _night_tick.get("price"):
        k200["price"] = _night_tick["price"]
        k200["rate"] = _night_tick["rate"]
```

야간 진입 시 등록은 `_nq_quote` 호출 직전에:

```python
    if ses == "night":
        await _ensure_night_ws(client, front["code"])
```

`get_futures` 아래에 append:

```python
_night_reg = None      # 현재 등록된 야간선물 종목코드


async def _ensure_night_ws(client, code):
    """야간 세션에서만 H0MFCNT0을 등록한다. 월물이 바뀌면 이전 등록을 해제하고 새로 건다."""
    global _night_reg
    from backend.flow import wsbus
    if _night_reg == code:
        return
    bus = wsbus.WsSession.get(client)
    if _night_reg:
        await bus.unregister("H0MFCNT0", _night_reg, _on_night_tick)
    await bus.register("H0MFCNT0", code, _on_night_tick)
    _night_reg = code
```

- [ ] **Step 8: 통과 확인**

Run: `make test`
Expected: 전부 PASS

- [ ] **Step 9: 야간 실검증**

평일 18:00 이후 8000 서버에서 대시보드를 열고, 야간선물 칩 값이 수 초 간격으로 움직이는지 본다.
동시에 `/live`를 열어 주식 수급도 계속 흐르는지 확인한다(두 등록이 한 연결을 공유하는지가 핵심).

- [ ] **Step 10: 커밋**

```bash
git add backend/flow/futures.py backend/api/marketdata.py tests/
git commit -m "feat(futures): 야간선물 실시간 등록(H0MFCNT0) — WS 있으면 우선, 없으면 REST

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: 마무리 — 문서 정리

**Files:**
- Modify: `docs/futures-plan.md`
- Modify: `docs/superpowers/specs/2026-07-31-index-futures-design.md`

- [ ] **Step 1: futures-plan.md의 체크리스트를 실측 결과로 채운다**

7/19 체크박스(①②③)를 G1~G3 실측 결과로 갱신하고, 미해결 항목만 남긴다.

- [ ] **Step 2: 스펙에 최종 상태를 기록한다**

WsSession 리팩터를 했는지 안 했는지, 안 했다면 `/live` 2종목 동시 열기 버그가 남아 있다는 것을 명시한다.

- [ ] **Step 3: 커밋**

```bash
git add docs/
git commit -m "docs(futures): 실측 결과 반영 — 게이트 결과와 남은 이슈 정리

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## 자체 검토 결과

**스펙 커버리지**: 목표(칩 2개·시간대 적응)=T2·T3·T5 / 아키텍처 4계층=T1·T2·T3 / `futures.py` 함수 6개=T1(3개)·T4(2개)·T5(1개) / KisClient 메서드=T2·T5 / ffcode 12h 캐시=T4 / 세션별 TTL=T2 / 지연 배지=T3(CSS·렌더)·T5(판정) / 칩 단위 독립 실패=T2·T5 / WsSession=T7·T8·T9 / 테스트 4종=각 태스크 / G1~G4=T3·T5·T6·T8.

**작성 중 잡은 오류 2개(수정 완료)**:
- T9가 야간선물 틱을 `kis.parse_ccnl`로 파싱하게 돼 있었다. 그건 주식(H0STCNT0)용이라 필드 순서가
  다르고 가격이 정수라 883.40이 883으로 잘린다. 전용 `parse_ngt_ccnl`(H0MFCNT0 순서)을 TDD로 추가했다.
- T8의 G4 회귀가 없는 파일(`live-snapshot.json`)을 비교하게 돼 있었다. `harness verify`는 PNG를 내므로
  `make ci`(골든) + 스크린샷 비교로 바꿨다.

**남은 간극 1개(의도적)**:
- `stale` 플래그를 실제로 세우는 곳은 G3 결과에 달려 있어 T5 Step 11에 조건부로 남겼다.
  나스닥이 무지연이면 배지 자체가 필요 없다.
