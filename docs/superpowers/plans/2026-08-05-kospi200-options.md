# 코스피200 옵션 — 미결제 분포 차트 + 오늘의 증감 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대시보드에 코스피200 옵션 섹션을 추가한다. 행사가별 **당일 증감** 차트(주인공)와 **누적 미결제** 차트(맥락), 그리고 숫자 3개(풋콜 비율·ATM 내재변동성·풋 벽)를 보여준다.

**Architecture:** 선물 칩과 같은 4계층 — 순수 파서(`flow/optmaster.py`·`flow/options.py`) → KIS REST(`flow/kis.py`) → 배치 수집 + TTL 캐시(`api/marketdata.py`) → 섹션 렌더(`report/options_panel.py` → `report/dashboard.py`). 전광판 TR이 보드의 일부(행사가 내림차순 상위 100행)만 주므로 **종목마스터에서 전 종목 코드를 얻어 단건 시세를 도는** 방식이다. 한 회차가 최대 1,012건·약 3.5분이라 요청을 붙잡지 않고 백그라운드로 돌린다.

**Tech Stack:** Python 3.9 · FastAPI · httpx · pytest · 바닐라 JS + Canvas 2D(빌드 스텝 없음)

**Spec:** `docs/superpowers/specs/2026-08-05-kospi200-options-design.md`

---

## 진행 상태 (2026-08-05 16:50 KST)

| 태스크 | 상태 | 커밋 |
|---|---|---|
| T1 마스터 파싱 | ✅ 8테스트 + **실파일 검증** | `6d60233` |
| T2 지표 순수함수 | ✅ 14테스트 | `5e78a2e` |
| T3 단건시세 TR + 유량제어 | ✅ 7테스트 | `697c647` |
| T4 회차수집·TTL·백그라운드 | ✅ 8테스트 + **실체인 배선 검증** | `7415ccd` |
| T5 `/api/options` | ✅ | `bca5a36` |
| T6 섹션(요약줄·숫자 3개) | ✅ | `59582b4` |
| T7 Canvas 차트 2개 | ✅ 10테스트 + CDP 스크린샷 | `8927037` |
| T8 장중 실측 | ⏸ **장 마감(15:45)으로 대기** | — |

전체 스위트 535건 통과.

**KIS 없이 미리 검증한 것**(마스터는 공개 파일이라 키가 필요 없다):

- 실제 `fo_idx_code.mst`(1.19MB) 파싱 → **옵션 5,224행 · 만기 11종**. 만기 11종은
  스펙이 만기목록 TR로 얻는다던 개수와 같다 — TR을 뺀 결정(§변경 ①)이 옳았다.
- 근월물 `202608`, 만기일 **2026-08-13**(둘째 목요일) 자동 선택.
- **콜 390 · 풋 390 = 780건**, 행사가 **625.0 ~ 1597.5** — 2026-08-05 실조회와 정확히 일치.
- 차월물 `202609`는 **506+506 = 1,012건** — 스펙의 유량 계획(최대 1,012)과 일치.
- `_collect_options`를 실제 780종목 체인 + 가짜 응답으로 완주: 781콜(만기 프로브 1건 포함),
  마스터 행사가 폴백 동작, **JSON 14KB**(dict 형태였다면 120KB).
- 초당 5건 상한 기준 예상 소요: 780건 ≈ 2.6분 / 1,012건 ≈ 3.4분 (스펙의 "약 3.5분"과 일치).

**T8에서만 알 수 있는 것**(추측하지 않는다): 실제 회차 소요·실패 건수, `EGW00201` 발생 여부,
옵션 배치 중 `/live` 수급이 안 깨지는지, 풋 벽이 다른 날에도 1,000인지, ATM IV 실값.
**T8 전에는 8000 실서버에 반영하지 않는다** — 시간당 1,012콜을 공유 KIS 키로 쏘는 게
이 게이트가 확인하려는 바로 그 위험이다.

---

## Global Constraints

- **Python 3.9 호환** — `X | Y` 타입 문법·`match`·`str.removeprefix` 금지. `Optional[...]`, `from __future__ import annotations` 사용.
- **시각은 전부 KST** — `datetime.now()`/`date.today()` 금지, `backend.flow.kst.now()`/`kst.today()` 사용.
- **테스트는 KIS·네트워크 미접촉** — 가짜 클라이언트/주입 훅으로만. 하네스가 테스트 실행 시 KIS 키를 차단한다.
- **KIS 호출 초당 5건 상한** — 개인 계정 한도는 초당 10건이고 `/live` 수급이 이미 2~4건/초를 쓴다. 7.3건/초에서 `EGW00201`이 780건 중 6건 났다(2026-08-05 실측).
- **웹소켓 미접촉** — REST 전용. 1키1세션은 `/live` 수급(`flow/wsbus.py`)이 쓴다.
- **8000 실서버 불가침** — 재기동이 필요하면 `.venv/bin/python`으로만(시스템 python3.9엔 `pydantic_settings` 없음).
- **색 관례** — 상승·콜=빨강(`--up`), 하락·풋=파랑(`--down`). 미국식 반대 색 금지.
- **개인용 유지** — 시세 재배포 금지.
- **정직성 규칙**(스펙 §정직성 규칙 — 리뷰의 1급 기준):
  - **콜 벽은 숫자로 내지 않는다.** 범위 따라 1,050~1,250으로 흔들린다.
  - **풋 벽은 숫자로 내되 "지수 ±20% 안에서"를 반드시 병기한다.**
  - **ATM 내재변동성은 오늘 거래된(`vol>0`) 행사가에서만** 뽑는다.
  - **부분 실패 시 실패 건수를 화면에 밝힌다.**
  - 모르는 값을 0이나 그럴듯한 숫자로 꾸미지 않는다 — `None` → 화면 `–`.
- **테스트 실행** — `make test` (= `.venv/bin/python -m harness test`). 단일 파일은 `.venv/bin/python -m pytest tests/test_options.py -v`.
- **커밋 메시지** — 한국어 요약 + `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **scratchpad 커밋 금지.**

---

## 스펙 대비 의도적 변경 3건

계획을 짜며 스펙을 코드로 옮기다 걸린 것들이다. 구현자는 **이 절을 스펙보다 우선**한다.

**① 만기 목록 TR(`FHPIO056104C0`)을 쓰지 않는다.** 스펙 §데이터 확보 3)이 근월물 선택용으로 이 TR을 지정했지만, 종목마스터에 이미 전 종목의 만기가 들어 있다(그래서 마스터를 받는 것이다). TR 하나를 더 부르면 실패 모드만 하나 늘고 얻는 게 없다 — `optmaster.front_month()`가 마스터만으로 근월물을 고른다.

**② 코스피200 현물을 단건 시세의 `output3`에서 꺼내지 않는다.** 스펙 §데이터 확보 2)가 "`output3`에 KOSPI200 현물이 딸려 온다"고 적었지만 **그 필드 이름은 실측으로 기록되지 않았다**. 필드명을 추측해 쓰면 조용히 0이 되고, 0이면 `wall()`·`atm_iv()`가 통째로 무의미해진다. 대신 이미 검증된 `KisClient.index("2001")`(`FHPUP02100000` + `parse_index`)를 쓴다 — 회차당 1건이라 유량에 영향이 없다.

**③ 마커는 증감 차트에만 찍는다.** 스펙 §화면은 두 차트를 같은 좌표계로 그린다고만 했다. 누적 차트의 최댓값(1,597.5 = 최고 행사가)에 마커를 찍으면 **정직성 규칙이 숫자로 내지 말라고 한 바로 그 값**을 차트가 강조하게 된다. 누적은 분포만 그리고 마커를 찍지 않는다.

---

## File Structure

| 파일 | 신규/수정 | 책임 |
|---|---|---|
| `backend/flow/optmaster.py` | 신규 | 종목마스터 다운로드·파싱·캐시. 코드↔만기↔행사가만 |
| `backend/flow/options.py` | 신규 | 순수 파서 + 지표 계산. 네트워크·KIS 미접촉 |
| `backend/flow/kis.py` | 수정 | `KisClient.option_quote()` 추가 |
| `backend/api/marketdata.py` | 수정 | 배치 수집(유량 제어) + TTL + 백그라운드 갱신 + 디스크 캐시 |
| `backend/api/app.py` | 수정 | `GET /api/options` |
| `backend/report/options_panel.py` | 신규 | 섹션 CSS/마크업/JS(Canvas 차트 포함) |
| `backend/report/dashboard.py` | 수정 | 위 세 조각을 템플릿에 끼움 |
| `tests/test_optmaster.py` | 신규 | 마스터 파싱·만기 선택·캐시 폴백 |
| `tests/test_options.py` | 신규 | 지표 6종 순수 테스트 |
| `tests/test_options_collect.py` | 신규 | 수집기 유량·부분 실패·TTL·백그라운드 |
| `tests/test_options_panel_js.py` | 신규 | node 실행 — 렌더·차트 드로잉 |

`options.py`를 `optmaster.py`와 나눈 기준은 **"마스터 파일을 아는가"**다. `options.py`는 행 리스트만 받아 지표를 내므로 fixture만으로 100% 테스트된다. `optmaster.py`는 고정폭 레이아웃과 zip을 안다.

---

### Task 1: 종목마스터 파싱 — `optmaster.py`

**Files:**
- Create: `backend/flow/optmaster.py`
- Test: `tests/test_optmaster.py`

**Interfaces:**
- Consumes: 없음(이 계획의 첫 태스크). `backend.flow.kst`만 참조.
- Produces:
  - `MST_URL: str`
  - `parse_master(lines) -> List[dict]` — 각 항목 `{"code": str, "side": "call"|"put", "expiry": "YYYYMM", "strike": float}`
  - `expiry_date(yyyymm: str) -> datetime.date`
  - `front_month(rows, today: datetime.date) -> Optional[str]`
  - `chain(rows, expiry: str) -> dict` — `{"calls": [...], "puts": [...]}` 행사가 오름차순
  - `load(cache_dir: str, force: bool = False, fetch=None) -> List[dict]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_optmaster.py`:

```python
"""옵션 종목마스터 파싱 — 고정폭 cp949 레이아웃과 근월물 선택.

만기·행사가가 코드가 아니라 **이름 필드**에 있다는 게 이 모듈의 전부다
(2026-08-05 O1 실측: 코드의 '01608'은 상품+연월 축약이라 "202608"로 못 찾는다).
"""
import datetime as dt

from backend.flow import optmaster as om


def _line(head, code, isin, name):
    """마스터 한 행 조립 — [0]=구분 · [1:10]=단축코드 · [10:22]=ISIN · [22:]=이름."""
    return head + code.ljust(9) + isin.ljust(12) + name


# 2026-08-05 실제 마스터에서 뜬 모양: '5' 'B01608625' 'KR4B01686256' | 'C 202608   625.0'
_CALL = _line("5", "B01608625", "KR4B01686256", "C 202608   625.0")
_PUT = _line("6", "B01658625", "KR4B01686264", "P 202608   625.0")
_CALL_NEXT = _line("5", "B01609130", "KR4B01690001", "C 202609 1,300.0")
_FUTURE = _line("1", "A01609000", "KR4101SC0009", "F 202609")


def test_parse_master_reads_side_expiry_strike_from_name_field():
    rows = om.parse_master([_CALL, _PUT, _CALL_NEXT])
    assert len(rows) == 3
    c = rows[0]
    assert c["code"] == "B01608625" and c["side"] == "call"
    assert c["expiry"] == "202608" and c["strike"] == 625.0
    assert rows[1]["side"] == "put"
    assert rows[2]["strike"] == 1300.0          # 콤마 제거


def test_parse_master_skips_non_option_rows_and_garbage():
    rows = om.parse_master([_FUTURE, "", "5", _line("5", "B0160XXXX", "KR4X", "잘못된이름")])
    assert rows == []                            # 선물·빈행·형식 불일치는 조용히 버린다


def test_expiry_date_is_second_thursday():
    assert om.expiry_date("202608") == dt.date(2026, 8, 13)   # 8/6이 첫 목요일
    assert om.expiry_date("202609") == dt.date(2026, 9, 10)


