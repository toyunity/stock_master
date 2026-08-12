# 변동성 지수(VKOSPI) 패널 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대시보드에 접힌 섹션 하나를 더해, 펼치면 VKOSPI 현재값과 최근 100거래일 추이 라인 차트를 보여준다.

**Architecture:** 기존 지수 칩과 같은 4계층 — 순수 파서(`flow/kis.py`) → KIS REST(`KisClient.index_daily`) → TTL 캐시(`api/marketdata.py`) → 섹션 렌더(`report/vol_panel.py` → `report/dashboard.py`). 한 번의 REST 호출이 현재값과 이력을 둘 다 준다. **섹션을 펼칠 때만 조회한다**(이 앱 최초의 지연 로딩 — 다른 섹션은 전부 즉시 로드다).

**Tech Stack:** Python 3.9 · FastAPI · httpx · pytest · 바닐라 JS + Canvas 2D(빌드 스텝 없음)

**Spec:** `docs/superpowers/specs/2026-08-05-vkospi-panel-design.md`

---

## Global Constraints

- **Python 3.9 호환** — `X | Y` 타입 문법·`match`·`str.removeprefix` 금지. `Optional[...]`, `from __future__ import annotations` 사용.
- **시각은 전부 KST** — `datetime.now()`/`date.today()` 금지, `backend.flow.kst.now()`/`kst.today()` 사용.
- **테스트는 KIS·네트워크 미접촉** — 가짜 클라이언트/주입 훅으로만.
- **웹소켓 미접촉** — REST 전용. 1키1세션은 `/live` 수급(`flow/wsbus.py`)이 쓴다.
- **8000 실서버 불가침** — 재기동이 필요하면 `.venv/bin/python`으로만.
- **색 관례** — 상승=빨강(`--up`), 하락=파랑(`--down`). 미국식 반대 색 금지.
- **개인용 유지** — 시세 재배포 금지.
- **정직성 규칙**(스펙 §정직성 규칙 — 리뷰의 1급 기준):
  - **기준선(20/30 등)을 지어내지 않는다.** 이 시장은 오늘 78, 100일 범위 48~97이다.
  - **백분위·상태 문구(평온/경계/공포)를 내지 않는다.** 해석은 차트가 한다.
  - 차트 밑 한 줄은 지표의 성질만 말한다 — `지수와 반대로 움직입니다`.
  - 모르는 값을 0이나 그럴듯한 숫자로 꾸미지 않는다(`None` → 화면 `–`).
- **테스트 실행** — `make test`. 단일 파일은 `.venv/bin/python -m pytest tests/test_vkospi.py -v`.
- **커밋 메시지** — 한국어 요약 + `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **scratchpad 커밋 금지.**

---

## 실측으로 확정된 값 (추측 금지)

구현자는 아래를 **그대로** 쓴다. 전부 2026-08-05에 실제로 재서 확인한 것이다.

| | 값 | 함정 |
|---|---|---|
| 지수 코드 | **`0503`** | `00503`(마스터 원본 5자리)을 넣으면 **`rt_cd=0`에 값이 `0.00`**으로 온다. 에러가 안 나서 조용히 틀린다 |
| TR | `FHPUP02120000` | |
| 경로 | `/uapi/domestic-stock/v1/quotations/inquire-index-daily-price` | `inquire-daily-indexprice`는 **존재하지 않는다**(JSON이 아닌 응답이 와서 파싱 예외) |
| 파라미터 | `FID_COND_MRKT_DIV_CODE=U` · `FID_INPUT_ISCD=0503` · `FID_INPUT_DATE_1=<오늘 YYYYMMDD>` · `FID_PERIOD_DIV_CODE=D` | |
| 현재값 | `output1` (dict, 20필드) | |
| 이력 | **`output2`** (list, 100행, **최신순**) | `output`은 `None`이다 |

응답 필드: `stck_bsop_date` · `bstp_nmix_prpr` · `bstp_nmix_prdy_vrss` · `bstp_nmix_prdy_ctrt` · `prdy_vrss_sign`

**실측 스냅샷(2026-08-05 19:40)**: 오늘 `78.55` · 전일대비 `-3.50`(−4.27%) ·
기간 `20260312`~`20260805`(100거래일) · 범위 최저 `48.51` 최고 `96.94` · 빈 행 0 ·
월 경계 6개(idx 0/14/36/54/75/97 = 3·4·5·6·7·8월).

---

## File Structure

| 파일 | 신규/수정 | 책임 |
|---|---|---|
| `backend/flow/kis.py` | 수정 | `parse_index_daily()` + `KisClient.index_daily()` |
| `backend/api/marketdata.py` | 수정 | `get_vkospi()` — TTL 60초 캐시 |
| `backend/api/app.py` | 수정 | `GET /api/vkospi` |
| `backend/report/vol_panel.py` | 신규 | 섹션 CSS/마크업/JS(지연 로딩 + 라인 차트) |
| `backend/report/dashboard.py` | 수정 | 자리표시자 3개 끼움 |
| `tests/test_vkospi.py` | 신규 | 파서 · TR 고정 · 캐시 |
| `tests/test_vol_panel_js.py` | 신규 | node 실행 — 지연 로딩·차트·라벨 |

`vol_panel.py`를 따로 두는 기준은 `options_panel.py`와 같다 — `dashboard.py`가 이미 710줄이다.

---

### Task 1: 순수 파서 + KIS 조회

**Files:**
- Modify: `backend/flow/kis.py` (`parse_index` 다음 / `KisClient.index` 다음)
- Test: `tests/test_vkospi.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `kis.parse_index_daily(js) -> Optional[dict]` — `{"now": {"price","change","rate","sign"}, "days": [{"d": "YYYYMMDD", "v": float}, ...]}`. **`days`는 오래된 → 최신 순**(응답은 최신순이므로 뒤집는다). 실패·빈 이력이면 `None`.
  - `kis.VKOSPI_ISCD = "0503"`
  - `KisClient.index_daily(iscd: str, date: str) -> Optional[dict]` — 위 dict

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_vkospi.py`:

```python
"""VKOSPI 일별 지수 — 순수 파싱 + TR 고정. KIS·네트워크 미접촉.

이 파일이 지키는 함정 3개(2026-08-05 실측):
  · 코드는 0503이지 00503이 아니다 — 00503은 rt_cd=0에 0.00이 와서 조용히 틀린다
  · 이력은 output2에 있다(output은 None)
  · 응답은 최신순이라 차트용으로 뒤집어야 한다
"""
import asyncio

