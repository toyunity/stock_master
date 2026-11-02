# 판정 기록·적중률(verdict ledger) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 홈이 내보내는 내일 예상(outlook)과 매매 판정(signal)을 파일에 적어두고, 홈을 그릴 때 일봉으로 채점해 적중률을 헤더와 카드에 보여준다.

**Architecture:** 신규 모듈 `backend/flow/verdicts.py` 하나(저장 `record`/`load` + 순수 채점 `score` + 홈용 `scorecard`). 기록 호출은 기존 두 지점(`marketdata.get_outlook_brief`, `cli.build_dashboard`)에 `ledger` 플래그로 붙고, 라우트가 마스터 계정일 때만 True를 넘긴다. 채점 결과는 `render_dashboard`의 `D` JSON에 `scorecard`로 베이크되며 새 엔드포인트는 없다.

**Tech Stack:** Python 3.9, pandas(이미 있음), JSON 파일, 기존 대시보드 템플릿 JS.

**Spec:** `docs/superpowers/specs/2026-11-02-verdict-ledger-design.md`

## Global Constraints

- Python 3.9 문법만: `match` 금지, `X | Y` 힌트 금지(`Optional[X]`), 모듈 첫 줄 `from __future__ import annotations`.
- 테스트는 `.venv/bin/python -m pytest`. 실서버 8000은 절대 재기동·접촉하지 않는다. KIS 실호출 없음(전부 스텁).
- 새 의존성·새 추상화 금지. 화면 색은 `backend/report/theme.py` 토큰만(`--good`, `--down`, `--text-2`; `--bad`는 없다).
- `settings.flow_mode == "demo"`면 장부에 **쓰지 않는다**(읽기는 허용).
- 장부 파일: `Path(settings.cache_dir) / "verdicts.json"`, 쓰기는 `watch.py` 관용구(모듈 Lock + `.tmp` + `os.replace`). 모든 테스트는 `monkeypatch.setattr(settings, "cache_dir", str(tmp_path))`로 격리한다.
- 키 = `"{kind}:{code}:{date}"`, 값 = `{"dir", "px", "at", ...}`. 마지막 기록이 이긴다. 저장은 400일, 표시 창은 60거래일, 표본 10 미만은 "표본 부족 (n/10)".
- 채점: outlook은 **T 날짜(이상 첫) 봉** 종가, signal은 **D 이후 10번째 봉** 종가, 둘 다 **그 다음 봉이 있어야 확정**(없으면 pending). up/buy는 ret>0, down/sell은 ret<0이 적중. neutral/hold는 `skip`으로 센다.
- 실측·결정의 근거는 코드 주석에 **날짜와 함께** 남긴다. 커밋 메시지는 `feat(verdicts): …` 한국어, 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- 화면(HTML/JS) 변경 후엔 `make verify`까지 돈다.

## Review Focus

1. 장부 JSON이 손상돼도 홈이 떠야 한다 → `load()`가 `{}`를 돌려주고 다음 `record`가 정상 저장 (Task 1 테스트).
2. 관심종목에서 뺀 종목의 기록은 `frames`에 없다 → KeyError 없이 `pending` (Task 2 테스트).
3. `px`가 NaN·0·None이면 기록하지 않는다 (Task 1 테스트).
4. 빈 DataFrame(상장 직후·조회 실패)에서는 signal을 기록하지 않고 홈은 그대로 뜬다 (Task 5 테스트).
5. `frames`가 비어 창 기준을 봉으로 못 잡으면 달력 90일로 폴백한다 (Task 2 테스트).

---

### Task 1: 장부 저장 — `verdicts.record` / `load`

**Files:**
- Create: `backend/flow/verdicts.py`
- Test: `tests/test_verdicts.py`

**Interfaces:**
- Produces: `record(kind: str, code: str, date: str, direction: str, px, **extra) -> bool` (저장했으면 True), `load() -> dict`, `_path() -> Path`, `KEEP_DAYS = 400`.
- `at`은 `kst.now().isoformat(timespec="seconds")`.

- [ ] **Step 1: 실패하는 테스트**

