# 아이폰 홈 위젯(Scriptable) + 편집 가능 관심종목 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 아이폰 홈 화면 위젯(Scriptable)이 `/api/widget`(Bearer 토큰, KIS 단일 소스)을 읽어 관심종목 시세를 표시하고, 관심종목은 대시보드에서 편집해 앱·위젯·MCP·리포트에 일괄 반영된다.

**Architecture:** 인증은 AuthGate 안의 Bearer 검사(공개 예외 아님 — "모든 경로 잠금" 불변식 유지). 시세는 시간대 불문 KIS `price()`, 거래일은 FHKST01010400 1회 조회로 판별(공휴일 자동 해소). 토큰은 `SM_WIDGET_TOKEN` env 단일 + 아이폰 Keychain. 관심종목은 `watchlist.json` + `get_watchlist()` 단일 접근자(소비자 5곳).

**Tech Stack:** FastAPI + 순수 ASGI 게이트, KIS OpenAPI(httpx), Scriptable(JS), pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-iphone-widget-design.md` (커밋 a519f50 + 1f9b1f8)

## Global Constraints

- **Python 3.9 호환** (실서버 시스템 3.9): `match`문·`X | Y` 타입 힌트 금지, `Optional[...]` 사용.
- **"모든 경로가 실제로 잠겼는가"** 불변식: 새 라우트는 반드시 `tests/test_auth.py`의 `PROTECTED`에 추가. `/api/widget`은 무토큰 401이므로 **예외 없이** 추가된다.
- **자기완결 HTML**: 외부 CDN/폰트 0. 페이지 스타일은 `backend/report/dashboard.py`의 `_BASE_CSS`/`_PWA_HEAD` 재사용(scanner_page.py 패턴).
- **테스트는 KIS 키 없이 통과**해야 함(CI/타 기기). KIS 실측은 별도 수동 스텝으로 분리.
- **pydantic Settings는 `.env`를 자동 로드**함(`env_file=".env"`) — 테스트에서 "미설정" 시나리오는 반드시 `widget_token=None`을 **명시적으로** 전달(마스터 실기기 .env 오염 방지).
- 응답 계약(화이트리스트): `/api/widget`은 `open/trade_date/fetched_at/refresh_after_sec/items[{code,name,price,change}]` 외 필드 **추가 금지**.
- 테스트 실행: `.venv/bin/python -m pytest tests/ -x -q` (프로젝트 루트에서).
- 커밋 메시지: 기존 관례(한국어 conventional commits, `feat(widget): ...` 등).

## File Structure

| 파일 | 역할 | 생성/수정 |
|---|---|---|
| `backend/config.py` | `widget_token` 설정 추가 | 수정 |
| `backend/flow/kis.py` | `parse_latest_trade_date` + `KisClient.latest_trade_date` | 수정 |
| `backend/flow/market_status.py` | 장 상태/거래일/refresh_after_sec 판정(순수 함수 + TTL 캐시) | **생성** |
| `backend/api/widget.py` | 위젯 응답 조립(KIS 단일 소스, 부분 실패 null, universe 폴백) | **생성** |
| `backend/api/auth.py` | AuthGate에 `/api/widget` Bearer 검사 | 수정 |
| `backend/api/app.py` | `/api/widget`·`/widget-setup` 라우트, 토큰 fail-closed, (2단계) watchlist 전환 | 수정 |
| `backend/report/widget_setup.py` | 설치 페이지 + Scriptable 스크립트 템플릿 | **생성** |
| `docs/widget-guide.md` | 마스터용 설치·사용 가이드 | **생성** |
| `backend/flow/watchlist.py` | 관심종목 저장소(`get_watchlist`/`set_watchlist`, MAX 10) | **생성** |
| `backend/market/universe.py` | `get_cached`(stale 읽기 전용) + `name_map` | 수정 |
| `backend/news/names.py` | `resolve_name(code, names)` — universe 우선, 하드코딩 폴백 | 수정 |
| `backend/report/dashboard.py` | `assemble_stock(names=)` + 편집 UI(＋추가/－삭제) | 수정 |
| `backend/cli.py` | `_news_aliases` 헬퍼, `fetch_live_prices` 세마포어, report→get_watchlist | 수정 |
| `backend/mcp/tools.py` | watchlist 소비자 전환 | 수정 |
| `tests/test_widget.py` | 위젯 조립·계약·market_status | **생성** |
| `tests/test_widget_setup.py` | 설치 페이지·스크립트(node --check) | **생성** |
| `tests/test_watchlist.py` | 저장소 검증·원자성·폴백 | **생성** |
| `tests/test_auth.py` | PROTECTED 추가 + Bearer 3종(유효 200급/불일치 401/미설정 503) | 수정 |

---

# 1단계 — 위젯 (현 관심종목으로 먼저 배송)

### Task 1: `SM_WIDGET_TOKEN` 설정 + fail-closed 기동 검증

**Files:**
- Modify: `backend/config.py` (67행 `cookie_secure` 아래)
- Modify: `backend/api/app.py:53-57` (`create_app` 초입)
- Test: `tests/test_widget.py` (신규)

**Interfaces:**
- Produces: `settings.widget_token: Optional[str]` — 이후 모든 태스크가 사용.
- Produces: `create_app`이 토큰 20자 미만 시 `RuntimeError` (fail-closed).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_widget.py
"""아이폰 위젯 — 토큰 설정·데이터 조립·응답 계약(화이트리스트).

설계: docs/superpowers/specs/2026-07-16-iphone-widget-design.md
⚠ Settings는 .env를 자동 로드하므로 '미설정' 시나리오는 widget_token=None을 명시한다.
"""
import pytest

from backend.config import Settings

TOKEN = "w" * 32   # 유효 토큰(20자 이상)


def _settings(tmp_path, **over):
    base = dict(cache_dir=str(tmp_path), flow_mode="demo",
                widget_token=TOKEN, kis_app_key=None, kis_app_secret=None,
                dart_api_key=None)
    base.update(over)
    return Settings(**base)


def test_short_widget_token_refuses_boot(tmp_path):
    """약한 토큰이 유일 방어선이 되는 것을 차단 — 20자 미만이면 기동 거부(fail-closed)."""
    from backend.api.app import create_app
    with pytest.raises(RuntimeError):
        create_app(_settings(tmp_path, widget_token="short"))


def test_valid_or_absent_widget_token_boots(tmp_path):
    from backend.api.app import create_app
    create_app(_settings(tmp_path))                       # 32자 → OK
    create_app(_settings(tmp_path, widget_token=None))    # 미설정 → OK(위젯만 꺼짐)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_widget.py -x -q`
Expected: FAIL — `Settings`에 `widget_token` 필드 없음(ValidationError 아님 — extra ignore라 무시됨 → `create_app`이 RuntimeError를 안 던져 `Failed: DID NOT RAISE`).

- [ ] **Step 3: 구현**

`backend/config.py` — `cookie_secure` 줄(67행) 아래에 추가:

```python
    # 아이폰 위젯(Scriptable) 읽기 토큰 — env 단일 경로(캐시파일 자동생성 금지:
    # env를 지우면 조용히 재생성돼 위젯만 영문 모를 401 — 설계 2026-07-16).
    # 생성: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
    widget_token: Optional[str] = None         # SM_WIDGET_TOKEN
```

`backend/api/app.py` — `create_app` 초입, `settings = settings if ...` 바로 아래에 추가:

```python
    # 위젯 토큰 fail-closed — 약한 토큰(짧은 문자열)이 공개 Funnel의 유일 방어선이
    # 되는 것을 기동 시점에 차단(auth.install의 fail-closed와 같은 철학).
    if settings.widget_token and len(settings.widget_token) < 20:
        raise RuntimeError(
            "SM_WIDGET_TOKEN이 너무 짧습니다(최소 20자) — "
            'python3 -c "import secrets; print(secrets.token_urlsafe(32))" 로 생성하세요')
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_widget.py -x -q`
Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/config.py backend/api/app.py tests/test_widget.py
git commit -m "feat(widget): SM_WIDGET_TOKEN 설정 + 20자 미만 기동 거부(fail-closed)"
```

---

### Task 2: 거래일 판별 — KIS 일자별 TR + `market_status` 모듈

**Files:**
- Modify: `backend/flow/kis.py` (parse 함수는 `parse_price` 아래, 클라이언트 메서드는 `price()` 아래)
- Create: `backend/flow/market_status.py`
- Test: `tests/test_widget.py` (추가)

**Interfaces:**
- Consumes: `kst.now()`, `kst.KST` (`backend/flow/kst.py`), `KisClient._get`.
- Produces: `parse_latest_trade_date(js) -> Optional[str]` ('YYYY-MM-DD').
- Produces: `KisClient.latest_trade_date(code="005930") -> Optional[str]` (async).
- Produces: `market_status.get_status(client=None, now=None) -> dict` = `{"open": bool, "trade_date": str, "refresh_after_sec": int}` (async). client=None이면 TR 생략(벽시계 폴백).
- Produces: 순수 함수 `wallclock_open(now)`, `next_open_sec(now)`, `refresh_after_sec(open_, now)`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_widget.py`에 추가