from backend.flow import kis


def _js(dates_values, now=("78.55", "-3.50", "-4.27", "5")):
    """실측 응답 모양 — output1=현재 요약(dict), output2=일별(list, 최신순)."""
    px, chg, rate, sign = now
    return {"rt_cd": "0",
            "output1": {"bstp_nmix_prpr": px, "bstp_nmix_prdy_vrss": chg,
                        "bstp_nmix_prdy_ctrt": rate, "prdy_vrss_sign": sign},
            "output2": [{"stck_bsop_date": d, "bstp_nmix_prpr": v}
                        for d, v in dates_values]}


def test_parse_index_daily_reads_output2_and_reverses_to_oldest_first():
    js = _js([("20260805", "78.55"), ("20260804", "82.05"), ("20260803", "80.10")])
    d = kis.parse_index_daily(js)
    assert d["now"]["price"] == 78.55
    assert d["now"]["change"] == -3.50 and d["now"]["rate"] == -4.27
    assert d["now"]["sign"] == "down"
    # 차트는 왼쪽부터 그린다 — 응답의 최신순을 여기서 뒤집는다
    assert [x["d"] for x in d["days"]] == ["20260803", "20260804", "20260805"]
    assert [x["v"] for x in d["days"]] == [80.10, 82.05, 78.55]


def test_parse_index_daily_rejects_error_and_empty():
    assert kis.parse_index_daily({"rt_cd": "1", "msg1": "오류"}) is None
    assert kis.parse_index_daily({"rt_cd": "0", "output2": []}) is None
    assert kis.parse_index_daily({"rt_cd": "0"}) is None
    assert kis.parse_index_daily(None) is None


def test_parse_index_daily_skips_broken_rows_but_keeps_the_rest():
    """값이 비거나 숫자가 아닌 행은 버린다 — 차트에 0이 찍히면 없는 급락이 보인다."""
    js = _js([("20260805", "78.55"), ("20260804", ""), ("20260803", "abc"),
              ("20260802", "80.10")])
    d = kis.parse_index_daily(js)
    assert [x["d"] for x in d["days"]] == ["20260802", "20260805"]


def test_parse_index_daily_survives_missing_output1():
    """이력만 있고 현재 요약이 없어도 차트는 그릴 수 있어야 한다."""
    js = _js([("20260805", "78.55")])
    del js["output1"]
    d = kis.parse_index_daily(js)
    assert d["now"] is None and len(d["days"]) == 1


def test_vkospi_iscd_is_four_digits():
    """마스터(idxcode.mst)는 5자리 00503이지만 API는 4자리다.
    00503을 넣으면 rt_cd=0에 0.00이 와서 **에러 없이 조용히 틀린다**(2026-08-05 실측)."""
    assert kis.VKOSPI_ISCD == "0503"


def test_index_daily_uses_correct_tr_path_and_params():
    seen = {}

    class _C(kis.KisClient):
        async def _get(self, path, tr_id, params, retries=2):
            seen.update({"path": path, "tr": tr_id, "params": params})
            return _js([("20260805", "78.55")])

    c = _C("k", "s", "/tmp")
    d = asyncio.run(c.index_daily(kis.VKOSPI_ISCD, "20260805"))
    assert seen["tr"] == "FHPUP02120000"
    assert seen["path"].endswith("/quotations/inquire-index-daily-price")
    assert seen["params"] == {"FID_COND_MRKT_DIV_CODE": "U",
                              "FID_INPUT_ISCD": "0503",
                              "FID_INPUT_DATE_1": "20260805",
                              "FID_PERIOD_DIV_CODE": "D"}
    assert d["now"]["price"] == 78.55
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_vkospi.py -v`
Expected: FAIL — `AttributeError: module 'backend.flow.kis' has no attribute 'parse_index_daily'`

- [ ] **Step 3: 파서를 구현한다**

`backend/flow/kis.py` — `parse_index` 바로 다음에 추가:

```python
VKOSPI_ISCD = "0503"   # 코스피200 변동성지수.
# 지수 마스터(idxcode.mst)에는 5자리 '00503 VKOSPI'로 있지만 **API는 4자리**다
# (00001 종합→0001, 22001 KOSPI200→2001과 같은 규칙). 00503을 그대로 넣으면
# rt_cd=0에 값이 0.00으로 와서 에러 없이 조용히 틀린다(2026-08-05 실측).


def parse_index_daily(js) -> Optional[dict]:
    """inquire-index-daily-price(FHPUP02120000) → {'now': {...}|None, 'days': [...]}.

    **이력은 output2에 있다**(output은 None이다). 응답은 최신순이라 차트가 왼쪽부터
    그릴 수 있게 **여기서 뒤집는다** — 정렬 방향을 프론트까지 끌고 가지 않는다.
    값이 비거나 숫자가 아닌 행은 버린다: 차트에 0이 찍히면 없던 급락이 보인다."""
    if not isinstance(js, dict) or js.get("rt_cd") != "0":
        return None
    rows = js.get("output2") or []
    days = []
    for r in rows:
        d = (r.get("stck_bsop_date") or "").strip()
        raw = (r.get("bstp_nmix_prpr") or "").strip()
        if not d or not raw:
            continue
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        days.append({"d": d, "v": v})
    if not days:
        return None
    days.sort(key=lambda x: x["d"])            # 최신순 → 오래된 순
    o = js.get("output1") or {}
    now = None
    if o:
        now = {"price": _f(o.get("bstp_nmix_prpr")),
               "change": _f(o.get("bstp_nmix_prdy_vrss")),
               "rate": _f(o.get("bstp_nmix_prdy_ctrt")),
               "sign": _SIGN.get(str(o.get("prdy_vrss_sign", "")), "")}
    return {"now": now, "days": days}