```python
import json, math
import pytest
from backend.config import settings
from backend.flow import verdicts

@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "flow_mode", "")

def test_record_upserts_same_key():
    assert verdicts.record("outlook", "000660", "2026-11-03", "up", 410000)
    assert verdicts.record("outlook", "000660", "2026-11-03", "down", 412000)
    d = verdicts.load()
    assert list(d) == ["outlook:000660:2026-11-03"]
    assert d["outlook:000660:2026-11-03"]["dir"] == "down"
    assert d["outlook:000660:2026-11-03"]["px"] == 412000
    assert "at" in d["outlook:000660:2026-11-03"]

def test_record_keeps_extra_fields():
    verdicts.record("signal", "005930", "2026-11-02", "buy", 71000, advice=True)
    assert verdicts.load()["signal:005930:2026-11-02"]["advice"] is True

@pytest.mark.parametrize("px", [None, 0, float("nan")])
def test_record_skips_unusable_px(px):
    assert verdicts.record("outlook", "000660", "2026-11-03", "up", px) is False
    assert not verdicts._path().exists()

def test_record_noop_in_demo(monkeypatch):
    monkeypatch.setattr(settings, "flow_mode", "demo")
    assert verdicts.record("outlook", "000660", "2026-11-03", "up", 1) is False
    assert not verdicts._path().exists()

def test_record_prunes_older_than_400_days(monkeypatch):
    import datetime as dt
    from backend.flow import kst
    monkeypatch.setattr(kst, "today", lambda: dt.date(2026, 11, 2))
    verdicts.record("outlook", "000660", "2025-09-01", "up", 1)   # 427일 전
    verdicts.record("outlook", "000660", "2026-11-03", "up", 1)
    assert list(verdicts.load()) == ["outlook:000660:2026-11-03"]

def test_load_tolerates_corrupt_file():
    verdicts._path().parent.mkdir(parents=True, exist_ok=True)
    verdicts._path().write_text("{not json", encoding="utf-8")
    assert verdicts.load() == {}
    assert verdicts.record("outlook", "000660", "2026-11-03", "up", 1)
    assert len(verdicts.load()) == 1
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_verdicts.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.flow.verdicts`

- [ ] **Step 3: `backend/flow/verdicts.py` 구현**

모듈 docstring에 스펙의 "왜"(마스터가 본 판단만, 채점은 읽을 때, 데모 금지)를 3줄로. `px` 유효성은 `watch._finite_pos`와 같은 기준(유한·양수). 프루닝은 키의 마지막 `:` 뒤 날짜가 `kst.today() - KEEP_DAYS`보다 이르면 버린다. `kst.today`는 모듈 경유(`kst.today()`)로 불러 테스트가 바꿀 수 있게.

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_verdicts.py -v`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/flow/verdicts.py tests/test_verdicts.py
git commit -m "feat(verdicts): 판정 장부 저장 — kind:code:date 키 upsert·400일 프루닝·데모 모드 무기록"
```

---

### Task 2: 순수 채점 — `verdicts.score`

**Files:**
- Modify: `backend/flow/verdicts.py`
- Test: `tests/test_verdicts.py`

**Interfaces:**
- Produces: `score(entries: dict, closes: dict, today: datetime.date, window_days: int = 60) -> dict`
  - `closes[code]` = `[(date_iso, close_float), ...]` 오름차순, NaN 제외.
  - 반환 `{"outlook": B, "signal": B, "by_code": {code: {"outlook": B, "signal": B}}}`,
    `B = {"n": int, "hit": int, "skip": int, "pending": int}` (`n` = hit+miss, 채점된 것만).
- `HOLD_BARS = 10`, `MIN_SAMPLE = 10`(표시용 상수, Task 6이 참조).

- [ ] **Step 1: 실패하는 테스트**