def test_front_month_picks_earliest_unexpired_and_includes_expiry_day():
    rows = om.parse_master([_CALL, _CALL_NEXT])
    assert om.front_month(rows, dt.date(2026, 8, 5)) == "202608"
    assert om.front_month(rows, dt.date(2026, 8, 13)) == "202608"   # 만기 당일은 아직 거래
    assert om.front_month(rows, dt.date(2026, 8, 14)) == "202609"
    assert om.front_month(rows, dt.date(2026, 12, 1)) is None


def test_chain_splits_and_sorts_by_strike():
    rows = om.parse_master([_CALL_NEXT, _CALL, _PUT])
    ch = om.chain(rows, "202608")
    assert [r["strike"] for r in ch["calls"]] == [625.0]
    assert [r["strike"] for r in ch["puts"]] == [625.0]
    assert om.chain(rows, "202609")["puts"] == []


def test_load_uses_injected_fetch_and_caches_to_disk(tmp_path):
    payload = ("\n".join([_CALL, _PUT])).encode("cp949")
    calls = {"n": 0}

    def _fetch():
        calls["n"] += 1
        return payload

    rows = om.load(str(tmp_path), fetch=_fetch)
    assert len(rows) == 2 and calls["n"] == 1
    rows2 = om.load(str(tmp_path), fetch=_fetch)      # 하루 안 → 재다운로드 없음
    assert len(rows2) == 2 and calls["n"] == 1


def test_load_falls_back_to_stale_cache_when_download_fails(tmp_path):
    om.load(str(tmp_path), fetch=lambda: _CALL.encode("cp949"))

    def _boom():
        raise RuntimeError("네트워크 끊김")

    rows = om.load(str(tmp_path), force=True, fetch=_boom)
    assert len(rows) == 1        # 낡은 캐시라도 쓴다 — 만기·행사가는 하루 사이 안 바뀐다


def test_load_returns_empty_when_no_cache_and_download_fails(tmp_path):
    def _boom():
        raise RuntimeError("네트워크 끊김")

    assert om.load(str(tmp_path), fetch=_boom) == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_optmaster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.flow.optmaster'`

- [ ] **Step 3: 구현한다**

`backend/flow/optmaster.py`:

```python
from __future__ import annotations

"""코스피200 옵션 종목마스터 — 코드↔만기↔행사가. 파싱은 순수, 다운로드만 네트워크.

옵션은 만기·행사가마다 종목이 따로 있고 근월물 하나가 1,012개까지 간다. 전광판
TR(FHPIF05030100)은 행사가 내림차순 **상위 100행만** 주고 파라미터로 창이 안
움직인다(2026-08-05 실측) — 전 구간을 보려면 마스터에서 코드를 얻어 단건 시세를
도는 수밖에 없다. Python 3.9 호환."""

import datetime as dt
import io
import os
import re
import time
import zipfile
from typing import List, Optional

MST_URL = "https://new.real.download.dws.co.kr/common/master/fo_idx_code.mst.zip"
_MST_NAME = "fo_idx_code.mst"
_TTL_SEC = 86400.0        # 하루 1회만 새로 받는다(종목이 일 단위로 추가될 뿐이다)

# 이름 필드 예: 'C 202608   625.0' · 'P 202609 1,300.0'
# 만기·행사가는 **코드가 아니라 이름**에 있다 — 코드의 '01608'은 상품+연월 축약이라
# "202608"로 검색하면 한 건도 안 걸린다(초안 작성 때 이걸로 헤맸다).
_NAME_RE = re.compile(r"^([CP])\s+(\d{6})\s+([\d,]+\.\d+)")


def parse_master(lines) -> List[dict]:
    """마스터 행(str) 시퀀스 → [{code, side, expiry, strike}].

    고정폭: [0]=구분(5=콜·6=풋) · [1:10]=단축코드 · [10:22]=ISIN · [22:]=이름.
    구분이 5/6이 아닌 행(선물 등)과 이름이 형식에 안 맞는 행은 조용히 버린다 —
    마스터엔 옵션 말고도 여러 상품이 함께 들어 있다. 콜/풋 판정은 구분자가 아니라
    이름의 C/P로 한다(실측으로 확인한 쪽이 이쪽이다)."""
    out = []
    for line in lines:
        if not line or line[:1] not in ("5", "6") or len(line) < 23:
            continue
        m = _NAME_RE.match(line[22:])
        if not m:
            continue
        code = line[1:10].strip()
        if not code:
            continue
        out.append({"code": code,
                    "side": "call" if m.group(1) == "C" else "put",
                    "expiry": m.group(2),
                    "strike": float(m.group(3).replace(",", ""))})
    return out


def expiry_date(yyyymm: str) -> dt.date:
    """만기일 = 그 달의 **두 번째 목요일**(코스피200 옵션 규정).

    공휴일이면 직전 영업일로 앞당겨지지만 여기선 보지 않는다. 그 차이는 만기 당일
    하루에만 영향을 주고, 화면의 '만기 N일'은 KIS가 주는 잔존일수(hts_rmnn_dynu)를
    쓰므로 표기가 어긋나지 않는다. 이 함수는 '근월물이 이미 지났는가'의 근사 판정용이고,
    실제 롤오버는 marketdata의 만기 프로브가 한 번 더 확인한다."""
    y, m = int(yyyymm[:4]), int(yyyymm[4:6])
    first = dt.date(y, m, 1)
    first_thu = 1 + (3 - first.weekday()) % 7      # weekday: 월=0 … 목=3
    return dt.date(y, m, first_thu + 7)


def front_month(rows, today: dt.date) -> Optional[str]:
    """근월물 만기 'YYYYMM' — 만기일이 오늘 이후(당일 포함)인 것 중 가장 이른 것.
    만기 당일도 장이 열려 거래되므로 포함한다. 없으면 None."""
    for m in sorted({r["expiry"] for r in rows}):
        try:
            if expiry_date(m) >= today:
                return m
        except ValueError:
            continue                                # 형식이 깨진 만기는 건너뛴다
    return None


def chain(rows, expiry: str) -> dict:
    """만기 하나의 전 종목 → {'calls': [...], 'puts': [...]} (행사가 오름차순)."""
    sel = [r for r in rows if r.get("expiry") == expiry]
    key = lambda r: r.get("strike") or 0.0         # noqa: E731
    return {"calls": sorted([r for r in sel if r["side"] == "call"], key=key),
            "puts": sorted([r for r in sel if r["side"] == "put"], key=key)}


def _download() -> bytes:
    """마스터 zip → 첫 엔트리 bytes. 동기·블로킹 — 호출부가 run_in_executor로 위임한다."""
    import httpx
    r = httpx.get(MST_URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return z.read(z.namelist()[0])


def load(cache_dir: str, force: bool = False, fetch=None) -> List[dict]:
    """마스터 → 행 리스트. 캐시가 하루 안이면 재사용, 아니면 새로 받는다.

    다운로드가 실패하면 **낡은 캐시라도 그대로 쓴다** — 만기·행사가는 하루 사이에
    바뀌지 않고 종목이 추가될 뿐이라 stale이 무응답보다 낫다(해외선물 마스터에서
    쓰던 관행 그대로). 캐시도 없고 다운로드도 실패하면 빈 리스트 → 호출부가 섹션을
    통째로 생략한다. fetch는 테스트가 네트워크 없이 주입하는 훅(bytes 반환)."""
    path = os.path.join(cache_dir, _MST_NAME)
    try:
        fresh = (time.time() - os.path.getmtime(path)) < _TTL_SEC
    except OSError:
        fresh = False
    if force or not fresh:
        try:
            raw = (fetch or _download)()
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(raw)
        except Exception:
            pass                                    # 아래에서 낡은 캐시로 폴백
    try:
        with open(path, "rb") as f:
            lines = [ln.decode("cp949", errors="replace").rstrip("\r\n") for ln in f]
    except OSError:
        return []
    return parse_master(lines)
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_optmaster.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/flow/optmaster.py tests/test_optmaster.py
git commit -m "feat(options): 옵션 종목마스터 파싱 — 만기·행사가는 이름 필드에서

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 순수 지표 — `options.py`

**Files:**
- Create: `backend/flow/options.py`
- Test: `tests/test_options.py`

**Interfaces:**
- Consumes: `backend.flow.kst`(세션 판정용)
- Produces:
  - `WALL_PCT: float = 20.0`
  - `parse_quote(js) -> Optional[dict]` — `{"strike","price","vol","oi","oi_chg","iv","delta","remain_days"}`
  - `session_of(now=None) -> "live"|"closed"`
  - `month_label(expiry) -> str` — `"202608"` → `"8월물"`
  - `put_call_ratio(calls, puts) -> Optional[float]`
  - `wall(rows, spot, pct) -> Optional[dict]`
  - `atm_iv(calls, puts, spot) -> Optional[dict]`
  - `top_changes(rows, n=1) -> dict` — `{"up":[...], "down":[...]}`
  - `histogram(rows, field) -> List[dict]` — `[{"k":행사가,"v":값}]`
  - `summarize(calls, puts, spot) -> dict`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_options.py`:

```python
"""옵션 지표 순수 함수 — fixture만으로 100%. KIS·네트워크 미접촉.

이 파일의 핵심 회귀 3개(2026-08-05 실측이 만든 규칙):
  · wall()이 범위 밖 최대값(사다리 양 끝)을 집으면 안 된다
  · atm_iv()가 거래 0인 행사가를 쓰면 안 된다(IV가 낡아 51~61%로 나온다)
  · summarize()가 콜 벽을 내면 안 된다
"""
import datetime as dt

from backend.flow import options as opt
from backend.flow.kst import KST


def _row(strike, oi=0, chg=0, vol=0, iv=0.0):
    return {"strike": strike, "oi": oi, "oi_chg": chg, "vol": vol, "iv": iv}


def test_parse_quote_reads_output1_not_output():
    js = {"rt_cd": "0", "output1": {"acpr": "1000.0", "futs_prpr": "12.35",
                                    "acml_vol": "1,234", "hts_otst_stpl_qty": "5678",
                                    "otst_stpl_qty_icdc": "-224",
                                    "hts_ints_vltl": "87.12", "delta_val": "0.4821",
                                    "hts_rmnn_dynu": "9"}}
    q = opt.parse_quote(js)
    assert q["strike"] == 1000.0 and q["price"] == 12.35
    assert q["vol"] == 1234                     # 천단위 콤마
    assert q["oi"] == 5678 and q["oi_chg"] == -224    # 증감은 음수가 정상값이다
    assert q["iv"] == 87.12 and q["delta"] == 0.4821 and q["remain_days"] == 9


def test_parse_quote_rejects_error_and_empty_body():
    assert opt.parse_quote({"rt_cd": "1", "msg1": "초당 거래건수를 초과"}) is None
    assert opt.parse_quote({"rt_cd": "0", "output1": {}}) is None
    assert opt.parse_quote({"rt_cd": "0", "output": {"acpr": "1"}}) is None   # output은 안 본다
    assert opt.parse_quote(None) is None


def test_parse_quote_defaults_missing_fields_to_zero():
    q = opt.parse_quote({"rt_cd": "0", "output1": {"acpr": "1000.0"}})
    assert q["vol"] == 0 and q["oi"] == 0 and q["oi_chg"] == 0 and q["iv"] == 0.0


def test_put_call_ratio_and_zero_denominator():
    calls, puts = [_row(1000, vol=100), _row(1010, vol=100)], [_row(1000, vol=150)]
    assert opt.put_call_ratio(calls, puts) == 0.75
    assert opt.put_call_ratio([], puts) is None          # 0으로 나눈 값을 지어내지 않는다
    assert opt.put_call_ratio([_row(1000, vol=0)], puts) is None


def test_wall_ignores_the_ladder_edge_outside_the_band():
    """실측 재현 — 전 구간 최대는 최저 행사가 625.0(지수 −40%)에 있지만 그건
    폭락 보험이 경계에 쌓인 것이지 지지선이 아니다. ±20% 안에서는 1,000이 답."""
    puts = [_row(625.0, oi=100000), _row(900.0, oi=3000),
            _row(1000.0, oi=9000), _row(1200.0, oi=500)]
    w = opt.wall(puts, spot=1039.35, pct=20.0)
    assert w["strike"] == 1000.0
    assert opt.wall(puts, spot=1039.35, pct=60.0)["strike"] == 625.0   # 넓히면 끝이 잡힌다


def test_wall_requires_explicit_range():
    import inspect
    sig = inspect.signature(opt.wall)
    assert sig.parameters["pct"].default is inspect.Parameter.empty


def test_wall_returns_none_without_spot_or_rows():
    assert opt.wall([], 1000.0, 20.0) is None
    assert opt.wall([_row(1000, oi=5)], None, 20.0) is None
    assert opt.wall([_row(1000, oi=0)], 1000.0, 20.0) is None     # 미결제 0만 있으면 없음


def test_atm_iv_skips_untraded_strikes_with_stale_iv():
    """거래 0인 행사가의 IV는 낡았다(실측: 거래분 80~92% vs 무거래분 51~61%)."""
    calls = [_row(1040.0, vol=0, iv=55.0), _row(1050.0, vol=12, iv=88.0)]
    puts = [_row(1030.0, vol=0, iv=52.0)]
    a = opt.atm_iv(calls, puts, spot=1039.35)
    assert a["strike"] == 1050.0 and a["iv"] == 88.0     # 더 가깝지만 무거래인 1040을 건너뛴다
    assert opt.atm_iv([_row(1040.0, vol=0, iv=55.0)], [], 1039.35) is None


def test_top_changes_splits_up_and_down_by_magnitude():
    rows = [_row(1300, chg=2214), _row(1250, chg=800),
            _row(1597.5, chg=-224), _row(1100, chg=0)]
    t = opt.top_changes(rows, n=2)
    assert [r["strike"] for r in t["up"]] == [1300, 1250]
    assert [r["strike"] for r in t["down"]] == [1597.5]
    assert opt.top_changes([_row(1000, chg=0)])["up"] == []      # 0은 증감이 아니다


def test_histogram_keeps_zero_bins_and_sorts():
    rows = [_row(1010, oi=0), _row(1000, oi=5)]
    assert opt.histogram(rows, "oi") == [{"k": 1000, "v": 5}, {"k": 1010, "v": 0}]


def test_summarize_publishes_put_wall_but_never_call_wall():
    calls = [_row(1050, oi=9000, chg=100, vol=10, iv=90.0),
             _row(1300, oi=8000, chg=2214, vol=5, iv=95.0)]
    puts = [_row(1000, oi=7000, chg=1189, vol=20, iv=88.0)]
    s = opt.summarize(calls, puts, spot=1039.35)
    assert s["put_wall"] == 1000 and s["wall_pct"] == opt.WALL_PCT
    assert "call_wall" not in s                     # 정직성 규칙 — 콜 벽은 내지 않는다
    assert s["call_chg_sum"] == 2314 and s["put_chg_sum"] == 1189
    assert s["top_call"]["strike"] == 1300 and s["top_put"]["strike"] == 1000
    assert s["atm_iv"] == 90.0                      # spot에 가장 가까운 '거래된' 행사가


def test_summarize_survives_empty_board():
    s = opt.summarize([], [], spot=None)
    assert s["pcr"] is None and s["put_wall"] is None and s["atm_iv"] is None
    assert s["call_chg_sum"] == 0 and s["top_call"] is None


def test_session_of_covers_option_regular_hours():
    def at(h, m, day=5):
        return dt.datetime(2026, 8, day, h, m, tzinfo=KST)
    assert opt.session_of(at(9, 0)) == "live"
    assert opt.session_of(at(15, 44)) == "live"
    assert opt.session_of(at(15, 45)) == "closed"   # 15:45 마감
    assert opt.session_of(at(8, 59)) == "closed"    # 선물(08:45)과 다르다
    assert opt.session_of(at(11, 0, day=8)) == "closed"   # 2026-08-08 = 토요일


def test_month_label():
    assert opt.month_label("202608") == "8월물"
    assert opt.month_label("202612") == "12월물"
    assert opt.month_label("") == ""
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_options.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.flow.options'`

- [ ] **Step 3: 구현한다**

`backend/flow/options.py`:

```python
from __future__ import annotations

"""코스피200 옵션 지표 — 순수 함수만. 네트워크·KIS 미접촉.

행 리스트 하나를 받아 화면이 쓸 숫자까지만 낸다. 여기 있는 규칙 대부분은
2026-08-05 전 종목 실조회가 만든 것이다 — 자세한 근거는 스펙 §왜 초안을 버렸나.
Python 3.9 호환."""

import datetime as dt
from typing import List, Optional

from backend.flow import kst

WALL_PCT = 20.0        # 벽을 재는 범위. 화면에 "지수 ±20% 안에서"로 반드시 병기한다.
OPEN_MIN, CLOSE_MIN = 9 * 60, 15 * 60 + 45      # 옵션 정규장 09:00~15:45(KST)


def _f(v) -> float:
    try:
        return float(str(v).strip().replace(",", ""))
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _i(v) -> int:
    try:
        return int(float(str(v).strip().replace(",", "")))
    except (TypeError, ValueError, AttributeError):
        return 0


def parse_quote(js) -> Optional[dict]:
    """단건 시세(FHMIF10000000) 응답 → 지표용 행. 실패·빈 본문이면 None.

    **본문은 output이 아니라 output1이다**(output2=코스피, output3=코스피200).
    output만 읽으면 rt_cd=0에 빈 dict가 와서 '스로틀 걸렸나'로 오진하기 딱 좋다 —
    2026-08-05에 실제로 그렇게 30분을 날렸다."""
    if not isinstance(js, dict) or js.get("rt_cd") != "0":
        return None
    o = js.get("output1") or {}
    if not o:
        return None
    return {"strike": _f(o.get("acpr")),
            "price": _f(o.get("futs_prpr")),
            "vol": _i(o.get("acml_vol")),
            "oi": _i(o.get("hts_otst_stpl_qty")),
            "oi_chg": _i(o.get("otst_stpl_qty_icdc")),   # 음수가 정상값이다
            "iv": _f(o.get("hts_ints_vltl")),
            "delta": _f(o.get("delta_val")),
            "remain_days": _i(o.get("hts_rmnn_dynu"))}


def session_of(now: Optional[dt.datetime] = None) -> str:
    """'live'|'closed' — 코스피200 옵션 정규장은 평일 09:00~15:45(KST).

    선물(08:45~15:45)과 개장이 다르다. 야간옵션은 이 앱의 비목표(스펙 §목표)라
    다루지 않는다. 공휴일은 보지 않는다 — 휴장일엔 직전 수집값이 그대로 남는다."""
    now = now or kst.now()
    if now.weekday() >= 5:
        return "closed"
    hm = now.hour * 60 + now.minute
    return "live" if OPEN_MIN <= hm < CLOSE_MIN else "closed"


def month_label(expiry: str) -> str:
    """'202608' → '8월물'. 형식이 아니면 빈 문자열."""
    if not expiry or len(expiry) < 6 or not expiry[:6].isdigit():
        return ""
    return "%d월물" % int(expiry[4:6])


def put_call_ratio(calls, puts) -> Optional[float]:
    """풋 거래량 합 ÷ 콜 거래량 합. 분모가 0이면 None — 0으로 나눈 값을 지어내지 않는다."""
    c = sum((r.get("vol") or 0) for r in (calls or []))
    if c <= 0:
        return None
    return sum((r.get("vol") or 0) for r in (puts or [])) / c


def wall(rows, spot, pct) -> Optional[dict]:
    """지수 ±pct% 안에서 미결제(oi)가 가장 큰 행. **범위는 필수 인자 — 기본값이 없다.**

    전 구간으로 재면 사다리 양 끝이 잡힌다(실측: 콜 최고행사가 1,597.5가 콜 미결제의
    16.2%, 풋 최저행사가 625.0이 풋의 14.0%). 가격은 각각 0.04원·0.44원 — 복권 같은
    초저가와 폭락 보험이 경계에 쌓인 것이지 '시장이 보는 저항선·지지선'이 아니다.
    범위를 강제해 그 함정을 구조적으로 막는다(기본값을 주면 호출부가 잊는다)."""
    if not rows or not spot or pct is None:
        return None
    lo, hi = spot * (1 - pct / 100.0), spot * (1 + pct / 100.0)
    band = [r for r in rows
            if lo <= (r.get("strike") or 0) <= hi and (r.get("oi") or 0) > 0]
    if not band:
        return None
    return max(band, key=lambda r: r.get("oi") or 0)


def atm_iv(calls, puts, spot) -> Optional[dict]:
    """ATM 내재변동성 — **오늘 거래된**(vol>0) 행사가 중 spot에 가장 가까운 행.

    거래가 없는 행사가는 시세가 낡아 IV도 낡는다(실측: 거래된 행사가 80~92% vs
    거래 0인 행사가 51~61%로 두 층이 지그재그). 안 거르면 조용히 틀린 값이 나온다."""
    if not spot:
        return None
    live = [r for r in list(calls or []) + list(puts or [])
            if (r.get("vol") or 0) > 0 and (r.get("iv") or 0) > 0 and r.get("strike")]
    if not live:
        return None
    r = min(live, key=lambda x: abs(x["strike"] - spot))
    return {"iv": r["iv"], "strike": r["strike"], "vol": r["vol"]}


def top_changes(rows, n: int = 1) -> dict:
    """당일 증감 상위 → {'up': [...], 'down': [...]} 각각 |증감| 큰 순 n개.
    증감 0은 어느 쪽도 아니다(늘지도 줄지도 않은 자리를 '최대'라 부르지 않는다)."""
    rows = rows or []
    up = sorted([r for r in rows if (r.get("oi_chg") or 0) > 0],
                key=lambda r: r["oi_chg"], reverse=True)[:n]
    down = sorted([r for r in rows if (r.get("oi_chg") or 0) < 0],
                  key=lambda r: r["oi_chg"])[:n]
    return {"up": up, "down": down}


def histogram(rows, field: str) -> List[dict]:
    """차트용 (행사가, 값) 배열 — 행사가 오름차순. **값이 0인 칸도 남긴다** —
    막대 없는 자리가 '데이터 없음'이 아니라 '정말 0'임을 차트가 그대로 보여야 한다."""
    return [{"k": r["strike"], "v": r.get(field) or 0}
            for r in sorted(rows or [], key=lambda r: r.get("strike") or 0.0)
            if r.get("strike")]


def summarize(calls, puts, spot) -> dict:
    """보드 → 화면이 쓰는 요약 숫자. 순수.

    **콜 벽은 일부러 넣지 않는다.** 범위에 따라 1,050~1,250으로 흔들려(±5%~±30%
    실측) 우리가 범위를 고르는 순간 답의 일부를 우리가 정하게 된다. 차트에서 눈으로
    보게 두고 숫자로 단정하지 않는다. 풋 벽은 어느 범위에서도 1,000으로 같아서 낸다."""
    pw = wall(puts, spot, WALL_PCT)
    a = atm_iv(calls, puts, spot)
    tc, tp = top_changes(calls or []), top_changes(puts or [])
    return {"pcr": put_call_ratio(calls, puts),
            "put_wall": (pw or {}).get("strike"),
            "wall_pct": WALL_PCT,
            "atm_iv": (a or {}).get("iv"),
            "atm_strike": (a or {}).get("strike"),
            "call_chg_sum": sum((r.get("oi_chg") or 0) for r in (calls or [])),
            "put_chg_sum": sum((r.get("oi_chg") or 0) for r in (puts or [])),
            "top_call": (tc["up"] or [None])[0],
            "top_put": (tp["up"] or [None])[0]}
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_options.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/flow/options.py tests/test_options.py
git commit -m "feat(options): 지표 순수 함수 — 벽은 범위 필수, ATM IV는 거래된 행사가만

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: KIS 단건 시세 + 유량 제어 수집기

**Files:**
- Modify: `backend/flow/kis.py` (`KisClient` 끝, `futures_board` 다음)
- Modify: `backend/api/marketdata.py`
- Test: `tests/test_options_collect.py` (신규 — 이 태스크에선 수집기 부분만)

**Interfaces:**
- Consumes: `options.parse_quote`(Task 2), `optmaster.chain`(Task 1)
- Produces:
  - `KisClient.option_quote(code: str) -> Optional[dict]`
  - `marketdata._collect_chain(client, rows, rate=None, conc=None) -> Tuple[list, int]` — `(파싱된 행 리스트, 실패 건수)`. 각 행은 `parse_quote` 결과에 `code`·`side`가 얹힌 것.
  - 상수 `_OPT_RATE = 5.0` · `_OPT_CONC = 3` · `_OPT_RETRY = 2`
  - **기본값을 `None`으로 두고 함수 안에서 상수를 읽는 이유**: `rate=_OPT_RATE`라고 쓰면 기본값이 **정의 시점에 묶여** 테스트의 `monkeypatch.setattr(md, "_OPT_RATE", ...)`가 먹지 않는다. 상수를 바꿔도 이미 구워진 기본값이 그대로 쓰인다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_options_collect.py`:

```python
"""옵션 배치 수집 — 유량 상한·부분 실패 집계. KIS 미접촉(가짜 클라이언트).

유량이 이 태스크의 전부다. 개인 계정 REST 한도는 초당 10건이고 /live 수급이
이미 2~4건/초를 쓴다 — 옵션 배치가 남은 몫을 다 먹으면 기존 화면이 EGW00201로
깨진다(7.3건/초에서 780건 중 6건 실패, 2026-08-05 실측).
"""
import asyncio
import time

import pytest


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """재시도 백오프를 0으로 — 테스트가 실제로 초를 세며 자지 않게 한다."""
    from backend.api import marketdata as md
    monkeypatch.setattr(md, "_OPT_BACKOFF", 0.0)


class _FakeOptClient:
    """option_quote 호출 시각을 기록하는 가짜 클라이언트. fail_codes는 항상 실패."""

    def __init__(self, fail_codes=(), latency=0.0):
        self.at, self.fail_codes, self.latency = [], set(fail_codes), latency

    async def option_quote(self, code):
        self.at.append(time.monotonic())
        if self.latency:
            await asyncio.sleep(self.latency)
        if code in self.fail_codes:
            return None
        n = int(code[-3:])
        return {"strike": float(n), "price": 1.0, "vol": n, "oi": n * 10,
                "oi_chg": n - 5, "iv": 80.0, "delta": 0.5, "remain_days": 9}


def _rows(n, side="call"):
    """마스터 행 n개. 행사가는 1.0부터 — 0.0은 '값 없음'과 구분이 안 된다."""
    return [{"code": "B0160%03d" % i, "side": side, "strike": float(i)}
            for i in range(1, n + 1)]


def test_collect_chain_attaches_code_and_side():
    from backend.api import marketdata as md
    c = _FakeOptClient()
    rows, failed = asyncio.run(md._collect_chain(c, _rows(3), rate=1000.0, conc=3))
    assert failed == 0 and len(rows) == 3
    assert rows[0]["code"] == "B0160001" and rows[0]["side"] == "call"


def test_collect_chain_never_exceeds_the_rate_cap():
    """40건을 초당 20건 상한으로 — 최소 (40-1)/20초는 걸려야 한다.
    세마포어만으론 응답이 빠를 때 발사량을 못 막는다(페이싱이 따로 필요한 이유)."""
    from backend.api import marketdata as md
    c = _FakeOptClient()
    t0 = time.monotonic()
    rows, failed = asyncio.run(md._collect_chain(c, _rows(40), rate=20.0, conc=3))
    elapsed = time.monotonic() - t0
    assert len(rows) == 40 and failed == 0
    assert elapsed >= 39 / 20.0 * 0.9          # 타이머 오차 10% 여유
    gaps = [b - a for a, b in zip(c.at, c.at[1:])]
    assert max(gaps) < 1.0                      # 상한을 지키되 쓸데없이 느리지도 않다


def test_collect_chain_counts_failures_without_dropping_the_batch():
    from backend.api import marketdata as md
    c = _FakeOptClient(fail_codes=("B0160002", "B0160004"))
    rows, failed = asyncio.run(md._collect_chain(c, _rows(5), rate=1000.0, conc=3))
    assert failed == 2 and len(rows) == 3       # 실패 건만 빠지고 나머지는 산다
    assert {r["code"] for r in rows} == {"B0160001", "B0160003", "B0160005"}


def test_collect_chain_retries_before_giving_up():
    """EGW00201(호출량 초과)은 정상 경로다 — 지수 백오프로 재시도한다."""
    from backend.api import marketdata as md

    class _FlakyOnce(_FakeOptClient):
        def __init__(self):
            super().__init__()
            self.seen = {}

        async def option_quote(self, code):
            self.seen[code] = self.seen.get(code, 0) + 1
            if self.seen[code] == 1:
                return None                     # 첫 시도만 실패
            return await super().option_quote(code)

    c = _FlakyOnce()
    rows, failed = asyncio.run(md._collect_chain(c, _rows(2), rate=1000.0, conc=2))
    assert failed == 0 and len(rows) == 2
    assert all(v == 2 for v in c.seen.values())


def test_collect_chain_survives_client_exception():
    from backend.api import marketdata as md

    class _Boom:
        async def option_quote(self, code):
            raise RuntimeError("연결 끊김")

    rows, failed = asyncio.run(md._collect_chain(_Boom(), _rows(2), rate=1000.0, conc=2))
    assert rows == [] and failed == 2


def test_collect_chain_falls_back_to_master_strike_when_response_lacks_it():
    """응답에 행사가가 비면 마스터 값으로 메운다 — 행사가 없는 행은 histogram이
    걸러내 차트에서 통째로 사라진다. 알고 있는 값이 있는데 버릴 이유가 없다."""
    from backend.api import marketdata as md

    class _NoStrike(_FakeOptClient):
        async def option_quote(self, code):
            q = await super().option_quote(code)
            q["strike"] = 0.0                   # 응답에 행사가가 비는 경우
            return q

    rows, _ = asyncio.run(md._collect_chain(_NoStrike(), _rows(1), rate=1000.0, conc=1))
    assert rows[0]["strike"] == 1.0             # 마스터의 행사가로 메워졌다


def test_option_quote_uses_correct_tr_and_params():
    """KisClient.option_quote — TR·경로·파라미터를 고정한다(회귀 방지)."""
    import asyncio as aio
    from backend.flow.kis import KisClient

    seen = {}

    class _C(KisClient):
        async def _get(self, path, tr_id, params, retries=2):
            seen.update({"path": path, "tr": tr_id, "params": params})
            return {"rt_cd": "0", "output1": {"acpr": "1000.0", "acml_vol": "5"}}

    c = _C("k", "s", "/tmp")
    q = aio.run(c.option_quote("B01608625"))
    assert seen["tr"] == "FHMIF10000000"
    assert seen["path"].endswith("/domestic-futureoption/v1/quotations/inquire-price")
    assert seen["params"] == {"FID_COND_MRKT_DIV_CODE": "O",
                              "FID_INPUT_ISCD": "B01608625"}
    assert q["strike"] == 1000.0 and q["vol"] == 5
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_options_collect.py -v`
Expected: FAIL — `AttributeError: module 'backend.api.marketdata' has no attribute '_collect_chain'`

- [ ] **Step 3: `KisClient.option_quote`를 구현한다**

`backend/flow/kis.py` — `futures_board` 바로 다음에 추가:

```python
    async def option_quote(self, code: str) -> Optional[dict]:
        """옵션 단건 시세(FHMIF10000000) — 전광판이 보드의 상위 100행만 주므로
        전 구간을 보려면 종목별로 이걸 돈다(2026-08-05 O1 실측).

        div=O가 옵션이다. 응답 본문이 output이 아니라 **output1**이라는 게 이 TR의
        함정 — parse_quote가 그걸 안다."""
        from backend.flow import options as _opt      # 순환 임포트 회피
        js = await self._get("/uapi/domestic-futureoption/v1/quotations/inquire-price",
                             "FHMIF10000000",
                             {"FID_COND_MRKT_DIV_CODE": "O", "FID_INPUT_ISCD": code})
        return _opt.parse_quote(js)
```

- [ ] **Step 4: 수집기를 구현한다**

`backend/api/marketdata.py` — `get_futures` 계열 아래, `get_asking` 위에 추가:

```python
# ── 코스피200 옵션 ─────────────────────────────────────────────────────────
_OPT_RATE = 5.0     # 초당 발사 상한. 개인 계정 한도는 10건/초인데 /live 수급이
                    # 2~4건/초를 이미 쓴다 — 절반만 쓴다. 7.3건/초에서 EGW00201이
                    # 780건 중 6건 났다(2026-08-05 실측).
_OPT_CONC = 3       # 동시 요청 수(같은 실측의 조합: 동시 3 + 페이싱)
_OPT_RETRY = 2      # EGW00201 재시도 횟수
_OPT_BACKOFF = 1.0  # 재시도 첫 대기(초). 매 회 2배 — 테스트가 0으로 덮어쓴다.


async def _collect_chain(client, rows, rate=None, conc=None):
    """옵션 종목 리스트 → (파싱된 행 리스트, 실패 건수). 초당 rate 건을 안 넘는다.

    세마포어만으로는 유량을 못 막는다 — 응답이 빠르면 동시 3으로도 초당 20건이
    나간다. '직전 발사 예정 시각'을 잠금으로 지켜 간격 자체를 강제한다. 페이싱을
    세마포어 **안**에서 하는 이유: 예약 직후 곧바로 발사돼야 예약과 실제 발사가
    어긋나지 않는다(밖에서 하면 세마포어 대기 동안 예약이 밀려 뭉쳐 나간다).

    rate/conc 기본값을 상수로 직접 쓰지 않고 None으로 두는 이유: 기본값은 함수
    정의 시점에 묶여, 테스트가 _OPT_RATE를 바꿔도 안 먹는다.

    실패는 예외로 올리지 않는다 — 1,012건 중 몇 건은 늘 실패하고, 그건 정상
    경로다(스펙 §에러 처리). 대신 **몇 건 실패했는지를 반환해 화면이 밝힌다**."""
    if not rows:
        return [], 0
    rate = _OPT_RATE if rate is None else rate
    conc = _OPT_CONC if conc is None else conc
    interval = 1.0 / max(rate, 0.001)
    sem = asyncio.Semaphore(max(1, conc))
    lock = asyncio.Lock()
    state = {"next": 0.0, "failed": 0}

    async def pace():
        async with lock:
            now = time.monotonic()
            wait = max(0.0, state["next"] - now)
            state["next"] = max(now, state["next"]) + interval
        if wait > 0:
            await asyncio.sleep(wait)

    async def one(row):
        delay = _OPT_BACKOFF
        for attempt in range(_OPT_RETRY + 1):
            async with sem:
                await pace()
                try:
                    q = await client.option_quote(row["code"])
                except Exception:
                    q = None
            if q is not None:
                q["code"], q["side"] = row["code"], row.get("side")
                if not q.get("strike"):
                    q["strike"] = row.get("strike")   # 응답이 비면 마스터 값으로
                return q
            if attempt < _OPT_RETRY and delay:
                await asyncio.sleep(delay)            # 지수 백오프
                delay *= 2
        state["failed"] += 1
        return None

    out = await asyncio.gather(*(one(r) for r in rows))
    return [q for q in out if q is not None], state["failed"]
```

`marketdata.py` 상단 임포트에 `from typing import Tuple`은 필요 없다(반환 타입 주석을 쓰지 않는다). `asyncio`·`time`은 이미 임포트돼 있다.

- [ ] **Step 5: 테스트 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_options_collect.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: 커밋**