```

- [ ] **Step 4: 조회 메서드를 구현한다**

`backend/flow/kis.py` — `KisClient.index` 바로 다음:

```python
    async def index_daily(self, iscd: str, date: str) -> Optional[dict]:
        """일별 지수(FHPUP02120000) — 한 번에 현재값 + 100거래일 이력.

        경로가 `inquire-index-daily-price`다. `inquire-daily-indexprice`는 존재하지
        않아 JSON이 아닌 응답이 오고 파싱에서 터진다(2026-08-05 실측)."""
        js = await self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-index-daily-price",
            "FHPUP02120000",
            {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": iscd,
             "FID_INPUT_DATE_1": date, "FID_PERIOD_DIV_CODE": "D"})
        return parse_index_daily(js)
```

- [ ] **Step 5: 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_vkospi.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: 커밋**

```bash
git add backend/flow/kis.py tests/test_vkospi.py
git commit -m "feat(vkospi): 일별 지수 파서 + 조회 — 코드는 0503, 이력은 output2

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: TTL 캐시 + API 라우트

**Files:**
- Modify: `backend/api/marketdata.py` (`get_indices` 다음)
- Modify: `backend/api/app.py` (`/api/market` 다음)
- Test: `tests/test_vkospi.py` (이어서)

**Interfaces:**
- Consumes: `kis.VKOSPI_ISCD` · `KisClient.index_daily`(Task 1)
- Produces:
  - `marketdata.get_vkospi(client=None, now=None) -> dict` — `{"now": {...}, "days": [...], "ts": epoch}` 또는 `{}`
  - `GET /api/vkospi`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_vkospi.py`에 이어서:

```python
import pytest


class _FakeVk:
    """index_daily 호출 횟수를 세는 가짜 클라이언트."""

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    async def index_daily(self, iscd, date):
        self.calls += 1
        assert iscd == "0503"          # 4자리 — 5자리를 넘기면 조용히 0.00이 온다
        if self.fail:
            raise RuntimeError("KIS 죽음")
        return {"now": {"price": 78.55, "change": -3.5, "rate": -4.27, "sign": "down"},
                "days": [{"d": "20260804", "v": 82.05}, {"d": "20260805", "v": 78.55}]}


@pytest.fixture(autouse=True)
def _reset_vk():
    from backend.api import marketdata as md
    md._vk_cache.update({"ts": 0.0, "data": None})
    yield
    md._vk_cache.update({"ts": 0.0, "data": None})


def test_get_vkospi_returns_now_and_days_and_caches():
    from backend.api import marketdata as md
    c = _FakeVk()
    d = asyncio.run(md.get_vkospi(client=c))
    assert d["now"]["price"] == 78.55 and len(d["days"]) == 2
    assert d["ts"] > 0
    asyncio.run(md.get_vkospi(client=c))          # 60초 캐시
    assert c.calls == 1


def test_get_vkospi_keeps_last_value_on_failure():
    """조회가 실패해도 직전값을 보여준다 — 빈 섹션보다 낫다."""
    from backend.api import marketdata as md
    asyncio.run(md.get_vkospi(client=_FakeVk()))
    md._vk_cache["ts"] = 0.0                       # TTL 만료
    d = asyncio.run(md.get_vkospi(client=_FakeVk(fail=True)))
    assert d["now"]["price"] == 78.55


def test_get_vkospi_empty_when_cold_and_failing():
    from backend.api import marketdata as md
    assert asyncio.run(md.get_vkospi(client=_FakeVk(fail=True))) == {}


def test_get_vkospi_empty_without_key(monkeypatch):
    from backend.api import marketdata as md
    monkeypatch.setattr(md, "_client", lambda: None)
    assert asyncio.run(md.get_vkospi()) == {}