```python
import datetime as dt

def _closes(start, vals):
    d0 = dt.date.fromisoformat(start)
    return [((d0 + dt.timedelta(days=i)).isoformat(), float(v)) for i, v in enumerate(vals)]

TODAY = dt.date(2026, 11, 20)

def test_score_outlook_hit_miss_neutral_pending():
    entries = {
        "outlook:A:2026-11-03": {"dir": "up", "px": 100},       # 11-03 종가 110 → hit
        "outlook:A:2026-11-04": {"dir": "down", "px": 110},     # 11-04 종가 120 → miss
        "outlook:A:2026-11-05": {"dir": "neutral", "px": 120},  # skip
        "outlook:A:2026-11-06": {"dir": "up", "px": 130},       # 11-06 봉 뒤에 봉 없음 → pending
    }
    closes = {"A": _closes("2026-11-02", [100, 110, 120, 130, 140])}  # 11-02..11-06
    s = verdicts.score(entries, closes, TODAY)
    assert s["outlook"] == {"n": 2, "hit": 1, "skip": 1, "pending": 1}
    assert s["by_code"]["A"]["outlook"] == s["outlook"]
    assert s["signal"] == {"n": 0, "hit": 0, "skip": 0, "pending": 0}

def test_score_outlook_uses_first_bar_on_or_after_target():
    entries = {"outlook:A:2026-11-07": {"dir": "up", "px": 100}}   # 11-07 봉 없음(휴장)
    closes = {"A": _closes("2026-11-05", [100, 100]) + [("2026-11-08", 101.0), ("2026-11-09", 50.0)]}
    s = verdicts.score(entries, closes, TODAY)
    assert s["outlook"] == {"n": 1, "hit": 1, "skip": 0, "pending": 0}

def test_score_signal_grades_10th_bar_after_D_and_needs_11th():
    entries = {"signal:A:2026-11-01": {"dir": "buy", "px": 100},
               "signal:A:2026-11-02": {"dir": "sell", "px": 100},
               "signal:A:2026-11-03": {"dir": "hold", "px": 100}}
    # 11-01 이후 10번째 봉 = 11-11(종가 90) → buy miss; 11번째 봉(11-12) 있어야 확정
    closes = {"A": _closes("2026-11-01", [100] * 10 + [90, 95])}      # 11-01..11-12
    s = verdicts.score(entries, closes, TODAY)
    # 11-02 이후 10번째 = 11-12(95), 그 다음 봉 없음 → sell pending
    assert s["signal"] == {"n": 1, "hit": 0, "skip": 1, "pending": 1}

def test_score_zero_return_is_miss():
    entries = {"outlook:A:2026-11-03": {"dir": "up", "px": 100}}
    closes = {"A": _closes("2026-11-03", [100, 100])}
    assert verdicts.score(entries, closes, TODAY)["outlook"]["hit"] == 0

def test_score_code_missing_in_closes_is_pending():
    entries = {"outlook:GONE:2026-11-03": {"dir": "up", "px": 100}}
    s = verdicts.score(entries, {}, TODAY)
    assert s["outlook"]["pending"] == 1 and s["by_code"]["GONE"]["outlook"]["pending"] == 1

def test_score_window_is_last_60_bars():
    vals = [100] * 70 + [110]
    closes = {"A": _closes("2026-08-01", vals)}        # 71봉, 마지막 2026-10-10
    dates = [d for d, _ in closes["A"]]
    old, new = dates[5], dates[-2]                      # 창 밖 / 창 안
    entries = {"outlook:A:%s" % old: {"dir": "up", "px": 90},
               "outlook:A:%s" % new: {"dir": "up", "px": 90}}
    s = verdicts.score(entries, closes, TODAY)
    assert s["outlook"]["n"] == 1 and s["outlook"]["hit"] == 1   # 창 밖 1건은 집계 안 됨

def test_score_window_falls_back_to_90_calendar_days_without_bars():
    entries = {"outlook:A:%s" % (TODAY - dt.timedelta(days=100)).isoformat(): {"dir": "up", "px": 1},
               "outlook:A:%s" % (TODAY - dt.timedelta(days=10)).isoformat(): {"dir": "up", "px": 1}}
    s = verdicts.score(entries, {}, TODAY)
    assert s["outlook"]["pending"] == 1     # 창 안 1건만 집계(pending), 창 밖은 제외
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_verdicts.py -k score -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'score'`

- [ ] **Step 3: `score` 구현**

창 기준(cutoff): 모든 `closes`의 날짜 합집합을 정렬해 뒤에서 `window_days`번째 날짜, 봉이 그보다 적으면 첫 날짜, 봉이 없으면 `today - 90일`. 키의 date < cutoff면 제외. outlook은 `date >= T`인 첫 봉 i(없으면 pending), 확정은 `i+1` 존재. signal은 `date > D`인 첫 봉 j, 대상 `j + HOLD_BARS - 1`, 확정은 `j + HOLD_BARS` 존재. `ret = close/px - 1`. 알 수 없는 `dir`은 skip. 주석에 "D 봉은 기록 시점에 부분봉이라 제외(2026-11-02 실측: 일봉 캐시는 첫 로드의 부분봉을 하루 종일 서빙)"를 남긴다.

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_verdicts.py -v`
Expected: 14 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/flow/verdicts.py tests/test_verdicts.py
git commit -m "feat(verdicts): 순수 채점 — outlook은 T 봉, signal은 10봉 뒤, 다음 봉 있어야 확정·60거래일 창"
```

---

### Task 3: 다음 개장일 — `market_status.next_trade_date`