```bash
git add backend/flow/kis.py backend/api/marketdata.py tests/test_options_collect.py
git commit -m "feat(options): 단건 시세 TR + 초당 5건 상한 배치 수집기

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `get_options()` — 만기 프로브·TTL·백그라운드 갱신·디스크 캐시

**Files:**
- Modify: `backend/api/marketdata.py`
- Test: `tests/test_options_collect.py` (이어서 추가)

**Interfaces:**
- Consumes: `_collect_chain`(Task 3) · `optmaster.load/front_month/chain/expiry_date`(Task 1) · `options.summarize/session_of/month_label`(Task 2) · `KisClient.index("2001")`(기존)
- Produces:
  - `get_options(client=None, now=None) -> Optional[dict]`
  - 반환 shape:
    ```python
    {"expiry": "202608", "label": "8월물", "remain_days": 9, "spot": 1039.35,
     "cols": ["strike", "oi", "oi_chg"],
     "calls": [[625.0, 12345, -224], ...],      # cols 순서의 3튜플
     "puts":  [[625.0, 9876, 1189], ...],
     "summary": {...},                           # options.summarize() 결과
     "failed": 0, "ts": 1754...,                 # 수집 완료 시각(epoch)
     "collecting": False, "stale": False}
    ```
  - **차트 배열을 3튜플로 보내는 이유**: 1,012행 × 8필드 dict면 JSON이 120KB를 넘는다. 화면이 실제로 쓰는 건 행사가·미결제·증감 셋뿐이라 20KB로 줄인다. `cols`를 같이 실어 shape가 스스로를 설명하게 한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_options_collect.py`에 이어서:

```python
import datetime as dt

import pytest

from backend.flow.kst import KST

_LIVE = dt.datetime(2026, 8, 5, 11, 0, tzinfo=KST)       # 수요일 장중
_CLOSED = dt.datetime(2026, 8, 5, 16, 30, tzinfo=KST)    # 마감 후


def _reset_opt(md):
    md._opt_cache.update({"ts": 0.0, "data": None, "busy": False})


@pytest.fixture(autouse=True)
def _isolate_opt_cache(tmp_path, monkeypatch):
    """디스크 캐시를 격리하고, 페이싱을 끄고, 오늘 날짜를 고정한다.

    날짜 고정이 중요하다 — front_month는 '만기일이 오늘 이후'로 고르므로,
    이걸 안 묶으면 2026-08-13이 지난 날 이 테스트가 갑자기 깨진다.
    (유량 자체는 test_collect_chain_never_exceeds_the_rate_cap이 rate를 직접 넘겨 잰다.)"""
    from backend.api import marketdata as md
    from backend.config import settings
    from backend.flow import kst
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(md, "_OPT_RATE", 1000.0)
    monkeypatch.setattr(kst, "today", lambda: dt.date(2026, 8, 5))
    _reset_opt(md)
    yield
    _reset_opt(md)


class _FakeBoard(_FakeOptClient):
    """마스터 없이 get_options를 돌리기 위한 클라이언트 — index()까지 흉내낸다."""

    async def index(self, iscd="0001"):
        assert iscd == "2001"        # 코스피200 — 스펙 §변경 ②
        return {"price": 1039.35, "rate": 0.5}


def _install_master(monkeypatch, md, rows):
    from backend.flow import optmaster as om
    monkeypatch.setattr(om, "load", lambda cache_dir, force=False, fetch=None: rows)


def _master_rows():
    return [{"code": "B0160%03d" % i, "side": "call", "expiry": "202608",
             "strike": 1000.0 + i} for i in range(1, 4)] + \
           [{"code": "B0165%03d" % i, "side": "put", "expiry": "202608",
             "strike": 1000.0 + i} for i in range(1, 4)]


def test_get_options_collects_and_shapes_payload(monkeypatch):
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    d = asyncio.run(md._collect_options(_FakeBoard()))
    assert d["expiry"] == "202608" and d["label"] == "8월물"
    assert d["spot"] == 1039.35 and d["remain_days"] == 9
    assert d["cols"] == ["strike", "oi", "oi_chg"]
    assert len(d["calls"]) == 3 and len(d["calls"][0]) == 3
    assert d["failed"] == 0
    assert "call_wall" not in d["summary"]      # 정직성 규칙


def test_get_options_returns_none_without_master(monkeypatch):
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, [])
    assert asyncio.run(md._collect_options(_FakeBoard())) is None


def test_get_options_serves_cache_immediately_and_refreshes_in_background(monkeypatch):
    """한 회차가 3.5분이라 요청을 붙잡으면 안 된다 — 즉시 직전값 + collecting:True."""
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    md._opt_cache["data"] = {"expiry": "202607", "calls": [], "puts": [], "summary": {}}
    md._opt_cache["ts"] = 0.0                   # 만료

    async def _run():
        d = await md.get_options(client=_FakeBoard(), now=_LIVE)
        assert d["expiry"] == "202607"          # 직전값을 곧바로 준다
        assert d["collecting"] is True and d["stale"] is True
        for _ in range(200):                    # 백그라운드가 끝날 때까지 양보
            if not md._opt_cache["busy"]:
                break
            await asyncio.sleep(0.01)
        d2 = await md.get_options(client=_FakeBoard(), now=_LIVE)
        assert d2["expiry"] == "202608" and d2["collecting"] is False
        assert d2["stale"] is False

    asyncio.run(_run())


def test_get_options_does_not_refresh_outside_session(monkeypatch):
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    md._opt_cache["data"] = {"expiry": "202608", "calls": [], "puts": [], "summary": {}}
    md._opt_cache["ts"] = 0.0
    c = _FakeBoard()
    d = asyncio.run(md.get_options(client=c, now=_CLOSED))
    assert d["collecting"] is False and c.at == []    # 마감 후엔 한 건도 안 부른다
    assert d["stale"] is False                        # 마감은 '지연'이 아니다


def test_get_options_returns_empty_when_cold_and_collecting(monkeypatch):
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    md._opt_cache["busy"] = True                      # 이미 첫 수집 중
    assert asyncio.run(md.get_options(client=_FakeBoard(), now=_LIVE)) == {}


def test_get_options_none_without_key(monkeypatch):
    from backend.api import marketdata as md
    monkeypatch.setattr(md, "_client", lambda: None)
    assert asyncio.run(md.get_options(now=_LIVE)) is None


def test_get_options_survives_disk_and_keeps_last_board(monkeypatch, tmp_path):
    """서버를 재기동해도 직전 보드를 보여준다 — 장외엔 새로 못 받는다."""
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    asyncio.run(md._opt_refresh(_FakeBoard()))
    saved = md._opt_cache["data"]
    assert saved is not None
    _reset_opt(md)                                     # 재기동 흉내
    d = asyncio.run(md.get_options(client=_FakeBoard(), now=_CLOSED))
    assert d["expiry"] == saved["expiry"] and len(d["calls"]) == len(saved["calls"])


def test_get_options_failure_keeps_previous_board(monkeypatch):
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    md._opt_cache["data"] = {"expiry": "202608", "calls": [], "puts": [], "summary": {}}
    md._opt_cache["ts"] = time.time()

    class _Boom(_FakeBoard):
        async def option_quote(self, code):
            raise RuntimeError("KIS 죽음")      # 전 종목 실패 → 회차가 통째로 무산

    asyncio.run(md._opt_refresh(_Boom()))
    assert md._opt_cache["data"]["expiry"] == "202608"   # 직전값 유지
    assert md._opt_cache["busy"] is False                # 실패해도 잠금은 풀린다
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_options_collect.py -v`
Expected: FAIL — `AttributeError: module 'backend.api.marketdata' has no attribute '_collect_options'`

- [ ] **Step 3: 구현한다**

`backend/api/marketdata.py` — `_collect_chain` 아래에 추가:

```python
_OPT_TTL = 3600.0        # 장중 1시간. 회차당 1,012건·약 3.5분이라 더 자주 돌 이유가 없다.
_OPT_FILE = "options_%s.json"
_opt_cache = {"ts": 0.0, "data": None, "busy": False}


def _opt_path(expiry):
    import os
    return os.path.join(settings.cache_dir, _OPT_FILE % expiry)


def _opt_save_disk(data):
    """수집 결과를 디스크에 남긴다 — 서버 재기동에도 직전 보드가 살아 있어야 한다."""
    import json
    import os
    try:
        os.makedirs(settings.cache_dir, exist_ok=True)
        with open(_opt_path(data["expiry"]), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass                     # 캐시 저장 실패가 화면을 죽이면 안 된다


def _opt_load_disk():
    """가장 최근에 저장된 보드 하나를 읽는다(만기별 파일 중 mtime 최신). 없으면 None."""
    import glob
    import json
    import os
    try:
        paths = glob.glob(os.path.join(settings.cache_dir, _OPT_FILE % "*"))
        if not paths:
            return None
        with open(max(paths, key=os.path.getmtime), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


async def _pick_expiry(client, rows, today):
    """근월물과 잔존일수 — 마스터로 고르고 **한 건만 찔러 확인**한다.

    만기일 계산(둘째 목요일)은 공휴일로 앞당겨지는 경우를 못 본다. 전 종목 3.5분을
    돌고 나서 '이미 만기였다'를 알면 늦으므로, 체인 한가운데 한 종목만 조회해
    잔존일수를 본다. 음수면 다음 월물로 넘어간다. 프로브가 실패하면(장외 등) 계산값을
    그대로 쓴다 — best effort지 게이트가 아니다."""
    from backend.flow import optmaster as om
    months = [m for m in sorted({r["expiry"] for r in rows})
              if om.expiry_date(m) >= today][:2]
    for m in months:
        ch = om.chain(rows, m)
        pool = ch["calls"] or ch["puts"]
        if not pool:
            continue
        try:
            q = await client.option_quote(pool[len(pool) // 2]["code"])
        except Exception:
            q = None
        if q is None:
            return m, None                       # 프로브 실패 → 계산값 채택
        if (q.get("remain_days") or 0) >= 0:
            return m, q.get("remain_days")
    return (months[0], None) if months else (None, None)


def _opt_pack(rows):
    """행 리스트 → [[행사가, 미결제, 당일증감], ...] (행사가 오름차순).

    1,012행을 dict로 보내면 JSON이 120KB를 넘는다 — 화면이 쓰는 건 이 셋뿐이라
    3튜플로 줄인다(약 20KB). 순서는 응답의 'cols'가 밝힌다."""
    return [[r.get("strike"), r.get("oi") or 0, r.get("oi_chg") or 0]
            for r in sorted(rows, key=lambda x: x.get("strike") or 0.0)
            if r.get("strike")]


async def _collect_options(client):
    """한 회차 전체 수집 — 마스터 → 만기 → 현물 → 콜/풋 전 종목. 실패하면 None."""
    from backend.flow import kst, optmaster as om, options as opt
    rows = await asyncio.get_event_loop().run_in_executor(
        None, om.load, settings.cache_dir)
    if not rows:
        return None
    expiry, remain = await _pick_expiry(client, rows, kst.today())
    if not expiry:
        return None
    ch = om.chain(rows, expiry)
    if not ch["calls"] and not ch["puts"]:
        return None
    # 코스피200 현물 — 스펙은 단건 시세 output3에 딸려 온다고 했지만 그 필드명이
    # 실측으로 기록되지 않았다. 추측한 이름이 빗나가면 spot=0이 되고, spot이 0이면
    # wall()·atm_iv()가 통째로 무의미해진다. 이미 검증된 index("2001")을 쓴다(1건).
    try:
        spot = (await client.index("2001") or {}).get("price")
    except Exception:
        spot = None
    calls, cf = await _collect_chain(client, ch["calls"])
    puts, pf = await _collect_chain(client, ch["puts"])
    if not calls and not puts:
        return None
    if remain is None:
        got = [r.get("remain_days") for r in (calls + puts) if r.get("remain_days")]
        remain = got[0] if got else None
    return {"expiry": expiry, "label": opt.month_label(expiry),
            "remain_days": remain, "spot": spot,
            "cols": ["strike", "oi", "oi_chg"],
            "calls": _opt_pack(calls), "puts": _opt_pack(puts),
            "summary": opt.summarize(calls, puts, spot),
            "failed": cf + pf, "ts": time.time()}


async def _opt_refresh(client):
    """백그라운드 1회차 — 성공하면 캐시·디스크를 갈아끼우고, 실패하면 직전값을 둔다."""
    try:
        data = await _collect_options(client)
        if data:
            _opt_cache["ts"], _opt_cache["data"] = time.time(), data
            _opt_save_disk(data)
    except Exception:
        pass
    finally:
        _opt_cache["busy"] = False        # 실패해도 반드시 풀린다(안 풀면 영영 안 돈다)


async def get_options(client=None, now=None):
    """코스피200 옵션 보드 — 대시보드 섹션용. 키없음이면 None, 콜드+수집중이면 {}.

    한 회차가 최대 1,012건·약 3.5분이라 **요청을 붙잡지 않는다** — 캐시가 만료돼도
    직전값을 즉시 돌려주고 갱신은 백그라운드로 돌린다('collecting': True). 대차잔고
    최초 백필과 같은 패턴이다. 'stale'은 장중에 TTL이 지났는데 아직 새 값이 없다는
    뜻이고, 마감 후엔 붙이지 않는다(마감은 지연이 아니다 — 선물 칩에서 정한 규칙)."""
    from backend.flow import options as opt
    client = client or _client()
    if client is None:
        return None
    if _opt_cache["data"] is None:
        _opt_cache["data"] = _opt_load_disk()     # 재기동 직후에도 직전 보드를 보여준다
    live = opt.session_of(now) == "live"
    fresh = (time.time() - _opt_cache["ts"]) < _OPT_TTL
    if live and not fresh and not _opt_cache["busy"]:
        _opt_cache["busy"] = True
        asyncio.ensure_future(_opt_refresh(client))
    data = _opt_cache["data"]
    if data is None:
        return {}
    out = dict(data)
    out["collecting"] = _opt_cache["busy"]
    out["stale"] = bool(live and not fresh)
    return out
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_options_collect.py -v`
Expected: PASS (15 passed)