```python
# ── 거래일/장 상태 판정 ────────────────────────────────────────────
import asyncio
import datetime as dt

from backend.flow.kst import KST


def _kst(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=KST)


def test_parse_latest_trade_date():
    from backend.flow.kis import parse_latest_trade_date
    js = {"rt_cd": "0", "output": [{"stck_bsop_date": "20260716"},
                                   {"stck_bsop_date": "20260715"}]}
    assert parse_latest_trade_date(js) == "2026-07-16"
    assert parse_latest_trade_date({"rt_cd": "1"}) is None
    assert parse_latest_trade_date({"rt_cd": "0", "output": []}) is None
    assert parse_latest_trade_date({"rt_cd": "0", "output": [{"stck_bsop_date": "bad"}]}) is None


def test_wallclock_open_hours_and_weekend():
    from backend.flow import market_status as ms
    assert ms.wallclock_open(_kst(2026, 7, 16, 10, 30)) is True    # 목 장중
    assert ms.wallclock_open(_kst(2026, 7, 16, 8, 59)) is False    # 장전
    assert ms.wallclock_open(_kst(2026, 7, 16, 15, 31)) is False   # 장후
    assert ms.wallclock_open(_kst(2026, 7, 18, 10, 0)) is False    # 토


def test_refresh_after_sec_open_vs_closed():
    from backend.flow import market_status as ms
    assert ms.refresh_after_sec(True, _kst(2026, 7, 16, 10, 0)) == 900
    # 목 16:00 → 금 09:00 = 17시간 = 61200초 → 6h 캡
    assert ms.refresh_after_sec(False, _kst(2026, 7, 16, 16, 0)) == 21600
    # 금 08:00 → 당일 09:00 = 3600초(캡 미달)
    assert ms.refresh_after_sec(False, _kst(2026, 7, 17, 8, 0)) == 3600


class _FakeClient:
    def __init__(self, td):
        self._td = td

    async def latest_trade_date(self, code="005930"):
        return self._td


def test_get_status_holiday_demotes_open(monkeypatch):
    """평일 공휴일: 벽시계는 장중이지만 KIS 최신 거래일 ≠ 오늘 → open:false 강등."""
    from backend.flow import market_status as ms
    monkeypatch.setattr(ms, "_cache", {"ts": 0.0, "trade_date": None})
    now = _kst(2026, 7, 16, 10, 0)                       # 목요일 장중(공휴일 가정)
    st = asyncio.run(
        ms.get_status(_FakeClient("2026-07-15"), now=now))
    assert st["open"] is False and st["trade_date"] == "2026-07-15"


def test_get_status_trading_day_open(monkeypatch):
    from backend.flow import market_status as ms
    monkeypatch.setattr(ms, "_cache", {"ts": 0.0, "trade_date": None})
    now = _kst(2026, 7, 16, 10, 0)
    st = asyncio.run(
        ms.get_status(_FakeClient("2026-07-16"), now=now))
    assert st["open"] is True and st["refresh_after_sec"] == 900


def test_get_status_without_client_falls_back_to_wallclock(monkeypatch):
    """TR 불가(키 없음) 폴백 — 주말엔 직전 금요일을 거래일로 추정."""
    from backend.flow import market_status as ms
    monkeypatch.setattr(ms, "_cache", {"ts": 0.0, "trade_date": None})
    st = asyncio.run(
        ms.get_status(None, now=_kst(2026, 7, 18, 10, 0)))          # 토요일
    assert st["open"] is False and st["trade_date"] == "2026-07-17"  # 금요일
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_widget.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'parse_latest_trade_date'`

- [ ] **Step 3: kis.py 구현** — `parse_price` 함수(223-232행) 바로 아래에 추가:

```python
def parse_latest_trade_date(js: dict):
    """FHKST01010400(일자별 시세) output 첫 행 stck_bsop_date → 'YYYY-MM-DD'.

    위젯의 open/asof 판정용 — 최신 행이 곧 최신 거래일이다(공휴일이면 전 거래일).
    형식 불량/실패는 None(호출부가 벽시계로 폴백)."""
    if js.get("rt_cd") != "0":
        return None
    rows = js.get("output") or []
    d = str((rows[0] if rows else {}).get("stck_bsop_date") or "")
    if len(d) != 8 or not d.isdigit():
        return None
    return "%s-%s-%s" % (d[:4], d[4:6], d[6:])
```

`KisClient.price()` 메서드(350-354행) 바로 아래에 추가:

```python
    async def latest_trade_date(self, code: str = "005930"):
        """최신 거래일(YYYY-MM-DD) — 일자별 시세 첫 행. 위젯 장상태 판정용.

        div는 J 고정: 거래일은 거래소 공통이고 이 TR의 UN 지원이 불확실(실측 전 안전값)."""
        js = await self._get("/uapi/domestic-stock/v1/quotations/inquire-daily-price",
                             "FHKST01010400",
                             {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                              "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"})
        return parse_latest_trade_date(js)
```

- [ ] **Step 4: market_status.py 구현** — 파일 전체 생성:

```python
from __future__ import annotations

"""위젯용 장 상태/거래일 판정 — KIS 일자별 TR 1회(TTL 캐시) + KST 벽시계.

open = 벽시계 장중 AND 최신 거래일 == 오늘. 평일 공휴일(연 10일+)에 벽시계만으로
'장중' 오표시가 나는 문제를 휴장일 캘린더 없이 해소한다(설계 §거래일 판별).
TR 실패/키 없음은 벽시계 단독 폴백(공휴일 한정 부정확 허용 — 고지된 제약).
Python 3.9 호환."""

import datetime as dt
import time

from backend.flow import kst

_TTL_OPEN, _TTL_CLOSED = 600.0, 3600.0      # TR 캐시: 장중 10분 / 장외 60분
_REFRESH_OPEN, _REFRESH_CAP = 900, 21600    # 위젯 갱신 힌트: 장중 15분 / 장외 6h 캡
_cache = {"ts": 0.0, "trade_date": None}


def wallclock_open(now=None) -> bool:
    """주말·시간대만 보는 벽시계 장중(09:00~15:30 KST). 공휴일은 모른다(cli._kr_market_open과
    동일 정의 — cli는 대시보드 폴링용이라 의존을 만들지 않고 여기 재정의)."""
    now = now or kst.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 <= hm <= 15 * 60 + 30


def next_open_sec(now=None) -> int:
    """다음 평일 09:00 KST까지 남은 초(공휴일 무시 — 깨어나면 open:false로 다시 잠듦)."""
    now = now or kst.now()
    d = now.date()
    if not (now.weekday() < 5 and now.hour < 9):
        d += dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
    target = dt.datetime.combine(d, dt.time(9, 0), tzinfo=kst.KST)
    return max(60, int((target - now).total_seconds()))


def refresh_after_sec(open_: bool, now=None) -> int:
    """위젯 갱신 힌트 — 장중 900초, 장외 min(다음 개장까지, 6h 캡)."""
    return _REFRESH_OPEN if open_ else min(next_open_sec(now), _REFRESH_CAP)


def _estimate_trade_date(now) -> str:
    """TR 폴백 — 평일 09시 이후는 오늘, 그 외(장전·주말)는 직전 평일. 공휴일은 모른다."""
    d = now.date()
    if now.weekday() < 5 and now.hour >= 9:
        return d.isoformat()
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


async def get_status(client=None, now=None) -> dict:
    """{'open','trade_date','refresh_after_sec'} — /api/widget 조립용.

    client는 KisClient(없으면 TR 생략). TR 결과는 모듈 캐시에 TTL 보관 —
    위젯 요청마다 KIS를 두드리지 않는다."""
    now = now or kst.now()
    wall = wallclock_open(now)
    ttl = _TTL_OPEN if wall else _TTL_CLOSED
    if time.time() - _cache["ts"] > ttl:
        td = None
        if client is not None:
            try:
                td = await client.latest_trade_date()
            except Exception:
                td = None
        _cache["ts"], _cache["trade_date"] = time.time(), td
    td = _cache["trade_date"]
    open_ = wall and (td is None or td == now.date().isoformat())
    return {"open": open_,
            "trade_date": td or _estimate_trade_date(now),
            "refresh_after_sec": refresh_after_sec(open_, now)}
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_widget.py tests/test_flow_parse.py -q`
Expected: 전부 passed (기존 kis 파스 테스트 회귀 없음)

- [ ] **Step 6: 커밋**

```bash
git add backend/flow/kis.py backend/flow/market_status.py tests/test_widget.py
git commit -m "feat(widget): 거래일 판별 — KIS 일자별 TR + market_status(공휴일 open 오표시 자동 해소)"
```

---

### Task 3: `/api/widget` 데이터 조립 + 라우트

**Files:**
- Create: `backend/api/widget.py`
- Modify: `backend/market/universe.py` (get_cached 추가, `price_map` 아래)
- Modify: `backend/api/app.py` (`/api/prices` 라우트 아래에 라우트 추가)
- Test: `tests/test_widget.py` (추가)

**Interfaces:**
- Consumes: `market_status.get_status(client)`, `candles._get_client()`, `display_name`, `kst.now()`.
- Produces: `widget_data(codes) -> Optional[dict]` (async) — None이면 라우트가 503.
- Produces: `universe.get_cached(cache_dir=None) -> list` — 나이 무시 캐시 읽기 전용.
- Produces: `GET /api/widget` — 인증 코드 0줄(Task 4의 게이트가 담당).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_widget.py`에 추가

```python
# ── /api/widget 데이터 조립 · 응답 계약 ───────────────────────────
import json as _json
import os

CONTRACT_KEYS = {"open", "trade_date", "fetched_at", "refresh_after_sec", "items"}
ITEM_KEYS = {"code", "name", "price", "change"}


def _seed_universe(cache_dir, rows):
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "universe_v2.json"), "w", encoding="utf-8") as f:
        _json.dump(rows, f, ensure_ascii=False)


def test_widget_data_contract_whitelist(tmp_path, monkeypatch):
    """응답 필드는 화이트리스트 그대로 — 감시선·조언 등 유입 시 여기가 먼저 깨진다."""
    from backend.config import settings
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)    # KIS 없음 → universe 폴백 경로
    _seed_universe(str(tmp_path), [
        {"code": "005930", "name": "삼성전자", "close": 71200.0, "change": 1.25}])
    d = asyncio.run(widget_data(["005930", "000660"]))
    assert set(d.keys()) == CONTRACT_KEYS
    assert all(set(i.keys()) == ITEM_KEYS for i in d["items"])
    assert d["items"][0]["price"] == 71200.0
    assert d["items"][1]["price"] is None                 # 캐시에 없는 종목 = null(행 유지)


def test_widget_data_none_when_no_source(tmp_path, monkeypatch):
    """KIS 없음 + 캐시 없음 → None(라우트 503) — 조용한 빈 위젯 금지."""
    from backend.config import settings
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    assert asyncio.run(widget_data(["005930"])) is None