**Files:**
- Modify: `backend/flow/market_status.py:57-68` (`next_open_sec` 옆)
- Test: `tests/test_kospitemp.py`가 아니라 **신규 `tests/test_market_status_next.py`**

**Interfaces:**
- Produces: `next_trade_date(now: datetime.datetime, open_days: Optional[dict]) -> str` (ISO date). `next_open_sec`의 날짜 걸음을 이 함수로 뽑아 `next_open_sec`가 재사용한다.
- 규칙: 개장일이고 09:00 전이면 오늘, 그 외 다음 개장일. `open_days`는 `parse_holidays` 형식(`{'YYYYMMDD': bool}`), None이면 주말만 건너뜀.

- [ ] **Step 1: 실패하는 테스트**

```python
import datetime as dt
from backend.flow import market_status as ms
from backend.flow.kst import KST

def _at(y, m, d, h):
    return dt.datetime(y, m, d, h, 0, tzinfo=KST)

def test_next_trade_date_before_open_is_today():
    assert ms.next_trade_date(_at(2026, 11, 3, 8), None) == "2026-11-03"   # 화

def test_next_trade_date_after_open_is_tomorrow():
    assert ms.next_trade_date(_at(2026, 11, 3, 18), None) == "2026-11-04"

def test_next_trade_date_skips_weekend():
    assert ms.next_trade_date(_at(2026, 11, 6, 18), None) == "2026-11-09"   # 금 → 월

def test_next_trade_date_skips_holiday_from_calendar():
    cal = {"20261104": False, "20261105": True}
    assert ms.next_trade_date(_at(2026, 11, 3, 18), cal) == "2026-11-05"

def test_next_open_sec_still_uses_same_walk():
    assert ms.next_open_sec(_at(2026, 11, 6, 18), None) == int(
        (_at(2026, 11, 9, 9) - _at(2026, 11, 6, 18)).total_seconds())
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_market_status_next.py -v`
Expected: FAIL — `AttributeError: ... 'next_trade_date'`

- [ ] **Step 3: 구현 + `next_open_sec` 리팩터**

`next_open_sec`의 `d` 걸음 블록을 `next_trade_date`로 옮기고 `next_open_sec`는 그 결과로 `target`을 만든다. 동작 불변(기존 `tests/test_widget.py` 등이 회귀 기준).

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_market_status_next.py tests/test_widget.py -q`
Expected: all passed

- [ ] **Step 5: 커밋**

```bash
git add backend/flow/market_status.py tests/test_market_status_next.py
git commit -m "refactor(market_status): next_trade_date 분리 — next_open_sec와 같은 개장일 걸음을 장부가 재사용"
```

---

### Task 4: outlook 기록 — `get_outlook_brief(ledger=True)`

**Files:**
- Modify: `backend/api/marketdata.py:677-744` (`_gather_signals`, `get_outlook`, `get_outlook_brief`)
- Modify: `backend/api/app.py:460-466` (`outlook_api`)
- Test: `tests/test_marketdata.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 `verdicts.record`, Task 3 `market_status.next_trade_date`, 기존 `market_status._get_open_days(client, now)`.
- Produces: `_gather_signals`가 `sig["px"]`(= `p["price"]`, 없으면 None)를 싣는다. `get_outlook`이 돌려주는 `o`에 `o["px"]`가 붙는다. `get_outlook_brief(codes, client=None, ledger: bool = False) -> dict` — 반환 모양 불변(`code→{direction, reason}`).
- 기록 조건: `ledger and o["session"] != "kr_open" and o.get("px")`. 키 date = `next_trade_date(kst.now(), await _get_open_days(client, kst.now()))`.

- [ ] **Step 1: 실패하는 테스트 (`tests/test_marketdata.py` 끝에)**