- [ ] **Step 5: 전체 스위트로 회귀를 확인한다**

Run: `make test`
Expected: 기존 테스트 전부 통과(옵션 코드는 아직 어디서도 안 불리므로 영향 없어야 한다)

- [ ] **Step 6: 커밋**

```bash
git add backend/api/marketdata.py tests/test_options_collect.py
git commit -m "feat(options): 회차 수집 + TTL·백그라운드 갱신·디스크 캐시

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `/api/options` 라우트

**Files:**
- Modify: `backend/api/app.py` (`futures_api` 다음)
- Test: `tests/test_api.py` (기존 스모크에 추가)

**Interfaces:**
- Consumes: `marketdata.get_options`(Task 4)
- Produces: `GET /api/options` → Task 4의 payload 또는 `{}`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_api.py` 끝에 추가:

```python
def test_options_route_returns_empty_without_key(monkeypatch):
    """키가 없으면 빈 dict — 프론트가 섹션을 통째로 숨긴다(에러 토스트 금지)."""
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
    from backend.config import settings
    monkeypatch.setattr(settings, "kis_app_key", None)
    with TestClient(create_app()) as c:
        r = c.get("/api/options")
    assert r.status_code == 200 and r.json() == {}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_options_route_returns_empty_without_key -v`
Expected: FAIL — 404

- [ ] **Step 3: 구현한다**

`backend/api/app.py` — `futures_api` 다음:

```python
    @app.get("/api/options")
    async def options_api():
        """코스피200 옵션 보드. 키없음/콜드면 {} — 프론트가 섹션을 숨긴다."""
        from backend.api.marketdata import get_options
        return await get_options() or {}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/api/app.py tests/test_api.py
git commit -m "feat(options): GET /api/options 라우트

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 대시보드 섹션 — 마크업·CSS·요약줄·숫자 3개

**Files:**
- Create: `backend/report/options_panel.py`
- Modify: `backend/report/dashboard.py`
- Test: `tests/test_dashboard.py` (마크업 사실 확인)

**Interfaces:**
- Consumes: `/api/options`(Task 5)
- Produces:
  - `options_panel.CSS: str` · `options_panel.HTML: str` · `options_panel.JS: str`
  - `dashboard._TEMPLATE`에 `__OPT_CSS__`·`__OPT_HTML__`·`__OPT_JS__` 자리
  - 이 태스크에선 `optDraw()`를 **빈 함수로 둔다** — 차트는 Task 7. 요약줄·숫자·숨김 로직만 완성한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_dashboard.py`에 추가:

```python
def test_dashboard_has_collapsed_options_section_hidden_by_default():
    """옵션 섹션은 접힌 채로, 데이터가 오기 전엔 숨어 있어야 한다 —
    빈 섹션이 '옵션 데이터 없음'처럼 자리를 차지하면 안 된다."""
    from backend.report.dashboard import render_dashboard
    html = render_dashboard([], [], "2026-08-05")
    assert 'id="optsec"' in html
    assert 'style="display:none"' in html.split('id="optsec"')[1][:120]
    assert "<details" in html.split('id="optsec"')[0][-80:]
    assert "open" not in html.split('id="optsec"')[1].split(">")[0]   # 기본 접힘
    assert 'id="opt-chg"' in html and 'id="opt-oi"' in html
    # 증감 차트가 누적보다 **위**에 온다 — 오늘의 신호가 주인공이다
    assert html.index('id="opt-chg"') < html.index('id="opt-oi"')
    assert "loadOptions" in html
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: FAIL — `assert 'id="optsec"' in html`

- [ ] **Step 3: `options_panel.py`를 만든다**

`backend/report/options_panel.py`:

```python
from __future__ import annotations

"""대시보드 코스피200 옵션 섹션 — CSS·마크업·JS 세 조각.

dashboard.py에서 분리한 이유는 순전히 크기다(섹션 하나가 차트 둘을 포함해 250줄이
넘는다). 렌더 시점에 dashboard._TEMPLATE의 자리표시자로 끼워진다.
문자열만 내보내고 파이썬 로직은 없다."""

CSS = """
#optsec .optdig{margin-left:auto;margin-right:8px;font-family:var(--font-num);
  font-variant-numeric:tabular-nums;font-size:11.5px;color:var(--text-3);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.optnums{display:flex;gap:8px;margin:10px 0 4px}
.optnums .on{flex:1;min-width:0;background:var(--surface-2);border-radius:var(--r-md);
  padding:8px 10px}
.optnums .ok{font-size:11px;color:var(--text-3);white-space:nowrap}
.optnums .ov{font-family:var(--font-num);font-variant-numeric:tabular-nums;
  font-size:17px;font-weight:700;color:var(--text);margin-top:2px}
.optnums .oz{font-size:10.5px;color:var(--text-3);margin-top:1px}
.optch{margin-top:12px}
.optcap{font-size:12.5px;font-weight:600;color:var(--text);margin-bottom:4px}
.optcap .meta{font-weight:400}
.optch canvas{width:100%;display:block}
#opt-foot{margin-top:10px}
"""

HTML = """
<details class="sec" id="optsec" style="display:none">
  <summary><svg class="hic secic"><use href="#i-bars"/></svg> 코스피200 옵션
    <span class="optdig" id="opt-dig"></span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="optnums" id="opt-nums"></div>
    <div class="optch">
      <div class="optcap">오늘의 증감 <span class="meta">— 오늘 새로 걸린 자리</span></div>
      <canvas id="opt-chg" height="190"></canvas>
    </div>
    <div class="optch">
      <div class="optcap">누적 미결제 <span class="meta">— 지금까지 쌓인 포지션</span></div>
      <canvas id="opt-oi" height="190"></canvas>
    </div>
    <div class="meta" id="opt-foot"></div>
  </div>
</details>
"""

JS = r"""
// ── 코스피200 옵션 섹션 — 1시간 수집분을 보여준다(장중 5분마다 재확인). ──
function optNum(n, d){ return n==null ? '–' : Number(n).toLocaleString('ko-KR',
  {minimumFractionDigits:d||0, maximumFractionDigits:d||0}); }
function optSigned(n){ return n==null ? '–' : (n>0?'+':'')+optNum(n); }

function optCard(k, v, z){
  return '<div class="on"><div class="ok">'+k+'</div><div class="ov">'+v+'</div>'
       + (z?'<div class="oz">'+z+'</div>':'')+'</div>';
}

async function loadOptions(){
  let d = null;
  try{
    const r = await fetch('/api/options');
    if(r && r.ok) d = await r.json();
  }catch(e){}
  const sec = document.getElementById('optsec');
  if(!sec) return;
  // 보여줄 게 없으면 섹션을 통째로 숨긴다 — 빈 칸이 '데이터 없음'처럼 자리를
  // 차지하는 것보다 없는 게 정직하다(기업 체력 패널에서 정한 규칙 그대로).
  if(!d || !d.summary || (!(d.calls||[]).length && !(d.puts||[]).length)){
    sec.style.display='none'; return;
  }
  sec.style.display='';
  const s = d.summary || {};
  // 접힌 줄 — 펼치지 않아도 쓸모가 있어야 한다.
  const bits = [];
  if(d.label) bits.push(d.label);
  if(d.remain_days!=null) bits.push('만기 '+d.remain_days+'일');
  if(s.pcr!=null) bits.push('풋콜 '+optNum(s.pcr,2));
  if(s.atm_iv!=null) bits.push('IV '+optNum(s.atm_iv,0)+'%');
  if(s.call_chg_sum) bits.push('오늘 콜 '+optSigned(s.call_chg_sum));
  const dig = document.getElementById('opt-dig');
  if(dig) dig.textContent = bits.join(' · ');

  // 숫자 3개. 콜 벽은 없다 — 범위 따라 흔들려 숫자로 단정하지 않기로 했다.
  const nums = document.getElementById('opt-nums');
  if(nums){
    nums.innerHTML =
        optCard('풋콜 비율', optNum(s.pcr,2), s.pcr==null?'거래 없음':'풋÷콜 거래량')
      + optCard('ATM 변동성', s.atm_iv==null?'–':optNum(s.atm_iv,0)+'%',
                s.atm_strike==null?'거래된 행사가 없음':'행사가 '+optNum(s.atm_strike,1))
      + optCard('풋 벽', optNum(s.put_wall,1),
                '지수 ±'+optNum(s.wall_pct)+'% 안에서');
  }

  optDraw(document.getElementById('opt-chg'), d, 2, true);   // 오늘의 증감(마커 O)
  optDraw(document.getElementById('opt-oi'),  d, 1, false);  // 누적 미결제(마커 X)

  // 각주 — 기준 시각, 수집 중, 실패 건수를 숨기지 않는다.
  const foot = document.getElementById('opt-foot');
  if(foot){
    const parts = [];
    if(d.ts) parts.push(new Date(d.ts*1000).toLocaleTimeString('ko-KR',
      {hour:'2-digit', minute:'2-digit'})+' 기준');
    if(d.collecting) parts.push('집계 중');
    else if(d.stale) parts.push('갱신 지연');
    if(d.failed) parts.push('조회 실패 '+d.failed+'건 — 합계 지표(풋콜 비율)에 그만큼 빠져 있다');
    parts.push('빨강=콜 · 파랑=풋 · 음영=지수 ±'+optNum((s.wall_pct||20))+'%');
    foot.textContent = parts.join(' · ');
  }
}
loadOptions(); setInterval(loadOptions, 300000);   // 5분마다 재확인(수집은 서버가 1시간)
window.addEventListener('resize', function(){
  const d = window.__optLast; if(d) { optDraw(document.getElementById('opt-chg'), d, 2, true);
                                      optDraw(document.getElementById('opt-oi'), d, 1, false); }
});
"""
```

> `optDraw`는 Task 7에서 채운다. 이 태스크에선 `JS` 문자열 맨 앞에 다음 자리막이를 넣어 `loadOptions()`가 `ReferenceError` 없이 끝까지 돌게 한다:
>
> ```js
> function optDraw(cv, d, fi, mark){ window.__optLast = d; }   // Task 7에서 구현
> ```

- [ ] **Step 4: `dashboard.py`에 끼운다**

`backend/report/dashboard.py`:

1. 임포트에 추가 — `from backend.report import options_panel as _optp`
2. `_TEMPLATE`의 `<style>` 블록 끝(또는 `__BASE_CSS__` 다음 줄)에 `__OPT_CSS__` 추가
3. `<div id="cards"></div>` **앞**에 `__OPT_HTML__` 추가 — 옵션은 시장 컨텍스트라 관심종목 카드 위에 온다
4. 페이지 로직 `<script>` 끝(`loadMarket(); setInterval(...)` 다음)에 `__OPT_JS__` 추가
5. `render_dashboard`의 치환 체인에 추가:

```python
            .replace("__OPT_CSS__", _optp.CSS)
            .replace("__OPT_HTML__", _optp.HTML)
            .replace("__OPT_JS__", _optp.JS)