def test_widget_api_route_503_without_source(tmp_path, monkeypatch):
    """auth 비활성(로컬) 라우트 스모크 — 소스 없음이면 503 + 사용자 메시지.

    ⚠ widget_data는 전역 settings를 읽는다(create_app 주입과 별개) — 마스터
    실기기 .env의 실제 KIS 키로 라이브 호출이 나가지 않게 전역을 격리한다."""
    from fastapi.testclient import TestClient
    from backend.config import settings
    from backend.api.app import create_app
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    c = TestClient(create_app(_settings(tmp_path)))
    r = c.get("/api/widget")
    assert r.status_code == 503 and "error" in r.json()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_widget.py -x -q`
Expected: FAIL — `ModuleNotFoundError: backend.api.widget`

- [ ] **Step 3: universe.get_cached 구현** — `backend/market/universe.py`의 `price_map` 위에 추가:

```python
def get_cached(cache_dir=None) -> list:
    """캐시 파일만 읽는다(나이 무시·수집 트리거 없음) — 위젯 폴백/이름 조회 전용.

    위젯 요청은 어떤 경우에도 FDR 동기 스크랩을 대기하지 않는다(설계 불변식:
    수 초짜리 수집이 iOS 위젯 시간예산을 태우고 sync 함수가 이벤트루프를 멈춤)."""
    cache_dir = cache_dir or settings.cache_dir
    return _read_cache(_cache_path(cache_dir), check_age=False) or []
```

- [ ] **Step 4: widget.py 구현** — 파일 전체 생성:

```python
from __future__ import annotations

"""위젯 데이터 조립 — KIS 단일 소스(시간대 불문), 실패 종목은 price:null 유지.

응답 계약(설계 §응답 계약, 화이트리스트): open/trade_date/fetched_at/
refresh_after_sec/items[{code,name,price,change}] — 이외 필드 추가 금지.
이 엔드포인트는 세션·2FA 없이 정적 토큰 하나로 열리는 표면이므로 감시선
(절대선·예약매도 = 실매매 의도)·조언·계좌성 정보는 절대 싣지 않는다.
Python 3.9 호환."""

import asyncio

from backend.config import settings
from backend.flow import kst, market_status
from backend.market import universe as _universe
from backend.news.names import display_name

_SEM = 5   # KIS 동시 호출 상한 — 연속 호출 간헐 500 완화(kis.py 실측 주석)


async def widget_data(codes):
    """위젯 응답 dict — KIS 불가/전멸 + 캐시 없음이면 None(라우트가 503).

    부분 실패는 행을 빼지 않고 price:null로 유지(조용한 누락 금지 — 위젯이 '—' 표시)."""
    client = None
    if settings.kis_app_key:
        try:
            from backend.flow.candles import _get_client
            client = _get_client()
        except Exception:
            client = None

    prices = {}
    if client is not None:
        sem = asyncio.Semaphore(_SEM)

        async def one(c):
            async with sem:
                try:
                    p = await client.price(c)
                except Exception:
                    return c, None
            if p and p.get("price"):
                return c, {"price": p["price"], "change": p.get("rate")}
            return c, None

        prices = dict(await asyncio.gather(*[one(c) for c in codes]))

    if not any(v is not None for v in prices.values()):
        # 폴백: universe 캐시 stale 읽기 전용(설계 — KIS 실패 시에만, 수집 트리거 금지)
        pm = _universe.price_map(_universe.get_cached())
        prices = {c: ({"price": pm[c]["close"], "change": pm[c]["change"]}
                      if c in pm and pm[c].get("close") is not None else None)
                  for c in codes}
        if not any(v is not None for v in prices.values()):
            return None

    st = await market_status.get_status(client)
    items = [{"code": c, "name": display_name(c),
              "price": (prices.get(c) or {}).get("price"),
              "change": (prices.get(c) or {}).get("change")} for c in codes]
    return {"open": st["open"], "trade_date": st["trade_date"],
            "fetched_at": kst.now().isoformat(timespec="seconds"),
            "refresh_after_sec": st["refresh_after_sec"], "items": items}
```

- [ ] **Step 5: 라우트 추가** — `backend/api/app.py`의 `/api/prices` 라우트 바로 아래:

```python
    @app.get("/api/widget")
    async def widget_api():
        """아이폰 위젯 시세 — 인증은 AuthGate(Bearer)가 이미 끝냄(핸들러 인증 코드 0줄).
        KIS 단일 소스, 장외에도 직전 세션 종가+등락률(설계 2026-07-16)."""
        from backend.api.widget import widget_data
        data = await widget_data(settings.watchlist)
        if data is None:
            return JSONResponse({"error": "시세를 가져올 수 없어요 (KIS 키 또는 캐시 필요)"},
                                status_code=503)
        return JSONResponse(data)
```

- [ ] **Step 6: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_widget.py tests/test_universe.py -q`
Expected: 전부 passed

- [ ] **Step 7: 커밋**

```bash
git add backend/api/widget.py backend/market/universe.py backend/api/app.py tests/test_widget.py
git commit -m "feat(widget): /api/widget — KIS 단일 소스·부분실패 null·universe stale 폴백·계약 화이트리스트"
```

---

### Task 4: AuthGate 안의 Bearer 검사 (공개 예외 아님)

**Files:**
- Modify: `backend/api/auth.py` (`AuthGate.__init__`·`__call__`(106-120행), `install`(162행))
- Test: `tests/test_auth.py` (PROTECTED 99-101행, `_auth_settings` 79-88행)

**Interfaces:**
- Consumes: `settings.widget_token` (Task 1).
- Produces: `AuthGate(app, widget_token=None)` — Starlette `add_middleware` 키워드 전달.
- Produces: `/api/widget` 무토큰 401(기존 게이트와 동일 본문) · 불일치 401 · 미설정 503 · 유효 통과.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_auth.py` 수정

`_auth_settings`의 `base` dict에 한 줄 추가(88행 `flow_mode="demo"` 뒤):

```python
               flow_mode="demo", widget_token="w" * 32)
```

`PROTECTED` 리스트(99-101행)에 두 경로 추가 — **예외 없이**(무토큰 /api/widget = 401, /widget-setup = 302):

```python
PROTECTED = ["/", "/live/000660", "/api/live/000660/stream",
             "/api/candles/000660", "/scanner", "/api/scanner", "/api/semi",
             "/api/watch/000660", "/api/widget", "/widget-setup"]
```

파일 끝에 Bearer 테스트 3종 추가:

```python
# ── 위젯 Bearer (게이트 안의 두 번째 잠금 — 공개 예외 아님, 설계 2026-07-16) ──
def test_widget_bearer_valid_token_passes_gate(tmp_path, monkeypatch):
    """유효 토큰은 게이트 통과 — 핸들러 도달(데이터 없음 503이지 게이트 401이 아님).
    전역 settings 격리 — 실기기 .env의 KIS 키로 라이브 호출 방지(결정적 503)."""
    from backend.config import settings as _gs
    monkeypatch.setattr(_gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(_gs, "kis_app_key", None)
    c = _client(_auth_settings(tmp_path))
    r = c.get("/api/widget", headers={"Authorization": "Bearer " + "w" * 32})
    assert r.status_code == 503                    # 테스트 환경: KIS/캐시 없음 → 핸들러 503
    assert r.json()["error"] != "unauthorized"     # 게이트가 아니라 핸들러의 응답


def test_widget_bearer_wrong_token_401(tmp_path):
    c = _client(_auth_settings(tmp_path))
    r = c.get("/api/widget", headers={"Authorization": "Bearer wrong-token-1234567890"})
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}   # 본문으로 실패 사유 구분 금지


def test_widget_token_unset_503_fail_closed(tmp_path):
    """SM_WIDGET_TOKEN 미설정 → 게이트가 503(기능 꺼짐) — 401과 구분, 핸들러 미도달."""
    c = _client(_auth_settings(tmp_path, widget_token=None))
    assert c.get("/api/widget").status_code == 503
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_auth.py -q`
Expected: FAIL 2건 — 기존 세션 게이트가 `/api/`를 일괄 401 처리하므로 PROTECTED의 `/api/widget`·wrong-token 401은 **이미 통과**한다. 실패하는 것은 `test_widget_bearer_valid_token_passes_gate`(게이트 401 ≠ 503)와 `test_widget_token_unset_503_fail_closed`(401 ≠ 503). (`/widget-setup`은 라우트 없어도 게이트가 먼저 302 → 통과)

- [ ] **Step 3: 구현** — `backend/api/auth.py`

`AuthGate.__init__`(111-112행)을 교체:

```python
    def __init__(self, app, widget_token=None):
        self.app = app
        self.widget_token = widget_token   # /api/widget 전용 Bearer(설계 2026-07-16)
```

`AuthGate.__call__`(114-120행)을 교체:

```python
    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path == "/api/widget":
            # 위젯: 세션 대신 Bearer — 공개 예외가 아니라 게이트 안의 두 번째 잠금.
            # 무토큰이 여전히 401이므로 PROTECTED 불변식 테스트에 예외가 없다.
            resp = self._widget_blocked(scope)
        else:
            resp = self._blocked(path, scope.get("session") or {})
        if resp is None:
            return await self.app(scope, receive, send)
        return await resp(scope, receive, send)
```

`_blocked` 아래에 메서드 추가:

```python
    def _widget_blocked(self, scope):
        """Bearer 토큰 검사 — 유효하면 None(통과). 미설정 503(fail-closed),
        그 외 전부 동일한 401 본문(실패 사유로 정보 누출 금지)."""
        import secrets as _secrets_mod
        from starlette.responses import JSONResponse
        if not self.widget_token:
            return JSONResponse({"error": "widget not configured"}, status_code=503)
        auth = b""
        for k, v in scope.get("headers") or ():
            if k == b"authorization":
                auth = v
                break
        token = auth.decode("latin-1")[7:] if auth[:7].lower() == b"bearer " else ""
        if token and _secrets_mod.compare_digest(token, self.widget_token):
            return None
        return JSONResponse({"error": "unauthorized"}, status_code=401)
```

`install()`의 `app.add_middleware(AuthGate)`(162행)를 교체:

```python
    app.add_middleware(AuthGate, widget_token=settings.widget_token)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_auth.py tests/test_widget.py -q`
Expected: 전부 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/api/auth.py tests/test_auth.py
git commit -m "feat(widget): AuthGate 안 Bearer 검사 — 모든 경로 잠금 불변식 무예외 유지(무토큰 401·미설정 503)"
```

---

### Task 5: `/widget-setup` 페이지 + Scriptable 스크립트(↻ 갱신 버튼 포함)

**Files:**
- Create: `backend/report/widget_setup.py`
- Modify: `backend/api/app.py` (`/scanner` 라우트 아래에 라우트 추가)
- Test: `tests/test_widget_setup.py` (신규)