```python
def _outlook_env(monkeypatch, tmp_path, session):
    from backend.api import marketdata as md
    from backend.config import settings
    from backend.flow import market_status
    md._outlook_cache.clear()
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "flow_mode", "")
    async def fake_signals(code, client):
        return {"session": session, "is_semi": True, "px": 410000,
                "us": {"sox_rate": 2.1, "nasdaq_rate": 1.0, "us_open": False},
                "adr": None, "flow": None,
                "momentum": {"rate": 1.0, "overheated": False}}
    monkeypatch.setattr(md, "_gather_signals", fake_signals)
    async def no_cal(client, now):
        return None
    monkeypatch.setattr(market_status, "_get_open_days", no_cal)
    import datetime as dt
    from backend.flow import kst
    monkeypatch.setattr(kst, "now", lambda: dt.datetime(2026, 11, 6, 18, 0, tzinfo=kst.KST))  # 금 저녁
    return md

def test_outlook_brief_records_next_trade_date_for_master(monkeypatch, tmp_path):
    from backend.flow import verdicts
    md = _outlook_env(monkeypatch, tmp_path, "us_closed")
    out = asyncio.run(md.get_outlook_brief(["000660"], client=object(), ledger=True))
    assert out["000660"]["direction"] == "up"
    d = verdicts.load()
    assert list(d) == ["outlook:000660:2026-11-09"]           # 월요일
    assert d["outlook:000660:2026-11-09"]["dir"] == "up"
    assert d["outlook:000660:2026-11-09"]["px"] == 410000

def test_outlook_brief_skips_kr_open_session(monkeypatch, tmp_path):
    from backend.flow import verdicts
    md = _outlook_env(monkeypatch, tmp_path, "kr_open")
    asyncio.run(md.get_outlook_brief(["000660"], client=object(), ledger=True))
    assert verdicts.load() == {}

def test_outlook_brief_default_does_not_record(monkeypatch, tmp_path):
    from backend.flow import verdicts
    md = _outlook_env(monkeypatch, tmp_path, "us_closed")
    asyncio.run(md.get_outlook_brief(["000660"], client=object()))
    assert verdicts.load() == {} and not verdicts._path().exists()
```

`tests/test_api.py`에:

```python
def test_outlook_route_passes_ledger_flag_for_master(monkeypatch):
    from backend.api import marketdata as md
    seen = {}
    async def fake_brief(codes, client=None, ledger=False):
        seen["ledger"] = ledger
        return {}
    monkeypatch.setattr(md, "get_outlook_brief", fake_brief)
    assert client.get("/api/outlook").status_code == 200   # 인증 비활성 → default_account = 마스터
    assert seen["ledger"] is True
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_marketdata.py -k outlook_brief tests/test_api.py -k ledger -v`
Expected: FAIL — `TypeError: get_outlook_brief() got an unexpected keyword argument 'ledger'`

- [ ] **Step 3: 구현**

`_gather_signals`의 `client.price` 블록에서 `sig["px"] = p.get("price")`. `get_outlook`은 `o["px"] = sig.get("px")`. `get_outlook_brief`는 루프 안에서 조건 충족 시 `verdicts.record("outlook", c, target, o["direction"], o["px"])` — `target`은 루프 전에 한 번 계산하되 **`ledger`일 때만**(비마스터 요청에 휴장일 TR을 더 부르지 않는다). `market_status`와 `kst`는 **모듈 속성으로 호출**(`market_status._get_open_days(...)`, `kst.now()`) — 테스트가 그 지점을 갈아끼운다. `outlook_api`는 `ledger=(_req_email(request, settings) == userstore.default_account())`. `get_outlook_brief` docstring에 "장부는 마스터 계정이 본 판단만(계정 3개, 2026-11-02 결정)".

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_marketdata.py tests/test_api.py tests/test_nextday.py -q`
Expected: all passed

- [ ] **Step 5: 커밋**

```bash
git add backend/api/marketdata.py backend/api/app.py tests/test_marketdata.py tests/test_api.py
git commit -m "feat(verdicts): 내일 예상을 장부에 기록 — 마스터 계정·장중 제외·다음 개장일 키"
```

---

### Task 5: signal 기록 + 채점 — `build_dashboard(ledger=True)`

**Files:**
- Modify: `backend/cli.py:181-230` (`build_dashboard`)
- Modify: `backend/api/app.py:133-141` (`index`)
- Modify: `backend/flow/verdicts.py` (`scorecard`)
- Modify: `backend/report/dashboard.py:1011-1016` (`render_dashboard` 시그니처·`data`)
- Test: `tests/test_verdicts.py`, `tests/test_us_cards.py`(패턴 재사용, 신규 테스트는 `tests/test_verdicts_dashboard.py`)

**Interfaces:**
- Consumes: Task 1 `record`, Task 2 `score`.
- Produces: `verdicts.scorecard(frames: dict, today: Optional[datetime.date] = None, window_days: int = 60) -> Optional[dict]` — 장부가 비면 None, 아니면 `score(...)` 결과. `frames[code]`는 `Close` 열·DatetimeIndex DataFrame(NaN 행 제외해 `closes`로 변환).
- `build_dashboard(..., ledger: bool = False)`: 종목 루프에서 `len(df) > 0`이면 `record("signal", code, df.index[-1].date().isoformat(), signal.action, px, advice=signal.advice)`. `px` = `pm.get(code, {}).get("close")` 우선, 없으면 마지막 `Close`. **기록은 `pm`이 완성된 뒤**(루프를 가격 조립 뒤에 한 번 더 돈다).
- `render_dashboard(stocks, universe, date, pwa=False, scorecard=None)`: `data["scorecard"] = scorecard`.

- [ ] **Step 1: 실패하는 테스트 (`tests/test_verdicts_dashboard.py`)**

```python
import pandas as pd, pytest
from backend.config import settings
from backend.flow import verdicts