```

- [ ] **Step 5: 테스트 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add backend/report/options_panel.py backend/report/dashboard.py tests/test_dashboard.py
git commit -m "feat(options): 대시보드 옵션 섹션 — 요약줄·숫자 3개(콜 벽 없음)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Canvas 차트 2개 + node 실행 테스트

**Files:**
- Modify: `backend/report/options_panel.py` (`optDraw` 구현)
- Test: `tests/test_options_panel_js.py` (신규)

**Interfaces:**
- Consumes: Task 6의 `loadOptions()` 호출 규약 — `optDraw(canvas, payload, fieldIndex, mark)`
  - `fieldIndex`: `1`=누적 미결제 · `2`=당일 증감 (payload의 `cols` 순서)
  - `mark`: 최대 증가 지점에 마커를 찍을지 — **증감 차트만 true**
- Produces: 그려진 캔버스. 반환값 없음.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_options_panel_js.py`:

```python
"""옵션 섹션 JS 실행 스모크 — 문자열 검사가 아니라 node로 실제 실행한다.

/live에서 확립한 패턴 그대로다. 문자열 존재 검사로는 ReferenceError(렌더가 중간에
죽어 이후가 전부 미표시)를 못 잡는다. 캔버스는 없는 환경이라 2D 컨텍스트를 기록용
스텁으로 대신하고, 어떤 도형이 어디에 그려졌는지를 단언한다.
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
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(s => s.indexOf('loadOptions') >= 0);
if (!code) { console.log(JSON.stringify({error: 'loadOptions 스크립트 없음'})); process.exit(0); }

const ops = [];                       // 캔버스에 그려진 것 전부를 기록한다
function ctx(){
  const o = {ops};
  const rec = name => function(){ ops.push([name].concat([...arguments])); };
  ['clearRect','fillRect','beginPath','moveTo','lineTo','stroke','fill','arc',
   'fillText','setTransform','closePath','save','restore'].forEach(n => o[n] = rec(n));
  Object.defineProperty(o, 'fillStyle', {set(v){ ops.push(['fillStyle', v]); }, get(){ return ''; }});
  Object.defineProperty(o, 'strokeStyle', {set(v){ ops.push(['strokeStyle', v]); }, get(){ return ''; }});
  Object.defineProperty(o, 'lineWidth', {set(){}, get(){ return 1; }});
  Object.defineProperty(o, 'globalAlpha', {set(){}, get(){ return 1; }});
  Object.defineProperty(o, 'font', {set(){}, get(){ return ''; }});
  Object.defineProperty(o, 'textAlign', {set(){}, get(){ return ''; }});
  Object.defineProperty(o, 'textBaseline', {set(){}, get(){ return ''; }});
  return o;
}
const validIds = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));
const els = {};
function mk(id){
  const e = {id, textContent:'', innerHTML:'', className:'', style:{},
             clientWidth: 340, getAttribute: k => (k === 'height' ? '190' : null)};
  if (id === 'opt-chg' || id === 'opt-oi') { e.getContext = () => ctx(); }
  return e;
}
global.document = {
  getElementById: id => validIds.has(id) ? (els[id] || (els[id] = mk(id))) : null,
  querySelectorAll: () => [],
};
global.window = {devicePixelRatio: 2, addEventListener: () => {}, __optLast: null};
global.getComputedStyle = () => ({getPropertyValue: k =>
  ({'--up':'#e5342f','--down':'#1f66e0','--border':'#dcdfe6','--text-3':'#8b93a4'}[k] || '')});
global.setInterval = () => 0;
global.fetch = async () => ({ok: true, json: async () => payload});

(async () => {
  try {
    eval(code);
    await new Promise(r => setTimeout(r, 30));    // loadOptions()가 await를 끝내도록
    console.log(JSON.stringify({
      ok: true,
      dig: (els['opt-dig'] || {}).textContent || '',
      nums: (els['opt-nums'] || {}).innerHTML || '',
      foot: (els['opt-foot'] || {}).textContent || '',
      display: ((els['optsec'] || {}).style || {}).display,
      ops,
    }));
  } catch (e) {
    console.log(JSON.stringify({error: String(e && e.stack || e)}));
  }
})();
"""


def _run(tmp_path, payload):
    from backend.report.dashboard import render_dashboard
    html = tmp_path / "dash.html"
    html.write_text(render_dashboard([], [], "2026-08-05"), encoding="utf-8")
    data = tmp_path / "opt.json"
    data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    js = tmp_path / "h.js"
    js.write_text(_HARNESS, encoding="utf-8")
    out = subprocess.run(["node", str(js), str(html), str(data)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert "error" not in res, res["error"]
    return res


def _payload(**over):
    d = {"expiry": "202608", "label": "8월물", "remain_days": 9, "spot": 1039.35,
         "cols": ["strike", "oi", "oi_chg"],
         "calls": [[1000.0, 5000, 100], [1050.0, 9000, 300], [1300.0, 8000, 2214],
                   [1597.5, 26000, -224]],
         "puts": [[625.0, 22000, 10], [1000.0, 7000, 1189], [1050.0, 3000, -50]],
         "summary": {"pcr": 0.75, "put_wall": 1000.0, "wall_pct": 20.0,
                     "atm_iv": 87.0, "atm_strike": 1050.0,
                     "call_chg_sum": 6963, "put_chg_sum": 5616,
                     "top_call": {"strike": 1300.0, "oi_chg": 2214},
                     "top_put": {"strike": 1000.0, "oi_chg": 1189}},
         "failed": 0, "ts": 1786000000.0, "collecting": False, "stale": False}
    d.update(over)
    return d


@needs_node
def test_section_renders_digest_numbers_and_both_charts(tmp_path):
    res = _run(tmp_path, _payload())
    assert "8월물" in res["dig"] and "만기 9일" in res["dig"] and "풋콜 0.75" in res["dig"]
    assert "풋 벽" in res["nums"] and "1,000.0" in res["nums"]
    assert "지수 ±20% 안에서" in res["nums"]        # 범위 병기 — 정직성 규칙
    assert "콜 벽" not in res["nums"]                # 콜 벽은 숫자로 내지 않는다
    rects = [o for o in res["ops"] if o[0] == "fillRect"]
    assert len(rects) >= 14                          # 두 차트 × (막대 7개 + 밴드)


@needs_node
def test_negative_change_bars_extend_opposite_side(tmp_path):
    """증감이 음수면 중앙선 반대쪽으로 뻗어야 한다 — '줄었음'을 그대로 보여준다.
    콜(위쪽)의 −224는 아래로, 풋(아래쪽)의 −50은 위로 간다."""
    res = _run(tmp_path, _payload())
    # fillRect(x, y, w, h) — 음수 막대는 h의 부호나 y가 중앙선을 넘어가야 한다
    rects = [o for o in res["ops"] if o[0] == "fillRect" and abs(o[4]) > 0.5]
    assert any(o[4] > 0 for o in rects) and any(o[4] < 0 for o in rects)


@needs_node
def test_markers_only_on_change_chart(tmp_path):
    """누적 차트의 최댓값은 사다리 끝(1,597.5)이다 — 거기에 마커를 찍으면
    '숫자로 내지 말라'고 한 값을 차트가 강조하게 된다. 마커는 증감에만."""
    res = _run(tmp_path, _payload())
    arcs = [o for o in res["ops"] if o[0] == "arc"]
    assert len(arcs) == 2                            # 증감 차트의 콜·풋 최대 증가 2개


@needs_node
def test_section_hides_itself_when_board_is_empty(tmp_path):
    res = _run(tmp_path, _payload(calls=[], puts=[], summary={}))
    assert res["display"] == "none"
    assert [o for o in res["ops"] if o[0] == "fillRect"] == []


@needs_node
def test_footer_states_failures_and_collecting(tmp_path):
    res = _run(tmp_path, _payload(failed=30, collecting=True))
    assert "30건" in res["foot"] and "집계 중" in res["foot"]


@needs_node
def test_missing_values_render_dash_not_zero(tmp_path):
    """모르는 값을 0으로 꾸미지 않는다."""
    res = _run(tmp_path, _payload(summary={"pcr": None, "put_wall": None,
                                           "wall_pct": 20.0, "atm_iv": None,
                                           "atm_strike": None, "call_chg_sum": 0,
                                           "put_chg_sum": 0, "top_call": None,
                                           "top_put": None}))
    assert "–" in res["nums"] and "0.00" not in res["nums"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_options_panel_js.py -v`
Expected: FAIL — `assert len(rects) >= 14` (자리막이 `optDraw`가 아무것도 안 그린다)

- [ ] **Step 3: `optDraw`를 구현한다**

`backend/report/options_panel.py`의 `JS` 문자열에서 자리막이를 지우고 그 자리에:

```javascript
// ── 행사가별 분포 차트 — 중앙선 위=콜(빨강) 아래=풋(파랑), 음수는 반대쪽. ──
// 막대가 780~1,012개라 SVG가 아니라 Canvas다. fi는 payload.cols의 인덱스
// (1=누적 미결제, 2=당일 증감). mark는 최대 증가 지점 마커 — 증감 차트만 true다.
// 누적의 최댓값은 사다리 끝(복권·보험이 쌓인 자리)이라 강조하면 오해를 만든다.
function optDraw(cv, d, fi, mark){
  window.__optLast = d;
  if(!cv || !cv.getContext) return;
  const calls = d.calls || [], puts = d.puts || [];
  if(!calls.length && !puts.length) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 340;
  const h = parseInt(cv.getAttribute('height'), 10) || 190;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);

  const cs = getComputedStyle(document.documentElement);
  const CV = k => (cs.getPropertyValue(k) || '').trim();
  const UP = CV('--up') || '#e5342f', DN = CV('--down') || '#1f66e0';
  const LN = CV('--border') || '#dcdfe6', TX = CV('--text-3') || '#8b93a4';

  const all = calls.concat(puts);
  let kmin = Infinity, kmax = -Infinity, vmax = 0;
  const ks = [];
  all.forEach(function(r){
    const k = r[0], v = Math.abs(r[fi] || 0);
    if(k < kmin) kmin = k; if(k > kmax) kmax = k; if(v > vmax) vmax = v;
    ks.push(k);
  });
  if(!(kmax > kmin) || !vmax) return;

  const padL = 4, padR = 4, padB = 15;
  const cy = (h - padB) / 2, half = cy - 10;
  const X = k => padL + (k - kmin) / (kmax - kmin) * (w - padL - padR);
  // 막대 폭 = 인접 행사가 간격. 행사가 사다리는 등간격이라 최소 간격이 곧 한 칸.
  ks.sort(function(a, b){ return a - b; });
  let step = kmax - kmin;
  for(let i = 1; i < ks.length; i++){ const g2 = ks[i] - ks[i-1]; if(g2 > 0 && g2 < step) step = g2; }
  const bw = Math.max(1, (X(kmin + step) - X(kmin)) - 0.5);

  // 지수 ±20% 밴드 음영 — 벽을 이 안에서만 읽는다는 걸 눈으로 보여준다.
  const spot = d.spot, pct = ((d.summary || {}).wall_pct || 20) / 100;
  if(spot){
    const x1 = Math.max(padL, X(spot * (1 - pct)));
    const x2 = Math.min(w - padR, X(spot * (1 + pct)));
    if(x2 > x1){ g.globalAlpha = 0.05; g.fillStyle = TX;
                 g.fillRect(x1, 0, x2 - x1, h - padB); g.globalAlpha = 1; }
  }

  // 중앙선
  g.strokeStyle = LN; g.lineWidth = 1;
  g.beginPath(); g.moveTo(padL, cy); g.lineTo(w - padR, cy); g.stroke();

  function bars(rows, color, up){
    g.fillStyle = color;
    rows.forEach(function(r){
      const v = r[fi] || 0;
      if(!v) return;
      const len = Math.abs(v) / vmax * half;
      // up이면 위로 뻗는 게 기본. 값이 음수면 부호가 뒤집혀 반대쪽으로 간다.
      const dir = (up ? -1 : 1) * (v < 0 ? -1 : 1);
      g.fillRect(X(r[0]) - bw / 2, cy, bw, dir * len);
    });
  }
  bars(calls, UP, true);
  bars(puts, DN, false);

  // 현재 지수 세로선
  if(spot && spot >= kmin && spot <= kmax){
    g.strokeStyle = TX; g.lineWidth = 1;
    g.beginPath(); g.moveTo(X(spot), 0); g.lineTo(X(spot), h - padB); g.stroke();
  }

  // 최대 증가 지점 마커 — 증감 차트에만.
  if(mark){
    [[calls, UP, true], [puts, DN, false]].forEach(function(t){
      const rows = t[0], color = t[1], up = t[2];
      let best = null;
      rows.forEach(function(r){ const v = r[fi] || 0;
        if(v > 0 && (!best || v > best[fi])) best = r; });
      if(!best) return;
      const len = Math.abs(best[fi]) / vmax * half;
      const y = cy + (up ? -1 : 1) * len;
      g.fillStyle = color;
      g.beginPath(); g.arc(X(best[0]), y, 3, 0, Math.PI * 2); g.fill();
      g.font = '600 10px system-ui, sans-serif';
      g.textAlign = X(best[0]) > w * 0.75 ? 'right' : 'left';
      g.textBaseline = up ? 'bottom' : 'top';
      const tx = Math.min(w - padR, Math.max(padL, X(best[0]) + (g.textAlign === 'right' ? -5 : 5)));
      g.fillText(optNum(best[0], 0) + ' +' + optNum(best[fi]), tx, y + (up ? -4 : 4));
    });
  }

  // 가로축 — 양 끝과 현재 지수만. 780칸에 눈금을 촘촘히 달면 글자가 겹친다.
  g.fillStyle = TX; g.font = '10px system-ui, sans-serif'; g.textBaseline = 'top';
  g.textAlign = 'left';  g.fillText(optNum(kmin, 0), padL, h - padB + 3);
  g.textAlign = 'right'; g.fillText(optNum(kmax, 0), w - padR, h - padB + 3);
  if(spot && spot >= kmin && spot <= kmax){
    g.textAlign = 'center';
    g.fillText('지수 ' + optNum(spot, 0), Math.min(w - 34, Math.max(34, X(spot))), h - padB + 3);
  }
}
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_options_panel_js.py -v`
Expected: PASS (6 passed — node 없으면 skip)

- [ ] **Step 5: 라이트/다크 아이폰 폭 스크린샷으로 눈 검증**

Run: `.venv/bin/python -m harness verify`
확인할 것(스펙 §화면 대비):
1. 증감 차트가 누적 차트 **위**에 있다
2. 음수 막대가 중앙선 반대쪽으로 뻗는다
3. 마커 글자가 캔버스 밖으로 잘리지 않는다(390px 폭)
4. 다크 모드에서 밴드 음영·중앙선이 보인다
5. 숫자 3장 중 어디에도 "콜 벽"이 없다

- [ ] **Step 6: 커밋**

```bash
git add backend/report/options_panel.py tests/test_options_panel_js.py
git commit -m "feat(options): 행사가 분포 Canvas 차트 2개 — 증감 위, 누적 아래

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: 장중 실측(O4) + 문서 마무리

**Files:**
- Modify: `docs/superpowers/specs/2026-08-05-kospi200-options-design.md`
- Modify: `docs/superpowers/plans/2026-08-05-kospi200-options.md` (이 파일 — 진행 상태)

**Interfaces:** 없음(검증·기록 태스크).

> **이 태스크는 평일 09:00~15:45 KST에만 할 수 있다.** 그 전에 도달하면 Task 7까지 커밋해 두고 여기서 멈춘다 — 추측으로 채우지 않는다.

- [ ] **Step 1: 실서버를 건드리지 않고 한 회차를 실측한다**

8000 실서버는 불가침이므로 별도 프로세스에서 수집기만 돌린다. 스크래치패드에
`o4_live.py`를 만들어(커밋 금지):

```python
"""O4 — 옵션 한 회차 실측. 8000 실서버 미접촉, REST 읽기 전용."""
import asyncio
import time

from backend.api import marketdata as md
from backend.flow.candles import _get_client

t0 = time.time()
d = asyncio.run(md._collect_options(_get_client()))
print("소요 %.0f초 · 만기 %s(%s) · 잔존 %s일 · 지수 %s" % (
    time.time() - t0, d["expiry"], d["label"], d["remain_days"], d["spot"]))
print("콜 %d · 풋 %d · 실패 %d건" % (len(d["calls"]), len(d["puts"]), d["failed"]))
print("요약", d["summary"])
```

Run: `.venv/bin/python <scratchpad>/o4_live.py`

**기록할 것(추측 금지 — 나온 값만 적는다)**:
- 회차 소요 시간과 실패 건수 → 스펙 §유량의 실측 표에 한 줄 추가
- `EGW00201`이 났는지 (실패 건수 > 0이면 원인을 로그로 확인)
- 풋 벽이 여전히 1,000인지 (다른 날에도 요지부동인지가 §정직성 규칙의 근거다)
- ATM IV가 거래된 행사가에서 80~92% 대인지

- [ ] **Step 2: `/live` 수급이 안 깨졌는지 확인한다**

옵션 배치가 도는 동안 `/live`가 `EGW00201`을 맞지 않아야 한다(초당 5건 상한의 존재 이유).

```bash
tail -200 <실서버 로그> | grep -c "EGW00201"
```

Expected: 0. 0이 아니면 `_OPT_RATE`를 3.0으로 낮추고 다시 잰다.

- [ ] **Step 3: 실서버에 반영하고 화면을 본다**

```bash
# graceful SIGTERM 후 .venv/bin/python으로만 재기동(시스템 python3.9엔 pydantic_settings 없음)
```

대시보드에서 확인: 섹션이 뜨는지 · 접힌 줄이 읽히는지 · 차트 둘이 그려지는지 ·
각주의 기준 시각이 맞는지.

- [ ] **Step 4: 스펙에 실측 결과를 적는다**

`docs/superpowers/specs/2026-08-05-kospi200-options-design.md`에 `## 실제 출하` 절을 만들어
Step 1~3에서 **실제로 관측된 값**을 적는다. 계획대로 안 된 것이 있으면 그것도 적는다.

- [ ] **Step 5: 커밋**

```bash
git add docs/
git commit -m "docs(options): O4 장중 실측 결과 반영

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## 자체 검토 결과

**스펙 커버리지**

| 스펙 절 | 태스크 |
|---|---|
| §데이터 확보 1) 종목마스터 | T1 |
| §데이터 확보 2) 단건 시세(`output1` 함정) | T2(`parse_quote`) · T3(`option_quote`) |
| §데이터 확보 3) 만기 목록 TR | **의도적 삭제** — §스펙 대비 변경 ① |
| §유량(초당 5건·백오프) | T3 |
| §아키텍처 `optmaster.py` | T1 |
| §아키텍처 `options.py` 6함수 | T2 |
| §아키텍처 `marketdata.get_options` | T3·T4 |
| §아키텍처 `app.py` 라우트 | T5 |
| §아키텍처 `dashboard.py` 섹션 | T6 (→ `options_panel.py`로 분리) |
| §화면 접힌 요약줄 | T6 |
| §화면 차트 2개(증감 위) | T7 |
| §화면 숫자 3개 | T6 |
| §정직성 규칙 4항 | T2(콜 벽 없음·ATM IV 필터) · T6(범위 병기·실패 건수) · T7(마커 제한) |
| §데이터 흐름 TTL·백그라운드·신선도 | T4 |
| §저장 `options_<expiry>.json` | T4 |
| §에러 처리 섹션 독립 실패 | T4(`{}` 반환) · T6(섹션 숨김) |
| §테스트 4종 | T1·T2·T3+T4·T7 |

**작성 중 잡은 문제 7개**

1. **만기 목록 TR과 마스터가 같은 일을 한다** — TR을 뺐다(§변경 ①). 실패 모드가 하나 준다.
2. **`output3`의 코스피200 필드명이 실측에 없다** — 추측하면 `spot=0`이 되고 그 순간 `wall()`·`atm_iv()`가 통째로 무의미해진다. 검증된 `index("2001")`로 바꿨다(§변경 ②).
3. **누적 차트에 최댓값 마커를 찍으면 정직성 규칙과 충돌한다** — 누적의 1위는 사다리 끝(1,597.5)이고, 그건 스펙이 "숫자로 내지 말라"고 한 바로 그 값이다. 마커를 증감 차트로 한정했다(§변경 ③) 그리고 T7에 회귀 테스트를 걸었다.
4. **테스트 fixture가 0을 두 가지 뜻으로 썼다** — `_rows()`가 strike 0.0부터 시작하면 "응답에 행사가가 없음"과 "마스터의 행사가가 0"을 구분할 수 없다. 1.0부터 시작하도록 고쳤다.
5. **기본 인자에 상수를 쓰면 monkeypatch가 안 먹는다** — `def _collect_chain(..., rate=_OPT_RATE)`는 기본값을 정의 시점에 굽는다. 테스트가 `_OPT_RATE`를 1000으로 바꿔도 5.0이 그대로 쓰여 회차 테스트마다 3.5분씩 걸릴 뻔했다. 기본값을 `None`으로 두고 함수 안에서 상수를 읽는다.
6. **날짜에 묶인 테스트** — `front_month()`가 "만기일이 오늘 이후"로 고르므로, 만기 fixture를 `202608`로 두면 2026-08-13이 지난 날 수집 테스트가 통째로 깨진다. fixture에서 `kst.today`를 고정했다.
7. **가짜 실패가 실제로 실패하지 않았다** — "KIS가 죽어도 직전 보드를 유지한다" 테스트가 `index()`를 터뜨렸는데, `_collect_options`는 현물 조회 실패를 `spot=None`으로 흡수하고 수집을 계속한다. 그대로 뒀으면 캐시가 덮어써져 테스트가 반대 결론을 냈을 것이다. `option_quote`를 터뜨리도록 바꿨다.

**의도적으로 남긴 간극 2개**

- **만기일 공휴일 보정 없음.** `expiry_date()`는 둘째 목요일만 본다. 그 목요일이 공휴일이면 실제 만기는 하루 앞이다. 전 종목을 3.5분 돌고 나서 알면 늦으므로 `_pick_expiry()`가 **한 건만 찔러** 잔존일수로 확인한다. 프로브까지 실패하면 계산값을 쓴다 — 최악의 경우 만기 당일 하루 데이터가 이상해지고, 다음 회차에 자동 복구된다. 휴장일 달력을 새로 만들 만한 값어치가 없다.
- **차트 툴팁·확대 없음.** 스펙에 없고, 이 화면은 "오늘 어디에 돈이 갔나"를 한눈에 보는 용도다. 필요해지면 그때 붙인다(YAGNI).

**타입 일관성 확인** — `optmaster` 행의 키(`code`/`side`/`expiry`/`strike`)가 T3 수집기와 T4 체인에서 같은 이름으로 쓰인다. `options` 행의 키(`strike`/`price`/`vol`/`oi`/`oi_chg`/`iv`/`delta`/`remain_days`)가 T2 지표 함수, T3 수집기, T4 `_opt_pack`에서 일치한다. JS 쪽 `cols` 인덱스(1=oi, 2=oi_chg)가 T4 `_opt_pack`의 배열 순서와 T7 `optDraw(fi)`에서 일치한다.