**Interfaces:**
- Consumes: `dashboard._BASE_CSS`/`_PWA_HEAD`, `settings.widget_token`.
- Produces: `render_widget_setup(token: str, base_url: str) -> str` (HTML).
- Produces: `GET /widget-setup` — 세션 게이트 뒤(PROTECTED는 Task 4에서 이미 추가).
- Produces: Scriptable 스크립트 `StockMaster` — 토큰 없는 공유-안전 파일, Keychain·중간 크기·오프라인 캐시·↻ 갱신.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_widget_setup.py
"""위젯 설치 페이지 — 토큰은 페이지에만(게이트 뒤), 스크립트 본문엔 절대 없음.

스크립트는 node --check로 문법 스모크(test_live_page_js.py 선례 — 문자열 존재
검사로는 SyntaxError로 위젯 전체가 죽는 사고를 못 잡는다)."""
import re
import shutil
import subprocess

import pytest

TOKEN = "t" * 32
BASE = "https://example.ts.net"

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 미설치 — JS 문법 스모크 생략")


def _page():
    from backend.report.widget_setup import render_widget_setup
    return render_widget_setup(TOKEN, BASE)


def _script():
    """페이지에서 스크립트 블록(<pre id="script">…</pre>)을 추출해 unescape."""
    import html as _html
    m = re.search(r'<pre id="script">([\s\S]*?)</pre>', _page())
    assert m, "스크립트 블록 없음"
    return _html.unescape(m.group(1))


def test_page_shows_token_but_script_never_contains_it():
    page, script = _page(), _script()
    assert TOKEN in page                      # 토큰 박스(게이트 뒤라 안전)
    assert TOKEN not in script                # 스크립트는 공유-안전(설계: Keychain)
    assert BASE in script                     # __BASE_URL__ 치환됨
    assert "__BASE_URL__" not in script


def test_script_has_required_parts():
    s = _script()
    for marker in ("Keychain", "timeoutInterval", "FileManager.local",
                   "refreshAfterDate", "mode=refresh", "widgetFamily",
                   "isAuth", "토큰 다시 입력"):
        assert marker in s, marker + " 누락"


@needs_node
def test_script_syntax_ok(tmp_path):
    p = tmp_path / "StockMaster.mjs"   # .mjs = 항상 ESM 파싱 — 최상위 await가 node<22.7에서도 통과
    p.write_text(_script(), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_route_serves_page_and_503_without_token(tmp_path):
    from fastapi.testclient import TestClient
    from backend.config import Settings
    from backend.api.app import create_app
    s = Settings(cache_dir=str(tmp_path), flow_mode="demo", widget_token=TOKEN,
                 kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    c = TestClient(create_app(s))
    r = c.get("/widget-setup")
    assert r.status_code == 200 and "Scriptable" in r.text
    s2 = Settings(cache_dir=str(tmp_path), flow_mode="demo", widget_token=None,
                  kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    assert TestClient(create_app(s2)).get("/widget-setup").status_code == 503
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_widget_setup.py -x -q`
Expected: FAIL — `ModuleNotFoundError: backend.report.widget_setup`

- [ ] **Step 3: widget_setup.py 구현** — 파일 전체 생성:

```python
from __future__ import annotations

"""위젯 설치 페이지(/widget-setup) — 게이트 뒤. 토큰·스크립트를 아이폰 사파리에서 복사.

파일 전송·토큰 수동 조회 단계를 통째로 없앤다(설계: 초보 최대 실패 지점 제거).
스크립트 본문에 토큰은 절대 넣지 않는다 — Scriptable은 기본으로 스크립트를
iCloud Drive에 평문 동기화하므로, 토큰은 최초 실행 시 1회 입력받아 Keychain에 저장."""

from html import escape

from backend.report.dashboard import _BASE_CSS, _PWA_HEAD

# Scriptable 위젯 스크립트 — 이 문자열이 곧 배포물이다(토큰 없음·공유-안전).
# JS는 Scriptable(JavaScriptCore) 대상: 옵셔널체이닝(?.) 등 신문법 회피.
_SCRIPT = r"""// Stock Master 아이폰 위젯 — 관심종목 시세 (중간 크기 전용)
// 이 파일에 비밀 토큰은 없습니다(최초 1회 입력 → 아이폰 Keychain 저장).
// ⚠ 이 스크립트·토큰을 타인과 공유하지 마세요 — KIS 시세 제3자 제공은 약관 위반.
const BASE = "__BASE_URL__";
const KEY = "sm_widget_token";
const CACHE = "sm_widget_cache.json";
const UP = Color.dynamic(new Color("#d32f2f"), new Color("#ff6b6b"));
const DOWN = Color.dynamic(new Color("#1565c0"), new Color("#6ba3ff"));

function cachePath() {
  // FileManager.local 고정 — iCloud는 위젯 컨텍스트에서 '미다운로드'로 못 읽고,
  // cacheDirectory는 iOS가 임의 삭제한다(설계).
  const fm = FileManager.local();
  return { fm: fm, path: fm.joinPath(fm.documentsDirectory(), CACHE) };
}
function saveCache(d) {
  try { const c = cachePath(); c.fm.writeString(c.path, JSON.stringify(d)); } catch (e) {}
}
function loadCache() {
  try {
    const c = cachePath();
    if (!c.fm.fileExists(c.path)) return null;
    return JSON.parse(c.fm.readString(c.path));
  } catch (e) { return null; }
}

async function getToken(promptIfMissing) {
  if (Keychain.contains(KEY)) return Keychain.get(KEY);
  if (!promptIfMissing) return null;
  const a = new Alert();
  a.title = "위젯 토큰 입력";
  a.message = "사파리로 " + BASE + "/widget-setup 에서 토큰을 복사해 붙여넣으세요 (1회만)";
  a.addSecureTextField("토큰");
  a.addAction("저장");
  a.addCancelAction("취소");
  if (await a.presentAlert() === -1) return null;
  const t = a.textFieldValue(0).trim();
  if (t) Keychain.set(KEY, t);
  return t || null;
}

async function fetchData(token) {
  const req = new Request(BASE + "/api/widget");
  req.timeoutInterval = 10;   // 기본 60초는 위젯 실행 예산 초과 — 맥 잠자기 = 매달리는 실패
  req.headers = { "Authorization": "Bearer " + token };
  const d = await req.loadJSON();
  if (d && d.error === "unauthorized") {
    const e = new Error("토큰이 맞지 않아요");   // 401 구분 — 오프라인과 다른 안내(스펙 에러 표)
    e.isAuth = true;
    throw e;
  }
  if (!d || !d.items) throw new Error("응답 오류 — 토큰을 확인하세요");
  return d;
}

function pad(n) { return (n < 10 ? "0" : "") + n; }
function fmtPrice(v) { return v == null ? "—" : Number(v).toLocaleString("ko-KR"); }
function fmtChg(c) {
  if (c == null) return "—";
  const s = c > 0 ? "+" : (c < 0 ? "−" : "");
  return s + Math.abs(c).toFixed(2) + "%";
}
function chgColor(c) {
  if (c == null || c === 0) return Color.gray();
  return c > 0 ? UP : DOWN;
}
function statusLabel(d) {
  if (d.open) {
    const t = new Date(d.fetched_at);
    return pad(t.getHours()) + ":" + pad(t.getMinutes()) + " 장중";
  }
  const td = new Date(d.trade_date + "T00:00:00+09:00");
  const w = "일월화수목금토".charAt(td.getDay());
  return (td.getMonth() + 1) + "/" + td.getDate() + "(" + w + ") 마감";
}

function buildWidget(d, offline) {
  const w = new ListWidget();
  w.url = BASE + "/";   // 몸통 탭 → 대시보드(미지정 시 편집기가 열려 초보 사고 지점)
  const fam = config.widgetFamily || "medium";   // 앱 내 미리보기(null) = medium 취급
  if (d && d.refresh_after_sec)
    w.refreshAfterDate = new Date(Date.now() + d.refresh_after_sec * 1000);
  const head = w.addStack();
  const title = head.addText("관심종목");
  title.font = Font.boldSystemFont(13);
  head.addSpacer();
  const brand = head.addText("STOCK MASTER");
  brand.font = Font.mediumSystemFont(9);
  brand.textColor = Color.gray();
  w.addSpacer(4);
  if (!d) {
    const t = w.addText("서버에 연결할 수 없어요.\n스크립트를 실행해 토큰을 확인하세요.");
    t.font = Font.systemFont(12);
    return w;
  }
  const max = fam === "large" ? 10 : 5;
  const items = d.items.slice(0, max);
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const row = w.addStack();
    row.centerAlignContent();
    const nm = row.addText(it.name);
    nm.font = Font.mediumSystemFont(13);
    nm.lineLimit = 1;
    nm.minimumScaleFactor = 0.7;   // 'LG에너지솔루션' 등 긴 이름 완충
    row.addSpacer();
    const px = row.addText(fmtPrice(it.price));
    px.font = Font.mediumSystemFont(13);
    const ch = row.addText("  " + fmtChg(it.change));
    ch.font = Font.boldSystemFont(12);
    ch.textColor = chgColor(it.change);
    w.addSpacer(2);
  }
  if (d.items.length > max) {
    const more = w.addText("+" + (d.items.length - max) + "종목");
    more.font = Font.systemFont(10);
    more.textColor = Color.gray();
  }
  w.addSpacer();
  const foot = w.addStack();
  foot.centerAlignContent();
  const st = foot.addText((offline ? "오프라인 · " : "") + statusLabel(d));
  st.font = Font.systemFont(10);
  st.textColor = offline ? Color.orange() : Color.gray();
  foot.addSpacer();
  const rf = foot.addStack();   // ↻ 갱신: 자체 url — 몸통 탭(대시보드)과 영역 구분
  rf.url = "scriptable:///run/" + encodeURIComponent(Script.name()) + "?mode=refresh";
  const rt = rf.addText("↻ 갱신");
  rt.font = Font.boldSystemFont(10);
  rt.textColor = Color.gray();
  return w;
}

function buildAuthError() {
  // 401: 캐시 폴백이 아니라 재입력 안내(스펙 §에러 처리 — 토큰 회전 직후 '오프라인' 오진단 방지)
  const w = new ListWidget();
  w.url = BASE + "/widget-setup";
  const t = w.addText("토큰이 맞지 않아요");
  t.font = Font.boldSystemFont(13);
  w.addSpacer(4);
  const s = w.addText("Scriptable에서 이 스크립트를 ▶ 실행해 '토큰 다시 입력'을 선택하세요.");
  s.font = Font.systemFont(11);
  s.textColor = Color.gray();
  return w;
}

async function showLive(token) {
  // ↻ 갱신: 앱에서 즉시 KIS 최신 시세를 전체 화면 표로 + 캐시 갱신.
  // (위젯 숫자의 즉시 갱신은 iOS가 허용하지 않음 — 다음 OS 갱신 때 반영)
  let d = null, err = "";
  try { d = await fetchData(token); saveCache(d); } catch (e) { err = String(e); }
  const t = new UITable();
  t.showSeparators = true;
  const hr = new UITableRow();
  hr.isHeader = true;
  hr.addText(d ? "실시간 시세 · " + statusLabel(d) : "갱신 실패: " + err);
  t.addRow(hr);
  const items = d ? d.items : ((loadCache() || {}).items || []);
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const r = new UITableRow();
    r.height = 48;
    r.addText(it.name, it.code);
    r.addText(fmtPrice(it.price) + "   " + fmtChg(it.change)).rightAligned();
    t.addRow(r);
  }
  await t.present(false);
}

const params = args.queryParameters || {};
if (config.runsInWidget) {
  const token = await getToken(false);
  let data = null, offline = false, authError = false;
  if (token) {
    try { data = await fetchData(token); saveCache(data); }
    catch (e) {
      if (e && e.isAuth) { authError = true; }        // 401 → 재입력 안내(캐시 폴백 아님)
      else { data = loadCache(); offline = true; }    // 그 외 실패 = 캐시 + 오프라인 배지
    }
  } else {
    data = loadCache();
    offline = true;
  }
  Script.setWidget(authError ? buildAuthError() : buildWidget(data, offline));
} else if (params.mode === "refresh") {
  const token = await getToken(true);
  if (token) await showLive(token);
} else if (!Keychain.contains(KEY)) {
  // 최초 설치: 토큰 입력 → 다음 단계 안내
  const token = await getToken(true);
  if (token) {
    const a = new Alert();
    a.title = "설정 완료";
    a.message = "홈 화면을 길게 눌러 Scriptable 위젯(중간 크기)을 추가하고,\n위젯 편집에서 Script를 이 스크립트로 지정하세요.";
    a.addAction("확인");
    await a.presentAlert();
  }
} else {
  // 재실행 메뉴 — 토큰 회전(가이드 문제해결) 시 '토큰 다시 입력'이 실제로 동작해야 한다
  const a = new Alert();
  a.title = "Stock Master 위젯";
  a.addAction("실시간 시세 보기");
  a.addAction("토큰 다시 입력");
  a.addCancelAction("닫기");
  const i = await a.presentAlert();
  if (i === 0) await showLive(Keychain.get(KEY));
  else if (i === 1) { Keychain.remove(KEY); await getToken(true); }
}
Script.complete();
"""

_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>위젯 설치 — Stock Master</title>
__PWA_HEAD__
<style>
__BASE_CSS__
.step{margin:14px 0;padding:14px;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r)}
.step h3{margin:0 0 6px;font-size:15px}
.step p{margin:0;font-size:13px;color:var(--text-2);line-height:1.6}
.tok{font-family:ui-monospace,Menlo,monospace;font-size:13px;word-break:break-all;
  background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-sm);
  padding:10px 12px;margin:8px 0}
pre#script{font-family:ui-monospace,Menlo,monospace;font-size:11px;line-height:1.5;
  background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-sm);
  padding:12px;max-height:300px;overflow:auto;white-space:pre-wrap;word-break:break-all}