def test_vkospi_route_returns_empty_without_key(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
    from backend.config import settings
    monkeypatch.setattr(settings, "kis_app_key", None)
    with TestClient(create_app()) as c:
        r = c.get("/api/vkospi")
    assert r.status_code == 200 and r.json() == {}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_vkospi.py -v`
Expected: FAIL — `AttributeError: module 'backend.api.marketdata' has no attribute '_vk_cache'`

- [ ] **Step 3: 캐시를 구현한다**

`backend/api/marketdata.py` — `get_indices` 다음에 추가:

```python
_VK_TTL = 60.0            # 변동성지수 60초. 지연 로딩이라 폭주 위험이 낮다.
_vk_cache = {"ts": 0.0, "data": None}


async def get_vkospi(client=None, now=None):
    """코스피200 변동성지수(VKOSPI) — 현재값 + 최근 100거래일. 60초 캐시.

    한 번의 호출이 현재값과 이력을 둘 다 준다(TR이 output1/output2로 함께 준다).
    화면에서는 **섹션을 펼칠 때만** 부르므로(지연 로딩) 대시보드를 열 때마다 나가는
    호출이 늘지 않는다. 장중/장외를 나누지 않는다 — 한 건짜리 호출에 세션 규칙을
    새로 만들 값어치가 없고, 옵션 마감(15:45)이 이 지수에도 그대로 적용되는지는
    확인하지 않았다(추측하지 않는다).

    실패하면 직전값을 그대로 준다. 콜드 상태로 실패하면 {} → 섹션이 통째로 숨는다."""
    from backend.flow import kis, kst
    client = client or _client()
    if client is None:
        return _vk_cache["data"] or {}
    if _vk_cache["data"] is not None and time.time() - _vk_cache["ts"] < _VK_TTL:
        return _vk_cache["data"]
    try:
        d = await client.index_daily(kis.VKOSPI_ISCD,
                                     (now or kst.now()).strftime("%Y%m%d"))
    except Exception:
        return _vk_cache["data"] or {}
    if not d or not d.get("days"):
        return _vk_cache["data"] or {}
    out = dict(d)
    out["ts"] = time.time()
    _vk_cache["ts"], _vk_cache["data"] = out["ts"], out
    return out
```

- [ ] **Step 4: 라우트를 구현한다**

`backend/api/app.py` — `/api/market` 다음:

```python
    @app.get("/api/vkospi")
    async def vkospi_api():
        """코스피200 변동성지수 — 현재값 + 최근 100거래일. 섹션을 펼칠 때만 호출된다.
        키없음/실패면 {} — 프론트가 섹션을 숨긴다."""
        from backend.api import marketdata
        return JSONResponse(await marketdata.get_vkospi() or {})
```

- [ ] **Step 5: 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_vkospi.py -v`
Expected: PASS (11 passed)

- [ ] **Step 6: 커밋**

```bash
git add backend/api/marketdata.py backend/api/app.py tests/test_vkospi.py
git commit -m "feat(vkospi): 60초 캐시 + GET /api/vkospi

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 섹션 + 지연 로딩 (차트는 자리막이)

**Files:**
- Create: `backend/report/vol_panel.py`
- Modify: `backend/report/dashboard.py`
- Test: `tests/test_dashboard.py` (마크업 사실 확인)

**Interfaces:**
- Consumes: `GET /api/vkospi`(Task 2)
- Produces:
  - `vol_panel.CSS` · `vol_panel.HTML` · `vol_panel.JS`
  - `dashboard._TEMPLATE`에 `__VOL_CSS__`·`__VOL_HTML__`·`__VOL_JS__` 자리
  - `vkDraw(cv, d)` — 이 태스크에선 **빈 함수**. 차트는 Task 4.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_dashboard.py`에 추가:

```python
def test_dashboard_has_collapsed_vkospi_section_that_is_not_open():
    """VKOSPI 섹션은 **기본 접힘**이고, 펼치기 전엔 조회하지 않는다(지연 로딩).

    다른 섹션(반도체 동향 등)은 즉시 로드지만 이건 다르다 — 안 펼치면 KIS 호출 0건이
    이 설계의 약속이다."""
    from backend.report.dashboard import render_dashboard
    html = render_dashboard([], [], "2026-08-05")
    assert 'id="volsec"' in html
    head = html.split('id="volsec"')[1].split(">")[0]
    assert "open" not in head                       # 기본 접힘
    assert 'id="vk-chart"' in html and 'id="vk-now"' in html
    assert "loadVkospi" in html
    # 즉시 호출하는 코드가 없어야 한다(다른 로더는 파일 끝에서 바로 부른다)
    assert "loadVkospi();" not in html
    assert "addEventListener('toggle'" in html
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: FAIL — `assert 'id="volsec"' in html`

- [ ] **Step 3: `vol_panel.py`를 만든다**

`backend/report/vol_panel.py`:

```python
from __future__ import annotations

"""대시보드 변동성지수(VKOSPI) 섹션 — CSS·마크업·JS 세 조각.

dashboard.py에서 분리한 이유는 크기다(dashboard.py가 이미 710줄이고 차트가 붙으면
100줄쯤 는다). options_panel.py와 같은 기준. 문자열만 내보내고 파이썬 로직은 없다."""

CSS = """
#volsec .vknow{display:flex;align-items:baseline;gap:8px;margin:10px 0 2px}
#volsec .vkv{font-family:var(--font-num);font-variant-numeric:tabular-nums;
  font-size:28px;font-weight:700;color:var(--text);letter-spacing:-.02em}
#volsec .vkd{font-family:var(--font-num);font-variant-numeric:tabular-nums;
  font-size:13px;font-weight:700}
#volsec .vkd.up{color:var(--up)} #volsec .vkd.down{color:var(--down)}
#volsec .vkd.flat{color:var(--flat)}
/* 높이를 CSS로 고정한다 — JS가 백킹스토어(cv.height)를 dpr배로 키워도 박스는
   그대로여야 한다. height 속성만 믿으면 리사이즈마다 섹션이 늘어난다. */
#vk-chart{width:100%;height:180px;display:block;margin-top:6px}
#volsec .vkfoot{margin-top:8px}
"""

HTML = """
<details class="sec" id="volsec">
  <summary><svg class="hic secic"><use href="#i-activity"/></svg> 변동성 · VKOSPI
    <span class="seccap" id="vk-cap">펼치면 조회</span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="vknow" id="vk-now"></div>
    <canvas id="vk-chart" height="180" data-h="180"></canvas>
    <div class="meta vkfoot" id="vk-foot"></div>
  </div>
</details>
"""

JS = r"""
// ── 변동성지수(VKOSPI) — **펼칠 때만 조회한다**(이 앱 최초의 지연 로딩). ──
// 안 펼치면 KIS 호출 0건. 대시보드를 열 때마다 나가는 호출을 늘리지 않는 게 요점이다.
function vkNum(n, d){ return n==null ? '–' : Number(n).toLocaleString('ko-KR',
  {minimumFractionDigits:d||0, maximumFractionDigits:d||0}); }

function vkDraw(cv, d){ window.__vkLast = d; }   // Task 4에서 구현

let vkLoaded = false;
async function loadVkospi(){
  let d = null;
  try{
    const r = await fetch('/api/vkospi');
    if(r && r.ok) d = await r.json();
  }catch(e){}
  const sec = document.getElementById('volsec');
  if(!sec) return;
  // 보여줄 게 없으면 섹션을 통째로 숨긴다(기업 체력·옵션 패널과 같은 관행).
  if(!d || !(d.days||[]).length){ sec.style.display='none'; return; }
  vkLoaded = true;

  const cap = document.getElementById('vk-cap');
  if(cap) cap.textContent = '최근 ' + d.days.length + '거래일';

  const n = d.now || {};
  const el = document.getElementById('vk-now');
  if(el){
    const cls = n.rate>0?'up':(n.rate<0?'down':'flat');
    const ar = n.rate>0?'▲':(n.rate<0?'▼':'·');
    el.innerHTML = '<span class="vkv">'+vkNum(n.price,2)+'</span>'
      + '<span class="vkd '+cls+'">'+ar+' '+vkNum(Math.abs(n.change||0),2)
      + ' ('+(n.rate==null?'–':vkNum(Math.abs(n.rate),2)+'%')+')</span>';
  }

  vkDraw(document.getElementById('vk-chart'), d);

  const foot = document.getElementById('vk-foot');
  // 기준선(20/30 등)을 말하지 않는다 — 이 시장은 오늘 78이고 100일 범위가 48~97이다.
  // 교과서 기준을 갖다 붙이면 틀린 말이 된다. 지표의 성질만 알려준다.
  if(foot) foot.textContent = '최근 ' + d.days.length + '거래일 · 지수와 반대로 움직입니다';
}

// 펼칠 때 딱 한 번만 조회한다. 접었다 폈다 해도 다시 안 부른다(서버 TTL 60초와 별개로
// 프론트에서도 막는다 — 토글은 사용자가 얼마든지 연타할 수 있다).
(function(){
  const sec = document.getElementById('volsec');
  if(!sec) return;
  sec.addEventListener('toggle', function(){
    if(sec.open && !vkLoaded) loadVkospi();
  });
})();
window.addEventListener('resize', function(){
  if(window.__vkLast) vkDraw(document.getElementById('vk-chart'), window.__vkLast);
});
"""
```

- [ ] **Step 4: `dashboard.py`에 끼운다**

1. 임포트에 추가 — `from backend.report import vol_panel as _volp`
2. `_TEMPLATE`의 `__OPT_CSS__` 다음 줄에 `__VOL_CSS__`
3. `__OPT_HTML__` **다음**에 `__VOL_HTML__`(옵션 섹션 아래, 관심종목 카드 위)
4. `__OPT_JS__` 다음에 `__VOL_JS__`
5. `render_dashboard`의 치환 체인에 추가:

```python
            .replace("__VOL_CSS__", _volp.CSS)
            .replace("__VOL_HTML__", _volp.HTML)
            .replace("__VOL_JS__", _volp.JS)
```

- [ ] **Step 5: 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add backend/report/vol_panel.py backend/report/dashboard.py tests/test_dashboard.py
git commit -m "feat(vkospi): 대시보드 섹션 — 기본 접힘 + 펼칠 때만 조회

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 라인 차트 (월 눈금) + node 실행 테스트

**Files:**
- Modify: `backend/report/vol_panel.py` (`vkDraw` 구현)
- Test: `tests/test_vol_panel_js.py` (신규)

**Interfaces:**
- Consumes: Task 3의 `vkDraw(cv, d)` 호출 규약 — `d = {"now": {...}, "days": [{"d","v"}...]}`
- Produces: 그려진 캔버스. 반환값 없음.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_vol_panel_js.py`:

```python
"""VKOSPI 섹션 JS 실행 스모크 — node로 실제 실행한다.

캔버스가 없는 환경이라 2D 컨텍스트를 기록용 스텁으로 대신하고, 어떤 도형이 어디에
그려졌는지를 단언한다. 옵션 차트에서 스크린샷으로만 잡혔던 결함 3개(라벨 잘림·
라벨 겹침·캔버스 부풀기)를 여기선 처음부터 테스트로 막는다.
"""
import json
import shutil
import subprocess

import pytest

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 미설치 — JS 실행 스모크 생략")

_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const payload = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const openIt = process.argv[4] === 'open';
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(s => s.indexOf('loadVkospi') >= 0);
if (!code) { console.log(JSON.stringify({error: 'loadVkospi 스크립트 없음'})); process.exit(0); }

const ops = [];
let fetches = 0;
function ctx(){
  const o = {};
  const rec = name => function(){ ops.push([name].concat([...arguments])); };
  ['clearRect','fillRect','beginPath','moveTo','lineTo','stroke','fill','arc',
   'fillText','setTransform','closePath','save','restore'].forEach(n => o[n] = rec(n));
  ['fillStyle','strokeStyle','lineWidth','globalAlpha','font','textAlign','textBaseline']
    .forEach(k => Object.defineProperty(o, k, {set(){}, get(){ return ''; }}));
  return o;
}
const attrs = {};
const validIds = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));
const els = {};
let toggleFn = null;
function mk(id){
  const e = {id, textContent:'', innerHTML:'', className:'', style:{}, clientWidth: 340,
             open: false, addEventListener: (t, f) => { if (t === 'toggle') toggleFn = f; }};
  if (id === 'vk-chart') {
    attrs[id] = {height: '180', 'data-h': '180'};
    e.getAttribute = k => (k in attrs[id] ? attrs[id][k] : null);
    Object.defineProperty(e, 'height', {
      set(v){ attrs[id].height = String(v); }, get(){ return +attrs[id].height; }});
    Object.defineProperty(e, 'width', {
      set(v){ attrs[id].width = String(v); }, get(){ return +(attrs[id].width||0); }});
    e.getContext = () => ctx();
  }
  return e;
}
global.document = {
  getElementById: id => validIds.has(id) ? (els[id] || (els[id] = mk(id))) : null,
  querySelectorAll: () => [],
  documentElement: {},
};
global.window = {devicePixelRatio: 2, addEventListener: () => {}, __vkLast: null};
global.getComputedStyle = () => ({getPropertyValue: k =>
  ({'--up':'#e5342f','--down':'#1f66e0','--border':'#dcdfe6','--text-3':'#8b93a4',
    '--text':'#1a1d24'}[k] || '')});
global.setInterval = () => 0;
global.fetch = async () => { fetches++; return {ok: true, json: async () => payload}; };

(async () => {
  try {
    eval(code);
    await new Promise(r => setTimeout(r, 20));
    const before = fetches;                    // 펼치기 전 호출 수
    if (openIt && toggleFn) { els['volsec'].open = true; toggleFn(); 
                              await new Promise(r => setTimeout(r, 30));
                              els['volsec'].open = false; toggleFn();
                              els['volsec'].open = true; toggleFn();
                              await new Promise(r => setTimeout(r, 20)); }
    const h1 = attrs['vk-chart'] ? attrs['vk-chart'].height : null;
    if (typeof vkDraw === 'function' && els['vk-chart'] && window.__vkLast)
      vkDraw(els['vk-chart'], window.__vkLast);
    const h2 = attrs['vk-chart'] ? attrs['vk-chart'].height : null;
    console.log(JSON.stringify({
      ok: true, fetchesBeforeOpen: before, fetchesTotal: fetches,
      now: (els['vk-now']||{}).innerHTML || '',
      cap: (els['vk-cap']||{}).textContent || '',
      foot: (els['vk-foot']||{}).textContent || '',
      display: ((els['volsec']||{}).style||{}).display,
      h1, h2, ops,
    }));
  } catch (e) { console.log(JSON.stringify({error: String(e && e.stack || e)})); }
})();
"""


def _run(tmp_path, payload, open_it=True):
    from backend.report.dashboard import render_dashboard
    html = tmp_path / "dash.html"
    html.write_text(render_dashboard([], [], "2026-08-05"), encoding="utf-8")
    data = tmp_path / "vk.json"
    data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    js = tmp_path / "h.js"
    js.write_text(_HARNESS, encoding="utf-8")
    out = subprocess.run(["node", str(js), str(html), str(data),
                          "open" if open_it else "closed"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert "error" not in res, res["error"]
    return res


def _payload():
    """실측 모양 — 100거래일, 월 경계 6개(3·4·5·6·7·8월), 마지막 월이 끝 근처."""
    days, v = [], 60.0
    dates = ([("202603%02d" % d) for d in range(12, 32)][:14]
             + ["202604%02d" % d for d in range(1, 23)]
             + ["202605%02d" % d for d in range(4, 22)]
             + ["202606%02d" % d for d in range(1, 22)]
             + ["202607%02d" % d for d in range(1, 23)]
             + ["202608%02d" % d for d in (3, 4, 5)])
    for i, d in enumerate(dates[:100]):
        v = 48.51 + (96.94 - 48.51) * (0.5 + 0.45 * ((i % 17) / 17.0 - 0.5) * 2)
        days.append({"d": d, "v": round(v, 2)})
    days[-1]["v"] = 78.55
    return {"now": {"price": 78.55, "change": -3.5, "rate": -4.27, "sign": "down"},
            "days": days, "ts": 1786000000.0}


@needs_node
def test_does_not_fetch_before_the_section_is_opened(tmp_path):
    """**이 설계의 핵심 약속** — 안 펼치면 KIS 호출 0건이다."""
    res = _run(tmp_path, _payload(), open_it=False)
    assert res["fetchesBeforeOpen"] == 0 and res["fetchesTotal"] == 0


@needs_node
def test_fetches_once_no_matter_how_many_times_it_is_toggled(tmp_path):
    """토글은 연타할 수 있다 — 펼칠 때마다 부르면 안 된다."""
    res = _run(tmp_path, _payload())
    assert res["fetchesTotal"] == 1


@needs_node
def test_renders_value_and_line_chart(tmp_path):
    res = _run(tmp_path, _payload())
    assert "78.55" in res["now"] and "4.27%" in res["now"]
    assert "100거래일" in res["cap"]
    assert "지수와 반대로 움직입니다" in res["foot"]
    assert len([o for o in res["ops"] if o[0] == "lineTo"]) >= 99   # 100점 라인
    assert len([o for o in res["ops"] if o[0] == "arc"]) == 1       # 오늘 마커 1개


@needs_node
def test_x_axis_has_month_labels(tmp_path):
    """양 끝 날짜만 찍으면 '언제 튀었나'를 못 읽는다 — 월 눈금이 있어야 한다."""
    res = _run(tmp_path, _payload())
    texts = [o[1] for o in res["ops"] if o[0] == "fillText"]
    months = [t for t in texts if str(t).endswith("월")]
    assert len(months) >= 4, texts


@needs_node
def test_month_label_does_not_collide_with_the_today_marker(tmp_path):
    """마지막 월 경계는 항상 오른쪽 끝 근처다(월초는 늘 최근이다) — 예외가 아니라 기본이다."""
    res = _run(tmp_path, _payload())
    texts = [o for o in res["ops"] if o[0] == "fillText"]
    months = [o for o in texts if str(o[1]).endswith("월")]
    marker = [o for o in texts if "78.5" in str(o[1])]
    assert months and marker
    for m in months:
        for k in marker:
            close_x = abs(m[2] - k[2]) < 34      # 라벨 폭만큼 가까운데
            same_y = abs(m[3] - k[3]) < 12       # 같은 높이면 겹친다
            assert not (close_x and same_y), "월 라벨과 마커 라벨이 겹친다 %s %s" % (m, k)


@needs_node
def test_all_text_stays_inside_the_canvas(tmp_path):
    """앵커만이 아니라 글리프 박스까지 — 10px 폰트라 상하 12px 여백을 요구한다."""
    res = _run(tmp_path, _payload())
    ys = [o[3] for o in res["ops"] if o[0] == "fillText"]
    xs = [o[2] for o in res["ops"] if o[0] == "fillText"]
    assert ys and min(ys) >= 12 and max(ys) <= 180 - 12 + 3, ys
    assert min(xs) >= 0 and max(xs) <= 340, xs


@needs_node
def test_redraw_does_not_inflate_the_canvas(tmp_path):
    """cv.height 대입이 height 속성을 덮어쓴다 — 의도한 높이는 data-h에서 읽어야 한다.
    옵션 차트에서 190→570→1710으로 부푼 적 있다."""
    res = _run(tmp_path, _payload())
    assert res["h1"] == res["h2"], "재렌더에 캔버스가 부풀었다 %s → %s" % (res["h1"], res["h2"])
    assert int(res["h1"]) == 180 * 2


@needs_node
def test_section_hides_itself_when_there_is_no_data(tmp_path):
    res = _run(tmp_path, {"now": None, "days": []})
    assert res["display"] == "none"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_vol_panel_js.py -v`
Expected: FAIL — 자리막이 `vkDraw`가 아무것도 안 그린다(`lineTo` 0개)

- [ ] **Step 3: `vkDraw`를 구현한다**

`backend/report/vol_panel.py`의 `JS`에서 자리막이를 지우고 그 자리에:

```javascript
// ── 100거래일 라인 차트. 가로축은 월 눈금, 세로축은 최저·최고만. ──
// 세로 눈금을 촘촘히 달면 390px에서 겹친다(옵션 차트에서 겪었다). 가로 라벨을
// 살리는 대신 세로는 양 끝만 둔다.
function vkDraw(cv, d){
  window.__vkLast = d;
  if(!cv || !cv.getContext) return;
  const days = d.days || [];
  if(days.length < 2) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 340;
  // 의도한 CSS 높이는 data-h에서 읽는다 — height 속성은 아래에서 우리가 덮어쓰므로
  // 거기서 되읽으면 다시 그릴 때마다 dpr배로 부푼다.
  const h = parseInt(cv.getAttribute('data-h'), 10) || 180;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);

  const cs = getComputedStyle(document.documentElement);
  const CV = k => (cs.getPropertyValue(k) || '').trim();
  const LN = CV('--border') || '#dcdfe6', TX = CV('--text-3') || '#8b93a4';
  const INK = CV('--text') || '#1a1d24';
  const n = d.now || {};
  const ACC = (n.rate > 0 ? (CV('--up') || '#e5342f') : (CV('--down') || '#1f66e0'));

  const padL = 34, padR = 8, padT = 12, padB = 18;   // padL은 세로축 값 라벨 자리
  const vals = days.map(x => x.v);
  let lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  if(hi === lo){ hi = lo + 1; }
  const X = i => padL + i / (days.length - 1) * (w - padL - padR);
  const Y = v => padT + (1 - (v - lo) / (hi - lo)) * (h - padT - padB);

  // 월 경계 — **달력이 아니라 데이터에서** 월이 바뀌는 첫 행으로 잡는다.
  // 휴장일 때문에 1일이 데이터에 없다(실측: 5월 경계가 5/4, 8월이 8/3).
  const marks = [];
  let prev = null;
  days.forEach(function(x, i){
    const m = String(x.d).slice(4, 6);
    if(m !== prev){ marks.push({i: i, m: parseInt(m, 10)}); prev = m; }
  });

  // 월 격자선(옅게) — 눈이 구간을 나눠 읽게 하는 용도
  g.strokeStyle = LN; g.lineWidth = 1;
  marks.forEach(function(k){
    if(k.i === 0) return;                    // 왼쪽 끝엔 선을 긋지 않는다
    g.globalAlpha = 0.45;
    g.beginPath(); g.moveTo(X(k.i), padT); g.lineTo(X(k.i), h - padB); g.stroke();
    g.globalAlpha = 1;
  });

  // 라인
  g.strokeStyle = ACC; g.lineWidth = 1.6;
  g.beginPath();
  days.forEach(function(x, i){ i ? g.lineTo(X(i), Y(x.v)) : g.moveTo(X(i), Y(x.v)); });
  g.stroke();

  // 오늘 마커 + 값
  const last = days.length - 1, ly = Y(days[last].v);
  g.fillStyle = ACC;
  g.beginPath(); g.arc(X(last), ly, 3, 0, Math.PI * 2); g.fill();
  g.font = '600 10px system-ui, sans-serif';
  g.textAlign = 'right'; g.textBaseline = 'bottom';
  // 라벨은 마커 위가 기본. 천장에 닿으면 아래로 접는다(옵션 차트와 같은 규칙).
  let ty = ly - 6, tb = 'bottom';
  if(ty < 14){ ty = ly + 6; tb = 'top'; }
  g.textBaseline = tb;
  g.fillStyle = INK;
  g.fillText(vkNum(days[last].v, 2), w - padR, Math.min(h - padB - 2, Math.max(14, ty)));

  // 세로축 — 최저·최고만
  g.fillStyle = TX; g.font = '10px system-ui, sans-serif';
  g.textAlign = 'left'; g.textBaseline = 'middle';
  g.fillText(vkNum(hi, 1), 2, Math.max(12, padT));
  g.fillText(vkNum(lo, 1), 2, Math.min(h - padB, h - padB - 1));

  // 가로축 월 라벨. 마지막 월 경계는 늘 오른쪽 끝 근처라(월초는 항상 최근이다)
  // 마커 값 라벨과 같은 높이에 오면 안 된다 — 월 라벨은 축(아래쪽)에, 마커 값은
  // 라인 근처(위쪽)에 둔다. 위 마커 라벨의 y는 항상 h-padB-2 이하다.
  g.textAlign = 'center'; g.textBaseline = 'top';
  marks.forEach(function(k){
    const x = Math.min(w - padR - 10, Math.max(padL + 10, X(k.i)));
    g.fillText(k.m + '월', x, h - padB + 4);
  });
}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_vol_panel_js.py -v`
Expected: PASS (8 passed — node 없으면 skip)

- [ ] **Step 5: 전체 스위트**

Run: `make test`
Expected: 전부 PASS

- [ ] **Step 6: 아이폰 폭 스크린샷으로 눈 검증**

데모 서버는 KIS 키를 차단하므로 섹션이 스스로 숨는다. 실데이터 모양을 보려면
스크래치패드에 주입 스크립트를 만들어 CDP로 찍는다(옵션 차트에서 쓴 `opt_shot.py`와 같은 방식,
**커밋 금지**). 확인할 것:

1. 월 라벨(3~8월)이 안 겹치고 캔버스 안에 있다
2. 오늘 마커 값이 잘리지 않는다
3. 다크 모드에서 라인·격자선이 보인다
4. 가로 스크롤이 안 생긴다(`document.documentElement.scrollWidth === 390`)
5. **접힌 상태로 로드했을 때 네트워크 요청이 안 나간다**(CDP `Network.requestWillBeSent` 확인)

- [ ] **Step 7: 커밋**

```bash
git add backend/report/vol_panel.py tests/test_vol_panel_js.py
git commit -m "feat(vkospi): 100거래일 라인 차트 — 월 눈금, 오늘 마커

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 실서버 반영 + 실측 기록

**Files:**
- Modify: `docs/superpowers/specs/2026-08-05-vkospi-panel-design.md`

**Interfaces:** 없음(검증·기록).

- [ ] **Step 1: main 병합 후 재기동**

```bash
cd <repo>
git merge --no-ff feat/index-futures
P=$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t | head -1); kill -TERM $P
# graceful 종료 대기 후
nohup .venv/bin/python -m backend.cli serve --host 0.0.0.0 --port 8000 >> data/serve-8000.log 2>&1 &
```

- [ ] **Step 2: 대시보드에서 확인**

접힌 상태로 떠 있는지 → 펼치면 값과 차트가 나오는지 → 접었다 펴도 다시 조회하지 않는지.

- [ ] **Step 3: 실측 결과를 스펙에 적는다**

`## 실제 출하` 절을 만들어 **관측된 값**을 적는다. 계획대로 안 된 것이 있으면 그것도 적는다.