def _df(closes, start="2026-10-01"):
    idx = pd.date_range(start, periods=len(closes), freq="D")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": [1] * len(closes)}, index=idx)

@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    from backend import cli
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "flow_mode", "")
    monkeypatch.setattr(cli, "_kr_market_open", lambda: True)
    monkeypatch.setattr(cli, "_live_prices", lambda codes: {c: {"close": 999, "change": 1.0} for c in codes})
    monkeypatch.setattr(cli, "us_market_open", lambda: False)
    monkeypatch.setattr(cli, "_collect_issues", lambda codes, nm=None: {})
    monkeypatch.setattr(cli, "get_universe", lambda d: [])
    return cli, tmp_path

def test_build_dashboard_records_signal_with_live_px(cli_env):
    cli, tmp = cli_env
    src = lambda code, s, e: _df([100.0] * 80)   # noqa: E731
    cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp), source=src,
                        with_news=False, ledger=True)
    d = verdicts.load()
    key = "signal:005930:2026-12-19"                 # 마지막 봉 날짜(80일째)
    assert list(d) == [key]
    assert d[key]["px"] == 999 and d[key]["dir"] == "hold" and d[key]["advice"] is False

def test_build_dashboard_same_bar_twice_is_one_key(cli_env):
    cli, tmp = cli_env
    src = lambda code, s, e: _df([100.0] * 80)   # noqa: E731
    for _ in range(2):
        cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp), source=src,
                            with_news=False, ledger=True)
    assert len(verdicts.load()) == 1

def test_build_dashboard_default_no_ledger(cli_env):
    cli, tmp = cli_env
    cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp),
                        source=lambda c, s, e: _df([100.0] * 80), with_news=False)
    assert not verdicts._path().exists()

def test_build_dashboard_empty_frame_records_nothing_and_renders(cli_env):
    cli, tmp = cli_env
    html = cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp),
                               source=lambda c, s, e: _df([]), with_news=False, ledger=True)
    assert "관심종목 분석" in html and not verdicts._path().exists()

def test_build_dashboard_bakes_scorecard_for_master_only(cli_env):
    cli, tmp = cli_env
    # 11-05는 80봉(10-01~12-19) 중 60거래일 창(10-21~) 안이다. 11-05 종가 100 > px 90 → hit
    verdicts.record("outlook", "005930", "2026-11-05", "up", 90)
    src = lambda c, s, e: _df([100.0] * 80)   # noqa: E731
    html = cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp),
                               source=src, with_news=False, ledger=True)
    assert '"scorecard"' in html and '"hit": 1' in html
    other = cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp),
                                source=src, with_news=False)        # 비마스터 홈
    assert '"scorecard": null' in other                              # 마스터 장부 노출 금지

def test_scorecard_none_without_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    assert verdicts.scorecard({"005930": _df([1.0, 2.0])}) is None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_verdicts_dashboard.py -v`
Expected: FAIL — `TypeError: build_dashboard() got an unexpected keyword argument 'ledger'`

- [ ] **Step 3: 구현**

`build_dashboard`: 가격 조립(`pm`) 완료 뒤, `ledger`면 `signals`·`frames`·`pm`을 돌며 `record`. 그 다음 `sc = verdicts.scorecard(frames)`(ledger 여부와 무관 — 읽기는 모든 계정에 허용되지만 장부는 마스터 것뿐이므로 **`ledger`일 때만** 계산해 넘긴다; 비마스터 홈엔 마스터 적중률이 보이면 안 된다). `render_dashboard(..., scorecard=sc if ledger else None)`. `index` 라우트는 `ledger=(email == userstore.default_account())`. `scorecard`의 `closes` 변환은 `[(ts.date().isoformat(), float(c)) for ts, c in df["Close"].items() if c == c]`.

주석(cli.py 기록 지점): "px는 봉이 아니라 pm — 일봉 캐시는 첫 로드의 부분봉을 하루 종일 서빙한다(2026-11-02 실측, `PriceAdapter._covers_end`)".

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_verdicts_dashboard.py tests/test_us_cards.py tests/test_dashboard.py tests/test_api.py -q`
Expected: all passed