button.copy{min-height:44px;padding:10px 18px;border:0;border-radius:var(--r-sm);
  background:var(--primary);color:#fff;font-size:14px;font-weight:700;cursor:pointer}
.warn{background:var(--warn-bg);border:1px solid var(--border);border-radius:var(--r);
  padding:12px 14px;font-size:13px;margin:14px 0}
</style></head><body>
<div id="app"><div id="app-scroll">
<div><a class="back" href="/">← 대시보드</a></div>
<h1>📱 아이폰 위젯 설치</h1>
<div class="warn">⚠ 이 페이지의 토큰과 스크립트를 <b>타인과 공유하지 마세요</b> —
KIS 시세 제3자 제공은 약관 위반입니다. 자세한 사용법: docs/widget-guide.md</div>
<div class="step"><h3>1. App Store에서 “Scriptable” 설치 (무료)</h3>
<p>애플 개발자 계정·컴퓨터 불필요.</p></div>
<div class="step"><h3>2. 아래 스크립트 전체 복사 → Scriptable 새 스크립트에 붙여넣기</h3>
<p>Scriptable 앱 → 우상단 ＋ → 붙여넣기 → 이름을 <b>StockMaster</b>로 저장.</p>
<p style="margin-top:8px"><button class="copy" onclick="copyScript()">스크립트 전체 복사</button>
<span id="copied1" style="font-size:12px;color:var(--good)"></span></p>
<pre id="script">__SCRIPT__</pre></div>
<div class="step"><h3>3. 스크립트 실행(▶) → 토큰 붙여넣기 (1회)</h3>
<p>아래 토큰을 복사해 두세요. 토큰은 아이폰 Keychain에 저장되고 파일엔 남지 않습니다.</p>
<div class="tok" id="token">__TOKEN__</div>
<p><button class="copy" onclick="copyToken()">토큰 복사</button>
<span id="copied2" style="font-size:12px;color:var(--good)"></span></p></div>
<div class="step"><h3>4. 홈 화면 길게 누르기 → ＋ → Scriptable → <b>중간 크기</b> → 추가</h3>
<p>작게/크게 말고 중간(4×2)을 선택하세요.</p></div>
<div class="step"><h3>5. 위젯 길게 누르기 → 위젯 편집 → Script: <b>StockMaster</b> 지정</h3>
<p>⚠ 이 단계를 빼먹으면 “Tap to configure” 상태로 남습니다 — 가장 흔한 실수.</p></div>
<script>
function _copy(id, mark){
  const t = document.getElementById(id).textContent;
  navigator.clipboard.writeText(t).then(function(){
    document.getElementById(mark).textContent = ' ✓ 복사됨';
  });
}
function copyScript(){ _copy('script', 'copied1'); }
function copyToken(){ _copy('token', 'copied2'); }
</script>
</div></div></body></html>"""


def render_widget_setup(token: str, base_url: str) -> str:
    """설치 페이지 HTML — 토큰은 이 페이지(게이트 뒤)에만, 스크립트엔 절대 없음."""
    script = _SCRIPT.replace("__BASE_URL__", base_url.rstrip("/"))
    return (_TEMPLATE
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__SCRIPT__", escape(script))
            .replace("__TOKEN__", escape(token)))
```

⚠ 구현 시 확인: `dashboard.py`가 실제로 `_BASE_CSS`·`_PWA_HEAD`라는 이름을 export하는지(scanner_page.py:10-11의 import 목록이 근거). `.back` CSS 클래스가 `_BASE_CSS`에 없으면 스타일 블록에 추가.

- [ ] **Step 4: 라우트 추가** — `backend/api/app.py`의 `/scanner` 라우트 아래:

```python
    @app.get("/widget-setup", response_class=HTMLResponse)
    def widget_setup_page(request: Request):
        """위젯 설치 페이지 — 게이트 뒤(공개 아님). 토큰·스크립트를 사파리에서 복사.
        base_url은 프록시 헤더 우선(Funnel이 X-Forwarded-Proto: https를 붙임)."""
        if not settings.widget_token:
            return HTMLResponse("SM_WIDGET_TOKEN이 설정되지 않았어요 — .env에 추가 후 재시작",
                                status_code=503)
        from backend.report.widget_setup import render_widget_setup
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", request.url.netloc)
        return HTMLResponse(render_widget_setup(settings.widget_token,
                                                "%s://%s" % (scheme, host)))
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_widget_setup.py tests/test_auth.py -q`
Expected: 전부 passed (node 없으면 문법 스모크 1건 skip)

- [ ] **Step 6: 커밋**

```bash
git add backend/report/widget_setup.py backend/api/app.py tests/test_widget_setup.py
git commit -m "feat(widget): /widget-setup 설치 페이지 + Scriptable 스크립트(Keychain·오프라인 캐시·↻ 갱신)"
```

---

### Task 6: 설치·사용 가이드 `docs/widget-guide.md`

**Files:**
- Create: `docs/widget-guide.md`

**Interfaces:**
- Consumes: `/widget-setup` 5단계(Task 5와 문구 일치).

- [ ] **Step 1: 파일 생성** — 아래 내용 그대로:

```markdown
# 아이폰 홈 위젯 — 설치·사용 가이드

> ⚠ **공유 금지**: 이 위젯의 토큰(그리고 토큰이 표시되는 /widget-setup 화면)을
> 타인과 공유하면 KIS 시세를 제3자에게 제공하는 것이 되어 약관 위반입니다.
> 스크립트 파일 자체에는 토큰이 없어 안전하지만, 토큰은 절대 밖으로 보내지 마세요.

## 설치 (5단계, 약 5분)

1. **App Store에서 “Scriptable” 설치** (무료 — 개발자 계정·컴퓨터 불필요)
2. **아이폰 사파리로 `https://YOUR-MAC.YOUR-TAILNET.ts.net/widget-setup` 접속**
   — 평소처럼 구글 로그인 + 2FA. 토큰과 스크립트가 준비되어 있습니다.
3. **[스크립트 전체 복사] → Scriptable 앱 → ＋ → 붙여넣기 → 이름 `StockMaster`로 저장
   → ▶ 실행 → [토큰 복사]한 값 붙여넣기(1회)** — 토큰은 아이폰 Keychain에 저장됩니다.
4. **홈 화면 길게 누르기 → 왼쪽 위 ＋ → Scriptable 검색 → 중간 크기 선택 → 추가**
5. **추가된 위젯 길게 누르기 → 위젯 편집 → Script: `StockMaster` 지정**
   — ⚠ 이 단계를 빼먹으면 “Tap to configure”로 남습니다(가장 흔한 실수).

## 사용법

| 동작 | 결과 |
|---|---|
| 위젯 보기 | 관심종목 이름·현재가·등락률(빨강↑/파랑↓) + 하단 상태 |
| 위젯 몸통 탭 | Stock Master 앱(사파리) 열림 |
| **↻ 갱신 탭** | Scriptable이 열리며 **즉시 실시간 시세 표** 표시(위젯 숫자는 다음 자동 갱신 때 반영 — iOS 제약) |
| “HH:MM 장중” | 장중 KIS 실시간 현재가 기준 시각 |
| “7/15(화) 마감” | 장외 — 해당 거래일의 마감값(NXT 애프터장 반영값일 수 있음) |
| “오프라인 · …” | 서버(맥북)에 연결 실패 — 마지막 저장값 표시 중 |

- **갱신 주기**: iOS가 정합니다(대략 15분+, 밤·주말엔 다음 개장까지 잠듦).
  실시간 티커가 아니라 “쓱 보는 근사치”입니다. 지금 값이 필요하면 ↻ 갱신을 탭하세요.
- **맥북이 잠자면** 위젯도 새 값을 못 받습니다 — “오프라인” 표시로 알 수 있습니다.

## 문제 해결

| 증상 | 조치 |
|---|---|
| “응답 오류 — 토큰을 확인하세요” | Scriptable에서 스크립트 ▶ 실행 → 토큰 재입력 |
| 위젯이 “Tap to configure” | 위젯 편집에서 Script: StockMaster 지정(설치 5단계) |
| 계속 “오프라인” | 맥북 서버 확인: `curl -s localhost:8000/healthz` → 필요 시 재기동(docs 서버 운영 메모) |
| 토큰 유출 의심 | `.env`의 `SM_WIDGET_TOKEN` 교체(생성: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`) → 서버 재시작 → 아이폰에서 스크립트 ▶ 실행해 새 토큰 입력 |

## 관심종목 바꾸기 (2단계 배포 후)

대시보드 검색에서 **＋추가**, 카드에서 **－삭제** — 최대 10종목.
위젯·대시보드·MCP·리포트가 같은 목록을 봅니다.

> 알려진 제약: 새로 담은 종목은 뉴스 매칭에 회사명 1개(공식명)만 쓰여
> 약칭·영문명 기사가 안 잡힐 수 있어요. 기본 5종목은 수동 별칭이 튜닝돼 있습니다.
```

- [ ] **Step 2: 커밋**

```bash
git add docs/widget-guide.md
git commit -m "docs(widget): 설치·사용 가이드 — 5단계 설치·↻ 갱신·문제해결·공유 금지 경고"
```

---

### Task 7: 실서버 배선 + KIS 실측 (마스터와 함께, verify 스킬)

**Files:** `.env` (git 밖), 실측 확인만 — 코드 변경 없음.

- [ ] **Step 1: 토큰 생성·설정**

```bash
.venv/bin/python -c "import secrets; print('SM_WIDGET_TOKEN=' + secrets.token_urlsafe(32))" >> .env
tail -1 .env   # 값 확인
```

- [ ] **Step 2: 서버 재기동** — `docs/superpowers/` 서버 운영 메모대로 graceful SIGTERM 후 `.venv/bin/python -m backend.cli serve` (raw 시스템 3.9 금지 — pydantic_settings 없음).

- [ ] **Step 3: FHKST01010400 실측** (설계의 “구현 시 실측” 항목 — 장중·장외 각 1회)

```bash
.venv/bin/python - <<'EOF'
import asyncio
from backend.flow.candles import _get_client
async def main():
    c = _get_client()
    print("latest_trade_date:", await c.latest_trade_date())
    print("price(005930):", await c.price("005930"))
asyncio.run(main())
EOF
```
Expected: 거래일 평일 장중 → 오늘 날짜. 장외/주말 → 직전 거래일. `price`는 장외에도 직전 세션 종가+rate. **장중 당일 행이 안 나오면** `market_status.get_status`의 open 판정이 항상 false가 되므로, 그 경우 open 판정을 `wall and (td is None or td == today or td < today와 무관하게 wall 우선)`으로 조정하는 후속 결정 필요 — 실측 결과를 스펙에 기록.

- [ ] **Step 4: 로컬 왕복 확인**

```bash
TOKEN=$(grep SM_WIDGET_TOKEN .env | cut -d= -f2)
curl -s localhost:8000/api/widget | head -c 200          # 게이트: 401 (auth on일 때)
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/widget
```
Expected: 무토큰 `{"error":"unauthorized"}`(auth on) · 토큰 시 items 5건 JSON.

- [ ] **Step 5: Funnel 왕복 + 아이폰 실기기 설치** — 가이드(Task 6) 순서대로 마스터가 진행, ↻ 갱신·오프라인(서버 내리고) 확인.

---

# 2단계 — 편집 가능 관심종목

### Task 8: `watchlist` 저장소 모듈

**Files:**
- Create: `backend/flow/watchlist.py`
- Test: `tests/test_watchlist.py` (신규)

**Interfaces:**
- Consumes: `settings.watchlist`(시드), `settings.cache_dir`.
- Produces: `get_watchlist() -> list` — 파일값 우선, 없으면 시드. **이후 `settings.watchlist` 직접 참조 금지.**
- Produces: `set_watchlist(codes) -> list` — 검증 실패 `ValueError`(사용자 메시지). `MAX_CODES = 10`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_watchlist.py
"""관심종목 저장소 — watch.py(감시선) 미러: 검증·원자성·시드 폴백."""
import json
import os

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))


def test_get_falls_back_to_seed_when_no_file():
    from backend.flow.watchlist import get_watchlist
    from backend.config import settings
    assert get_watchlist() == list(settings.watchlist)


def test_set_then_get_roundtrip(tmp_path):
    from backend.flow import watchlist as wl
    saved = wl.set_watchlist(["035720", "005930"])
    assert saved == ["035720", "005930"]
    assert wl.get_watchlist() == ["035720", "005930"]
    with open(os.path.join(str(tmp_path), "watchlist.json"), encoding="utf-8") as f:
        assert json.load(f) == {"codes": ["035720", "005930"]}


def test_set_validates():
    from backend.flow import watchlist as wl
    with pytest.raises(ValueError):
        wl.set_watchlist("not-a-list")
    with pytest.raises(ValueError):
        wl.set_watchlist(["12345"])            # 6자리 아님
    with pytest.raises(ValueError):
        wl.set_watchlist([])                    # 최소 1개
    with pytest.raises(ValueError):
        wl.set_watchlist(["%06d" % i for i in range(11)])   # 최대 10개


def test_set_dedups_preserving_order():
    from backend.flow import watchlist as wl
    assert wl.set_watchlist(["005930", "000660", "005930"]) == ["005930", "000660"]


def test_corrupt_file_falls_back_to_seed(tmp_path):
    from backend.flow.watchlist import get_watchlist
    from backend.config import settings
    with open(os.path.join(str(tmp_path), "watchlist.json"), "w") as f:
        f.write("{broken")
    assert get_watchlist() == list(settings.watchlist)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_watchlist.py -x -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현** — `backend/flow/watchlist.py` 전체:

```python
from __future__ import annotations

"""관심종목 서버 저장 — 단일 진실 원천(설계 2026-07-16).

저장 파일: <cache_dir>/watchlist.json = {"codes": ["005930", ...]}.
소비자 5곳(대시보드·/api/prices·/api/widget·CLI report·MCP tools)은 전부
get_watchlist()를 경유한다 — settings.watchlist 직접 참조 금지(시드 전용 격하).
감시선(watch.py)과 동일 패턴: 원자적 쓰기 + 모듈 Lock, 부재/손상 시 시드 폴백.
순서 = 저장 순서 = 표시 순서(새 종목은 UI가 맨 앞에 넣는다). Python 3.9 호환."""

import json
import os
import re
import threading
from pathlib import Path

from backend.config import settings

_LOCK = threading.Lock()
_CODE_RE = re.compile(r"^\d{6}$")
MAX_CODES = 10   # 대시보드 렌더·KIS 동시 호출·위젯 공간 모두 커버(설계)


def _path() -> Path:
    return Path(settings.cache_dir) / "watchlist.json"


def get_watchlist() -> list:
    """현재 관심종목 코드 목록 — 파일값 우선, 부재/손상/무효면 config 시드."""
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        codes = d.get("codes") if isinstance(d, dict) else None
        if isinstance(codes, list):
            valid = [c for c in codes if isinstance(c, str) and _CODE_RE.match(c)]
            if valid:
                return valid
    except Exception:
        pass
    return list(settings.watchlist)


def set_watchlist(codes) -> list:
    """검증 후 원자적 저장. 위반 시 ValueError(사용자 노출 메시지). 저장 목록 반환."""
    if not isinstance(codes, list):
        raise ValueError("종목 코드 목록(배열)이 필요해요")
    norm, seen = [], set()
    for c in codes:
        c = str(c).strip()
        if not _CODE_RE.match(c):
            raise ValueError("종목 코드는 6자리 숫자여야 해요: %s" % c)
        if c not in seen:
            seen.add(c)
            norm.append(c)
    if not norm:
        raise ValueError("관심종목은 최소 1개 필요해요")
    if len(norm) > MAX_CODES:
        raise ValueError("관심종목은 최대 %d개까지 저장할 수 있어요" % MAX_CODES)
    with _LOCK:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"codes": norm}, f, ensure_ascii=False)
        os.replace(tmp, p)   # 원자적 교체 — 부분쓰기 방지
    return norm
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_watchlist.py -q`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/flow/watchlist.py tests/test_watchlist.py
git commit -m "feat(watchlist): 서버 저장소 — 최대 10종목·검증·원자적 쓰기·시드 폴백"
```

---

### Task 9: 이름 해석 일반화 (universe 우선, 하드코딩 폴백)

**Files:**
- Modify: `backend/market/universe.py` (`price_map` 아래에 `name_map`)
- Modify: `backend/news/names.py` (`display_name` 아래에 `resolve_name`)
- Modify: `backend/report/dashboard.py` (`assemble_stock`, 222-233행)
- Modify: `backend/cli.py` (`_collect_issues` 22-41행 → `_news_aliases` 분리, `build_dashboard` 104-122행)
- Modify: `backend/mcp/tools.py` (`_analyze` 31-44행)
- Modify: `backend/api/widget.py` (`display_name` → `resolve_name`)
- Test: `tests/test_widget.py`·`tests/test_dashboard.py` (추가)

**Interfaces:**
- Produces: `universe.name_map(universe) -> dict` (code→name).
- Produces: `names.resolve_name(code, names=None) -> str` — names dict 우선 → `display_name` 폴백(모르면 코드).
- Produces: `cli._news_aliases(codes, names=None) -> dict` — 수동 별칭(STOCK_NAMES) 우선, 없으면 universe 이름 1개.
- Changes: `assemble_stock(signal, issues, candles, price, names=None)` — **기존 4-인자 호출은 그대로 동작**(names 기본 None).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_widget.py`에 추가:

```python
# ── 이름 해석: universe 우선, 하드코딩 폴백 ────────────────────────
def test_resolve_name_chain():
    from backend.news.names import resolve_name
    uni_names = {"035720": "카카오"}
    assert resolve_name("035720", uni_names) == "카카오"       # universe 히트
    assert resolve_name("005930", uni_names) == "삼성전자"     # 미스 → 하드코딩
    assert resolve_name("999999", uni_names) == "999999"       # 둘 다 미스 → 코드


def test_news_aliases_manual_first_then_universe():
    from backend.cli import _news_aliases
    a = _news_aliases(["005930", "035720"], {"035720": "카카오"})
    assert a["005930"] == ["삼성전자"]        # 수동 별칭 우선(STOCK_NAMES)
    assert a["035720"] == ["카카오"]          # 신규 종목 → universe 이름 1개
    assert _news_aliases(["035720"], None)["035720"] == []   # 이름 없으면 빈 별칭


def test_widget_data_resolves_new_stock_name(tmp_path, monkeypatch):
    """신규 종목이 '035720' 숫자가 아니라 universe 이름으로 표시(설계 major #6)."""
    from backend.config import settings
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    _seed_universe(str(tmp_path), [
        {"code": "035720", "name": "카카오", "close": 43000.0, "change": -0.5}])
    d = asyncio.run(widget_data(["035720"]))
    assert d["items"][0]["name"] == "카카오"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_widget.py -x -q`
Expected: FAIL — `resolve_name` 없음

- [ ] **Step 3: 구현**

`backend/market/universe.py` — `price_map` 아래:

```python
def name_map(universe: list) -> dict:
    """code → name — 표시 이름 해석용(resolve_name에 주입)."""
    return {u["code"]: u["name"] for u in universe if u.get("name")}
```

`backend/news/names.py` — `display_name` 아래:

```python
def resolve_name(code: str, names=None) -> str:
    """표시 이름 — universe 이름(names dict) 우선, 하드코딩 폴백, 모르면 코드.

    신규 관심종목이 '035720' 숫자로 표시되는 문제의 해소(설계 2026-07-16).
    names는 universe.name_map() 결과를 호출부가 주입(이 모듈은 I/O 없음 유지)."""
    if names:
        n = names.get(code)
        if n:
            return n
    return display_name(code)
```

`backend/report/dashboard.py` — `assemble_stock` 시그니처와 name 줄만 변경:

```python
def assemble_stock(signal, issues, candles, price, names=None) -> dict:
    """신호 + 이슈 + 캔들 + 현재가를 대시보드 종목 dict로 합친다.
    names(universe code→name)가 있으면 표시 이름을 그것으로(신규 종목 대응)."""
    from backend.news.names import resolve_name
    iv = _issues_view(issues)
    return {"code": signal.code, "name": resolve_name(signal.code, names),
```
(나머지 필드는 기존 그대로 — `display_name(signal.code)`만 `resolve_name(signal.code, names)`로.)

`backend/cli.py` — `_collect_issues`를 분리·확장(기존 22-41행 교체):

```python
def _news_aliases(codes, names=None) -> dict:
    """뉴스 매칭 별칭 — 수동 별칭(STOCK_NAMES, 경계 인식 튜닝됨) 우선,
    없으면 universe 이름 1개 자동 보강(신규 종목 뉴스 영구 0건 방지 — 설계)."""
    return {c: (STOCK_NAMES.get(c)
                or ([names[c]] if names and names.get(c) else []))
            for c in codes}


def _collect_issues(codes, names=None):
    """RSS 뉴스 + DART 공시를 수집해 종목별로 매칭한다. (기존 독스트링 유지)"""
    try:
        news = fetch_news(settings.news_feeds)
    except Exception:
        log.warning("RSS 뉴스 수집 실패 — 뉴스 없이 진행", exc_info=True)
        news = []
    try:
        disclosures = fetch_disclosures(
            settings.dart_api_key, codes, settings.disclosure_lookback_days
        )
    except Exception:
        log.warning("DART 공시 수집 실패 — 공시 없이 진행", exc_info=True)
        disclosures = []
    return attach_issues(news, disclosures, codes, _news_aliases(codes, names),
                         max_per_stock=settings.news_max_per_stock)
```

`backend/cli.py` — `build_dashboard`(104-122행): universe를 이슈 수집 **앞**으로 올리고 names 전달:

```python
    signals, candles = [], {}
    for code in codes:
        df = adapter.get_ohlcv(code, start.isoformat(), end.isoformat(), force=force)
        signals.append(evaluate_with_gate(add_indicators(df), code))
        candles[code] = to_candles(df, chart_days)
    universe = get_universe(cache_dir)
    nm = name_map(universe)
    issues = _collect_issues(codes, nm) if with_news else {}
    pm = price_map(universe)
    if _kr_market_open():   # 장중엔 관심종목을 KIS 실시간 현재가로 덮어씀(StockListing=전일 종가)
        pm.update(_live_prices(codes))
    stocks = [assemble_stock(s, issues.get(s.code), candles.get(s.code), pm.get(s.code), nm)
              for s in signals]
    return render_dashboard(stocks, universe, end.isoformat(), pwa=pwa)
```
import 줄에 `name_map` 추가: `from backend.market.universe import get_universe, price_map, name_map`

`backend/mcp/tools.py` — `_analyze`에서 동일하게:

```python
    from backend.market.universe import name_map
    uni = get_universe(settings.cache_dir)
    pm = price_map(uni)
    nm = name_map(uni)
    issues = _collect_issues(list(codes), nm) if with_news else {}
    ...
        rows.append(assemble_stock(sig, issues.get(code), to_candles(df, chart_days),
                                   pm.get(code), nm))
```

`backend/api/widget.py` — import와 name 줄 교체:

```python
from backend.news.names import resolve_name
```
`widget_data`에서 items 조립 직전에 추가/교체:

```python
    names = _universe.name_map(_universe.get_cached())   # stale 허용 읽기 전용(수집 금지)
    items = [{"code": c, "name": resolve_name(c, names),
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_widget.py tests/test_dashboard.py tests/test_mcp.py tests/test_cli.py -q`
Expected: 전부 passed (assemble_stock 기존 4-인자 호출부는 names=None 폴백으로 무회귀)

- [ ] **Step 5: 커밋**

```bash
git add backend/market/universe.py backend/news/names.py backend/report/dashboard.py backend/cli.py backend/mcp/tools.py backend/api/widget.py tests/test_widget.py
git commit -m "feat(names): 이름 해석 일반화 — universe 우선·하드코딩 폴백, 뉴스 별칭 자동 보강"
```

---

### Task 10: `/api/watchlist` 라우트 + 소비자 5곳 전환

**Files:**
- Modify: `backend/api/app.py` (index 69-74행, `/api/prices` 140-147행, `/api/widget`, 라우트 추가)
- Modify: `backend/cli.py` (`main`의 report 분기, 152행)
- Modify: `backend/mcp/tools.py` (`watchlist_summary` 78행, `dashboard_data` 89행)
- Test: `tests/test_widget.py`(라우트)·`tests/test_auth.py`(PROTECTED)

**Interfaces:**
- Consumes: `watchlist.get_watchlist()/set_watchlist()` (Task 8).
- Produces: `GET /api/watchlist` → `{"items":[{"code","name"}]}` / `POST /api/watchlist` body `{"codes":[...]}` → 저장 결과 or `400 {"error": 메시지}`.
- Changes: 대시보드·prices·widget·CLI report·MCP가 전부 `get_watchlist()` 경유.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_widget.py`에 추가:

```python
# ── /api/watchlist 편집 API + 소비자 공유 ─────────────────────────
def _client_local(tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    return TestClient(create_app(_settings(tmp_path)))


def test_watchlist_api_roundtrip_and_validation(tmp_path, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    c = _client_local(tmp_path)
    r = c.get("/api/watchlist")
    assert r.status_code == 200 and len(r.json()["items"]) >= 5      # 시드
    r = c.post("/api/watchlist", json={"codes": ["035720", "005930"]})
    assert r.status_code == 200
    assert [i["code"] for i in c.get("/api/watchlist").json()["items"]] == ["035720", "005930"]
    assert c.post("/api/watchlist", json={"codes": []}).status_code == 400
    assert c.post("/api/watchlist", json={"codes": ["12"]}).status_code == 400
    assert c.post("/api/watchlist", json={}).status_code == 400


def test_widget_follows_edited_watchlist(tmp_path, monkeypatch):
    """앱에서 편집 → 위젯이 따라감(확정 결정 3)."""
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    _seed_universe(str(tmp_path), [
        {"code": "035720", "name": "카카오", "close": 43000.0, "change": -0.5}])
    c = _client_local(tmp_path)
    assert c.post("/api/watchlist", json={"codes": ["035720"]}).status_code == 200
    d = c.get("/api/widget").json()
    assert [i["code"] for i in d["items"]] == ["035720"]
```

그리고 `tests/test_auth.py`의 `PROTECTED`에 `"/api/watchlist"` 추가.

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_widget.py tests/test_auth.py -x -q`
Expected: FAIL — `/api/watchlist` 404

- [ ] **Step 3: 구현**

`backend/api/app.py` — import에 추가:

```python
from backend.flow import watchlist as _watchlist
```

`/api/watch/{code}` 라우트 **위**에 추가(경로 충돌 방지 — FastAPI는 등록 순서 매칭이므로 `/api/watchlist`를 먼저 등록):

```python
    @app.get("/api/watchlist")
    def watchlist_get():
        """관심종목 목록 — 대시보드 편집 UI·확인용. 이름은 universe 우선."""
        from backend.market.universe import get_cached, name_map
        from backend.news.names import resolve_name
        nm = name_map(get_cached())
        return JSONResponse({"items": [{"code": c, "name": resolve_name(c, nm)}
                                       for c in _watchlist.get_watchlist()]})

    @app.post("/api/watchlist")
    async def watchlist_set(request: Request):
        """관심종목 저장(전체 교체) — body {"codes":[...]}. 검증 실패 400(사용자 메시지)."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "본문(JSON)을 읽을 수 없어요"}, status_code=400)
        codes = body.get("codes") if isinstance(body, dict) else None
        try:
            saved = _watchlist.set_watchlist(codes)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"codes": saved})
```

소비자 전환(각 1줄):
- `index()`(71행): `build_dashboard(settings.watchlist, ...)` → `build_dashboard(_watchlist.get_watchlist(), ...)`
- `prices_api()`(147행): `fetch_live_prices(settings.watchlist)` → `fetch_live_prices(_watchlist.get_watchlist())`
- `widget_api()`: `widget_data(settings.watchlist)` → `widget_data(_watchlist.get_watchlist())`
- `backend/cli.py` `main()` report 분기: `build_dashboard(settings.watchlist, ...)` → 위에 `from backend.flow.watchlist import get_watchlist` 지역 import 후 `build_dashboard(get_watchlist(), ...)`
- `backend/mcp/tools.py`: 상단 import에 `from backend.flow.watchlist import get_watchlist` 추가, `watchlist_summary`·`dashboard_data`의 `settings.watchlist` → `get_watchlist()`

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 전체 통과 (`tests/test_config.py`는 시드 의미 그대로라 무변경 통과)

- [ ] **Step 5: 커밋**

```bash
git add backend/api/app.py backend/cli.py backend/mcp/tools.py tests/test_widget.py tests/test_auth.py
git commit -m "feat(watchlist): /api/watchlist 편집 API + 소비자 5곳 get_watchlist() 전환(사일런트 분기 제거)"
```

---

### Task 11: 대시보드 편집 UI (＋추가/－삭제)

**Files:**
- Modify: `backend/report/dashboard.py` (cardHtml 125행 부근, searchRender 145-155행 부근, JS 하단)
- Test: `tests/test_dashboard.py` (문자열 단언 추가)

**Interfaces:**
- Consumes: `POST /api/watchlist` (Task 10).
- Produces: 검색 행 [＋추가] · 카드 [－삭제] 버튼, 새 종목 맨 앞 추가, 성공 시 새로고침.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_dashboard.py`에 추가:

```python
def test_dashboard_has_watchlist_edit_ui():
    """편집 UI 마커 — 검색 ＋담기 / 카드 －삭제 / 저장 JS가 템플릿에 존재.
    tests/test_dashboard.py의 기존 import(render_dashboard)와 _stock() 헬퍼를 재사용한다."""
    html = render_dashboard([_stock()], [], "2026-06-22")
    for marker in ("saveWatch", "addStock", "delStock", "wadd", "wdel"):
        assert marker in html, marker + " 누락"
```
(다섯 마커 모두 정적 템플릿의 JS/CSS 문자열에 들어가므로 이 최소 렌더로 충분하다.)

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -x -q`
Expected: FAIL — 마커 없음

- [ ] **Step 3: 구현** — `backend/report/dashboard.py` JS 구간 수정:

`cardHtml`의 이름 줄(125행)에 삭제 버튼 추가:

```javascript
  h+='<a class="name" href="/live/'+esc(s.code)+'">'+esc(s.name)+' 📡</a> <span class="code">'+esc(s.code)+'</span>';
  h+=' <button class="wdel" onclick="delStock(\''+esc(s.code)+'\')" title="관심종목에서 삭제">－</button>';
```

`searchRender`(151행)의 행 템플릿에 추가 버튼(이미 담긴 종목은 표시 안 함):

```javascript
  res.innerHTML=items.slice(0,30).map(u=>'<div class="srow"><span><a href="/live/'+esc(u.code)+'">'+esc(u.name)+' 📡</a> <span class="code">'+esc(u.code)+'</span>'
    +(WATCH.indexOf(u.code)<0?' <button class="wadd" onclick="addStock(\''+esc(u.code)+'\')">＋담기</button>':'')
    +'</span><span class="spx">'+(u.close!=null?won(u.close)+' ':'')+chg(u.change)+'</span></div>').join('');
```

JS 하단(loadPrices 아래)에 추가:

```javascript
// ── 관심종목 편집(설계 2026-07-16): 전체 교체 POST, 새 종목 맨 앞, 최소 1·최대 10 ──
const WATCH = D.stocks.map(s=>s.code);
async function saveWatch(codes){
  try{
    const r=await fetch('/api/watchlist',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({codes})});
    const d=await r.json();
    if(!r.ok){alert(d.error||'저장 실패');return;}
    location.reload();
  }catch(e){alert('저장 실패 — 네트워크를 확인하세요');}
}
function addStock(code){
  if(WATCH.indexOf(code)>=0)return;
  saveWatch([code].concat(WATCH));   // 새 종목 맨 앞 — 위젯 상위 5에 바로 보임
}
function delStock(code){
  if(WATCH.length<=1){alert('관심종목은 최소 1개 필요해요');return;}
  if(confirm('관심종목에서 삭제할까요?')) saveWatch(WATCH.filter(c=>c!==code));
}
```

CSS(카드/검색 버튼 — `_BASE_CSS` 뒤 페이지 고유 스타일 블록에):

```css
button.wadd,button.wdel{border:1px solid var(--border);background:var(--surface-2);
  color:var(--text-2);border-radius:var(--r-pill);font-size:12px;padding:2px 10px;
  min-height:28px;cursor:pointer;vertical-align:middle}
button.wdel{color:var(--up)}
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py tests/test_render.py -q`
Expected: 전부 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/report/dashboard.py tests/test_dashboard.py
git commit -m "feat(dashboard): 관심종목 편집 UI — 검색 ＋담기·카드 －삭제, 새 종목 맨 앞"
```

---

### Task 12: `fetch_live_prices` 동시 호출 제한(세마포어)

**Files:**
- Modify: `backend/cli.py:70-89`
- Test: `tests/test_prices.py` (추가)

**Interfaces:**
- Changes: `fetch_live_prices` 내부만(시그니처·반환 불변) — 동시 KIS 호출 ≤ 5.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_prices.py`에 추가:

```python
def test_fetch_live_prices_limits_concurrency(monkeypatch):
    """관심종목 10개 편집 시 KIS 버스트(초당 20건·간헐 500) 방어 — 동시 ≤5."""
    import asyncio
    from backend import cli

    peak = {"now": 0, "max": 0}

    class _FakeClient:
        async def price(self, code):
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
            await asyncio.sleep(0.01)
            peak["now"] -= 1
            return {"price": 100, "rate": 1.0}

    monkeypatch.setattr("backend.flow.candles._get_client", lambda: _FakeClient())
    codes = ["%06d" % i for i in range(10)]
    res = asyncio.run(cli.fetch_live_prices(codes))
    assert len(res) == 10 and peak["max"] <= 5
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_prices.py -x -q`
Expected: FAIL — `peak["max"] == 10`

- [ ] **Step 3: 구현** — `fetch_live_prices`의 `one` 정의부만 교체:

```python
    sem = asyncio.Semaphore(5)   # 동시 호출 제한 — 편집 후 최대 10종목 × 12초 폴링
                                 # × 위젯이 겹쳐도 KIS 간헐 500(EGW00201) 방어(설계)

    async def one(c):
        async with sem:
            try:
                p = await client.price(c)
                if p and p.get("price"):
                    return c, {"close": p["price"], "change": p.get("rate")}
            except Exception:
                pass
            return c, None
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_prices.py -q`
Expected: 전부 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/cli.py tests/test_prices.py
git commit -m "fix(prices): fetch_live_prices 동시 호출 세마포어(≤5) — KIS 간헐 500 방어"
```

---

### Task 13: 전체 검증 + 마무리

- [ ] **Step 1: 전체 테스트**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 전부 passed(신규 포함), 실패 0

- [ ] **Step 2: 실기기 확인(마스터와 함께)** — 대시보드에서 종목 ＋담기 → 위젯 ↻ 갱신 → 새 종목 표시 확인. MCP `watchlist_summary`·`stock-master report`도 새 목록 반영 확인.

- [ ] **Step 3: 스펙 상태 갱신 + 커밋**

`docs/superpowers/specs/2026-07-16-iphone-widget-design.md` 상태줄을 "구현 완료(1·2단계)"로 갱신, FHKST01010400 실측 결과(Task 7)를 스펙 §거래일 판별에 1줄 기록.

```bash
git add docs/superpowers/specs/2026-07-16-iphone-widget-design.md
git commit -m "docs(spec): 위젯 설계 — 구현 완료 상태·일자별 TR 실측 결과 기록"
```

---

## Self-Review 결과 (계획 작성 후 점검)

- **스펙 커버리지**: KIS 단일 소스(T3)·AuthGate Bearer(T4)·토큰 env fail-closed(T1)·Keychain/설치 페이지(T5)·↻ 갱신(T5)·가이드(T6)·거래일/공휴일(T2)·계약 화이트리스트(T3 테스트)·watchlist 5소비자(T10)·이름 해석(T9)·편집 UI 3결정(T8/T11)·세마포어(T12)·실측(T7) — 전 항목 태스크 매핑 확인.
- **자리표시자**: 없음(검증 워크플로 지적으로 T11 테스트를 실존 `render_dashboard`+`_stock()` 헬퍼로 교체 완료). T5의 `_BASE_CSS`/`_PWA_HEAD`는 scanner_page.py:10-11 import로 실존 확인.
- **검증 워크플로 반영(3렌즈, 2026-07-16)**: 401 재입력 안내 위젯(buildAuthError)·토큰 재입력 메뉴, Task 4 Step 2 기대 실패 사실 정정, node --check `.mjs`(node<22.7 호환), watchlist 테스트 5 passed 정정, 가이드 별칭 제약 고지.
- **타입 일관성**: `get_watchlist()->list[str]`·`widget_data(codes)->Optional[dict]`·`resolve_name(code,names)`·`assemble_stock(...,names=None)` 교차 참조 일치 확인. `_news_aliases`는 T9 정의 → T9 내 `_collect_issues`만 사용.
```