- [ ] **Step 4: 커밋**

```bash
git add docs/
git commit -m "docs(vkospi): 실서버 실측 결과 기록

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## 자체 검토 결과

**스펙 커버리지**

| 스펙 절 | 태스크 |
|---|---|
| §실측 확정 — 코드 `0503`·TR·파라미터 | T1(상수·TR 고정 테스트) |
| §실측 확정 — `output2`, 최신순 뒤집기 | T1(`parse_index_daily`) |
| §화면 — 접힌 섹션, 펼칠 때 조회 | T3 |
| §화면 — 현재값 표시 | T3 |
| §화면 — 라인 차트·월 눈금·격자선·마커 | T4 |
| §화면 — 세로축 최저/최고만 | T4 |
| §정직성 — 기준선·백분위 안 냄 | T3(각주 문구), 리뷰 기준 |
| §정직성 — "지수와 반대로 움직입니다" | T3 |
| §아키텍처 4계층 | T1·T2·T3 |
| §데이터 흐름 — 지연 로딩, TTL 60초 | T2(서버) · T3(프론트) |
| §에러 처리 — 섹션 독립 실패·직전값 유지 | T2·T3 |
| §테스트 — 파서·캐시·TR·차트·지연로딩 | T1·T2·T4 |

**작성 중 잡은 문제 3개**

1. **지연 로딩은 서버 TTL만으로 못 지킨다.** `<details>` 토글은 사용자가 연타할 수 있어서, 프론트에도 `vkLoaded` 플래그가 있어야 "한 번만"이 성립한다. T4에 연타 회귀 테스트를 넣었다.
2. **월 라벨과 마커 라벨의 충돌은 예외가 아니라 기본이다.** 월초는 항상 최근이라 마지막 월 경계가 늘 오른쪽 끝 근처다(실측 idx 97 vs 99). 그래서 "겹치면 피한다"가 아니라 **애초에 다른 높이에 놓는다** — 월 라벨은 축 아래, 마커 값은 라인 근처. T4 테스트가 이걸 고정한다.
3. **`padL`이 필요하다.** 세로축 값 라벨(`96.9`)을 캔버스 왼쪽에 놓으려면 라인 시작점을 밀어야 한다. 안 밀면 라벨이 라인 위에 겹쳐 찍힌다.

**의도적으로 남긴 간극 2개**

- **세션별 TTL 없음.** 옵션 마감(15:45)이 이 지수에도 적용되는지 확인하지 않았다. 한 건짜리 호출이라 60초 고정으로 두고, 확인되면 그때 나눈다(추측으로 규칙을 만들지 않는다).
- **기간 선택 없음.** TR이 100행 고정이라 고를 수 있는 게 아니다. 더 긴 이력이 필요하면 `FID_INPUT_DATE_1`을 과거로 밀어 여러 번 부르는 별도 설계가 필요하고, 지금은 YAGNI다.

**타입 일관성 확인** — `parse_index_daily`가 내는 키(`now`/`days`, `days[i].d`/`.v`)가 T2 캐시, T3 JS(`d.days`, `d.now`), T4 차트(`x.d`/`x.v`)에서 모두 일치한다. `vkNum(n, d)`는 T3에서 정의하고 T4가 쓴다.