- [ ] **Step 5: 커밋**

```bash
git add backend/cli.py backend/api/app.py backend/flow/verdicts.py backend/report/dashboard.py tests/test_verdicts_dashboard.py
git commit -m "feat(verdicts): 매매 판정 기록(마지막 봉 날짜 키·KIS 현재가 px) + 홈 렌더에 scorecard 베이크"
```

---

### Task 6: 화면 — 헤더 한 줄 + 카드 한 줄

**Files:**
- Modify: `backend/report/dashboard.py:286` (grouphd `seccap`), `:341` 근처(카드 `.cnd` 옆), JS 하단(`loadOutlook` 근처)
- Modify: `backend/report/theme.py` (`.sc-good{color:var(--good)}`, `.sc-bad{color:var(--down)}`, `.sc-flat{color:var(--text-2)}`, `.sc{font-family:var(--font-num)}`)
- Test: `tests/test_dashboard.py`, `tests/test_theme.py`(토큰 존재 확인이 있으면 그 패턴)

**Interfaces:**
- Consumes: `D.scorecard` (Task 5 모양: `{outlook: B, signal: B, by_code: {code: {outlook: B, signal: B}}}`, 또는 null).
- Produces: `dashboard.py` 모듈 상수 `SCORECARD_JS` — 순수 함수 `scText(sc)`가
  `{head: string|null, tone: "good"|"bad"|"flat", cards: {code: string}}`를 돌려준다(DOM 접근 없음 —
  `AGO_JS`처럼 node로 실행 테스트). 템플릿의 `renderScorecard()`가 이걸 DOM에 붙인다.
- 문구(정확히):
  - 헤더: `내일예상 적중 {hit}/{n} · 매매판정 {hit}/{n} (10일) · 중립 {skip}` — 각 묶음은 `n ≥ 10`이면 비율 톤 클래스(≥55% `sc-good`, ≤45% `sc-bad`, 그 외 `sc-flat`), `n < 10`이면 `내일예상 표본 부족 ({n}/10)`로 바꾸고 `sc-flat`. `중립`은 outlook의 skip. signal의 `n == 0 && skip == 0`이면 그 묶음 생략.
  - 카드(국내만): `.cnd` 아래 `<div class="sc scc" data-code>`에 `예상 적중 {hit}/{n}` + (`pending > 0`이면 ` · 대기 {pending}`). `n + pending == 0`이면 비움.
  - `D.scorecard`가 null이면 헤더 `seccap`은 기존 `차트·뉴스·공시` 그대로, 카드 줄 없음.

- [ ] **Step 1: 실패하는 테스트**

`tests/test_scorecard_js.py` (신규, `tests/test_ago_js.py`의 node 패턴 그대로):

```python
import json, os, shutil, subprocess
import pytest
from backend.report.dashboard import SCORECARD_JS

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node 미설치")

def _b(**kw):
    return dict({"n": 0, "hit": 0, "skip": 0, "pending": 0}, **kw)

def _run(tmp_path, sc):
    js = tmp_path / "sc.js"
    js.write_text(SCORECARD_JS + "\nconsole.log(JSON.stringify(scText(%s)));" % json.dumps(sc),
                  encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)

@needs_node
def test_sctext_full_sample(tmp_path):
    out = _run(tmp_path, {"outlook": _b(n=30, hit=17, skip=12), "signal": _b(n=5, hit=3),
                          "by_code": {"005930": {"outlook": _b(n=9, hit=6, pending=1), "signal": _b()}}})
    assert out["head"] == "내일예상 적중 17/30 · 매매판정 3/5 (10일) · 중립 12"
    assert out["tone"] == "good"                       # 17/30 = 56.7% ≥ 55%
    assert out["cards"] == {"005930": "예상 적중 6/9 · 대기 1"}

@needs_node
@pytest.mark.parametrize("hit,n,tone", [(13, 30, "bad"), (15, 30, "flat"), (17, 30, "good")])
def test_sctext_tone_thresholds(tmp_path, hit, n, tone):
    out = _run(tmp_path, {"outlook": _b(n=n, hit=hit), "signal": _b(), "by_code": {}})
    assert out["tone"] == tone

@needs_node
def test_sctext_small_sample_and_empty_parts(tmp_path):
    out = _run(tmp_path, {"outlook": _b(n=4, hit=3), "signal": _b(),
                          "by_code": {"005930": {"outlook": _b(), "signal": _b()}}})
    assert out["head"] == "내일예상 표본 부족 (4/10)" and out["tone"] == "flat"
    assert out["cards"] == {"005930": ""}             # n+pending == 0 → 비움

@needs_node
def test_sctext_null(tmp_path):
    assert _run(tmp_path, None)["head"] is None
```

`tests/test_dashboard.py` 끝에:

```python
def test_scorecard_markup_present_only_with_data():
    sc = {"outlook": {"n": 30, "hit": 17, "skip": 0, "pending": 0},
          "signal": {"n": 0, "hit": 0, "skip": 0, "pending": 0}, "by_code": {}}
    with_ = render_dashboard([_stock()], [], "2026-11-02", scorecard=sc)
    without = render_dashboard([_stock()], [], "2026-11-02")
    assert 'id="sc-head"' in with_ and "renderScorecard" in with_ and '"scorecard": {' in with_
    assert '"scorecard": null' in without and "차트·뉴스·공시" in without
    for cls in (".sc-good", ".sc-bad", ".sc-flat"):
        assert cls in with_                              # theme.py 경유
```

- [ ] **Step 1b: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_scorecard_js.py tests/test_dashboard.py -k "sctext or scorecard" -v`
Expected: FAIL — `ImportError: cannot import name 'SCORECARD_JS'`

- [ ] **Step 2: 구현**

`theme.py`에 `.sc{font-family:var(--font-num)}`, `.sc-good{color:var(--good)}`, `.sc-bad{color:var(--down)}`, `.sc-flat{color:var(--text-2)}`(색은 토큰만). `dashboard.py`: `SCORECARD_JS` 상수(`scText` 순수 함수, 문구 규칙은 Interfaces 그대로; `MIN_SAMPLE`·`HOLD_BARS` 숫자는 JS에 리터럴 10으로 — `verdicts.MIN_SAMPLE`과 같아야 한다는 주석), 템플릿에 `__SCORECARD_JS__` 자리표시자(**`__LIB__`·`__DATA__`보다 앞에** 치환 — 치환 순서 주석 참조), `seccap`에 `id="sc-head"`, `cardHtml`에 `if(!isUS) h+='<div class="sc scc" data-code="…"></div>'`, `renderScorecard()`는 `scText(D.scorecard)`를 DOM에 붙이고 `tone`을 `sc-` 클래스로 단다. `cards.innerHTML = …` 직후 한 번 호출.

- [ ] **Step 3: 통과 + 실렌더**

Run: `.venv/bin/python -m pytest tests/test_scorecard_js.py tests/test_dashboard.py tests/test_theme.py -q && make verify`
Expected: all passed · verify가 6화면 라이트·다크 캡처, 가로 오버플로 0. `harness/artifacts/dashboard-light.png`를 열어 헤더 줄이 390px에서 한 줄 또는 자연 줄바꿈으로 보이는지 눈으로 확인(장부가 없으면 기본 캡션이 보이는 게 정상 — 하네스 데모는 `demo`라 장부를 쓰지 않는다. 확인용으로 tmp 장부를 만들지 말 것).

- [ ] **Step 4: 커밋**

```bash
git add backend/report/dashboard.py backend/report/theme.py tests/test_dashboard.py tests/test_scorecard_js.py
git commit -m "feat(home): 판정 적중률 — 관심종목 분석 헤더 한 줄 + 국내 카드 예상 적중"
```

---

### Task 7: 마무리 — 전체 검증·문서

**Files:**
- Modify: `README.md`(화면 `/` 목록 "관심종목 분석" 항목에 한 줄, 알려진 한계 1번에 "적중률은 장부로 측정한다" 보강), `.gitignore` 확인(`data/`는 이미 무시).

- [ ] **Step 1: 전체 테스트**

Run: `make test && make eval`
Expected: 모두 통과. `eval`은 판정 문구 골든이라 이 작업으로 바뀌면 안 된다(바뀌면 버그).

- [ ] **Step 2: README 반영 후 커밋**

```bash
git add README.md
git commit -m "docs: 판정 장부·적중률 — 홈 화면 목록과 알려진 한계에 반영"
```

- [ ] **Step 3: 배포 메모(실행 아님)**

8000 재기동은 **마스터 확인 후** `.venv/bin/python`으로. 재기동 전까지 장부는 쌓이지 않는다. 포트폴리오 줄·텔레그램 알림과 묶어 한 번에.
