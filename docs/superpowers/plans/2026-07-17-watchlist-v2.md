# 관심종목 v2 (계정별 · 보유/수익 · 미국주식 · 드래그편집) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로그인 계정별로 격리된 관심종목·보유·감시선을 저장하고, 보유 기반 수익(P&L)·미국주식을 위젯/대시보드에 표시하며, 드래그 순서변경·스와이프 삭제 편집을 제공한다.

**Architecture:** 계정 키=세션 이메일. 계정당 `users/<uid>.json` 한 파일(watchlist·watch_lines·widget_token). 위젯은 Bearer 토큰→계정 매핑. US 티커는 KR 전용 분석 파이프라인에서 제외하고 시세/위젯에만 노출. 교차계정 격리를 P&L 착수 전 테스트 게이트로 강제.

**Tech Stack:** FastAPI 순수 ASGI 게이트, KIS OpenAPI(국내 FHKST01010100 / 해외 HHDFS00000300), Scriptable JS, pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-watchlist-v2-accounts-holdings-us.md` (커밋 8b7dc21)

## Global Constraints

- **Python 3.9 호환**: `match`·`X | Y` 금지, `Optional[...]` 사용.
- **최우선 불변식**: "모든 경로가 실제로 잠겼는가" — 새 라우트는 `tests/test_auth.py` PROTECTED에 추가.
- **계정 격리 불변식**: A의 토큰/세션으로 B의 watchlist·보유·watch_lines 절대 조회 불가. `email_for_token` 미매칭 → None(default 폴백 금지).
- **비마스터 계정 watch_lines는 config 폴백 금지** — 파일 부재 시 빈 배열(config.watch_lines=마스터 실매도가).
- **US 티커는 KR 분석 파이프라인 제외**: `build_dashboard`·`_analyze`·`fetch_live_prices`는 `get_kr_codes(email)`만.
- **email 정규화**: `norm_email(e)=e.strip().lower()` 단일 함수 경유(마스터 uid 분리 방지).
- **자기완결 HTML**(외부 CDN 0), KIS=유일 시세 소스, 응답 계약 화이트리스트(감시선·조언·타계정 금지).
- 테스트: `.venv/bin/python -m pytest tests/ -q -p no:warnings` (루트, .venv). 미설정 시나리오는 Settings에 값 명시(.env 오염 방지).
- 커밋 트레일러: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01AfTjj4WQcXs5qsfWaAgtCi`

## File Structure

| 파일 | 역할 | 생성/수정 |
|---|---|---|
| `backend/config.py` | `default_account` 설정 추가 | 수정 |
| `backend/flow/userstore.py` | 계정별 저장소(watchlist·get_kr_codes·watch_lines·token·email_for_token·마이그레이션) | **생성** |
| `backend/flow/pnl.py` | 수익 계산 순수 함수 | **생성** |
| `backend/flow/usquote.py` | 미국 시세(거래소 순회·이름·캐시) | **생성** |
| `backend/api/auth.py` | AuthGate Bearer→email + scope 전달 | 수정 |
| `backend/api/widget.py` | KR/US 분기·보유 수익 조립 | 수정 |
| `backend/api/app.py` | 라우트 email 해석·/api/watchlist items 계약·widget/watch 배선 | 수정 |
| `backend/report/widget_setup.py` | 계정별 토큰 페이지 + 위젯 2줄 재디자인 | 수정 |
| `backend/report/dashboard.py` | 관리 리스트(버튼 폴백)+드래그/스와이프(별도 script)+US 검색 | 수정 |
| `backend/report/live_page.py` | `get_lines(email,code)` 전파 | 수정 |
| `backend/cli.py` | `build_dashboard`/`fetch_live_prices` KR 코드만 | 수정 |
| `backend/mcp/tools.py` | `_analyze` KR 코드만 | 수정 |
| `backend/flow/semi.py` | `_us_quote` 로직을 usquote로 공유 | 수정 |
| `docs/widget-guide.md` | 계정 토큰·수익 경고·큰 위젯·US·편집 | 수정 |
| `tests/test_userstore.py` · `test_pnl.py` · `test_usquote.py` | 신규 | **생성** |
| `tests/test_widget.py`·`test_auth.py`·`test_dashboard.py`·`test_widget_setup.py` | 케이스 추가 | 수정 |

---

# Phase 0 — 설정

### Task 1: `SM_DEFAULT_ACCOUNT` + `norm_email`

**Files:** Modify `backend/config.py` (widget_token 아래); Create `backend/flow/userstore.py` (norm_email만 먼저); Test `tests/test_userstore.py`

**Interfaces:** Produces `settings.default_account: Optional[str]`; `userstore.norm_email(e)->str`.

- [ ] **Step 1: 실패 테스트**

```python
# tests/test_userstore.py
"""계정별 저장소 — 격리·검증·마이그레이션·토큰. 설계 2026-07-17.
⚠ Settings는 .env 자동로드 — 테스트는 tmp cache_dir·명시 값으로 격리."""
def test_norm_email():
    from backend.flow.userstore import norm_email
    assert norm_email("  Master@Gmail.com ") == "master@gmail.com"
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_userstore.py -x -q` → ImportError.

- [ ] **Step 3: 구현** — `backend/config.py` widget_token 줄 아래:

```python
    # 계정별 데이터 기준 계정(로그인 이메일). 미설정 시 allowlist 첫 이메일(경고).
    default_account: Optional[str] = None       # SM_DEFAULT_ACCOUNT
```

`backend/flow/userstore.py` 새 파일 시작:

```python
from __future__ import annotations

"""계정별 저장소 — 로그인 이메일 기준으로 관심종목·보유·감시선·위젯토큰 격리.
저장: <cache_dir>/users/<uid>.json. 감시선 검증은 watch.py 재사용. 설계 2026-07-17."""

import hashlib
import json
import os
import re
import secrets
import threading
from pathlib import Path

from backend.config import settings

_LOCK = threading.Lock()
_KR_RE = re.compile(r"^\d{6}$")
_US_RE = re.compile(r"^[A-Z]{1,5}([.][A-Z])?$")
MAX_ITEMS = 10


def norm_email(e) -> str:
    return str(e or "").strip().lower()
```

- [ ] **Step 4: 통과** — `.venv/bin/python -m pytest tests/test_userstore.py -q` → 1 passed.
- [ ] **Step 5: 커밋** — `git add backend/config.py backend/flow/userstore.py tests/test_userstore.py && git commit -m "feat(userstore): SM_DEFAULT_ACCOUNT + norm_email 기반"`

---

# Phase 1 — 계정 저장소 (기반)

### Task 2: `userstore` watchlist + get_kr_codes + 검증

**Files:** Modify `backend/flow/userstore.py`; Test `tests/test_userstore.py`

**Interfaces:**
- Consumes: `norm_email`, `settings.default_account`/`settings.watchlist`.
- Produces: `_uid(email)`, `_path(email)`, `_load(email)->dict`, `_save(email,data)`, `default_account()->str`,
  `get_watchlist(email)->list[dict]`, `set_watchlist(email,items)->list[dict]`, `get_kr_codes(email)->list[str]`.

- [ ] **Step 1: 실패 테스트** — `tests/test_userstore.py`에 추가:

```python
import pytest

M = "master@gmail.com"
B = "b@gmail.com"


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "default_account", M)
    monkeypatch.setattr(settings, "watchlist", ["005930", "000660"])


def test_master_seeds_others_empty():
    from backend.flow import userstore as us
    assert [i["code"] for i in us.get_watchlist(M)] == ["005930", "000660"]  # 마스터 시드
    assert us.get_watchlist(B) == []                                        # 비마스터 빈


def test_set_get_roundtrip_and_isolation():
    from backend.flow import userstore as us
    us.set_watchlist(M, [{"code": "005930", "market": "KR", "shares": 10, "avg": 230000}])
    us.set_watchlist(B, [{"code": "NVDA", "market": "US", "shares": 5, "avg": 170.5}])
    assert us.get_watchlist(M)[0]["code"] == "005930"
    assert us.get_watchlist(B)[0]["code"] == "NVDA"           # 격리
    assert all(i["market"] == "KR" for i in us.get_watchlist(M))


def test_get_kr_codes_excludes_us():
    from backend.flow import userstore as us
    us.set_watchlist(M, [{"code": "005930", "market": "KR"},
                         {"code": "NVDA", "market": "US"}])
    assert us.get_kr_codes(M) == ["005930"]                   # US 제외


def test_set_validates():
    from backend.flow import userstore as us
    with pytest.raises(ValueError):
        us.set_watchlist(M, [{"code": "12345", "market": "KR"}])   # 6자리 아님
    with pytest.raises(ValueError):
        us.set_watchlist(M, [])                                     # 최소 1
    with pytest.raises(ValueError):
        us.set_watchlist(M, [{"code": "A%d" % i, "market": "US"} for i in range(11)])
    with pytest.raises(ValueError):
        us.set_watchlist(M, [{"code": "005930", "market": "KR", "avg": -1}])  # 음수


def test_us_avg_keeps_float():
    from backend.flow import userstore as us
    saved = us.set_watchlist(M, [{"code": "NVDA", "market": "US", "shares": 1, "avg": 170.55}])
    assert saved[0]["avg"] == 170.55           # US 소수 보존(int 반올림 금지)
```

- [ ] **Step 2: 실패 확인** — ImportError/AttributeError.

- [ ] **Step 3: 구현** — `userstore.py`에 추가:

```python
def _uid(email) -> str:
    return hashlib.sha256(norm_email(email).encode("utf-8")).hexdigest()[:16]


def _dir() -> Path:
    return Path(settings.cache_dir) / "users"


def _path(email) -> Path:
    return _dir() / (_uid(email) + ".json")


def default_account() -> str:
    if settings.default_account:
        return norm_email(settings.default_account)
    emails = [e.strip() for e in (settings.allowed_emails or "").split(",") if e.strip()]
    return norm_email(emails[0]) if emails else ""


def _load(email) -> dict:
    try:
        with open(_path(email), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(email, data) -> None:
    with _LOCK:
        p = _path(email)
        p.parent.mkdir(parents=True, exist_ok=True)
        data["email"] = norm_email(email)
        tmp = p.with_name(p.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)


def _clean_item(it) -> dict:
    """검증·정규화된 watchlist 항목(무효는 ValueError)."""
    if not isinstance(it, dict):
        raise ValueError("종목 항목 형식이 올바르지 않아요")
    code = str(it.get("code", "")).strip().upper()
    if _KR_RE.match(code):
        market = "KR"
    elif _US_RE.match(code):
        market = "US"
    else:
        raise ValueError("종목 코드는 6자리 숫자(국내) 또는 티커(미국)여야 해요: %s" % code)
    shares = it.get("shares")
    if shares is not None:
        shares = int(shares)
        if shares < 0:
            raise ValueError("보유 수량은 0 이상이어야 해요")
    avg = it.get("avg")
    if avg is not None:
        avg = float(avg)
        if avg <= 0:
            raise ValueError("평균매입가는 0보다 커야 해요")
        if market == "KR":
            avg = int(round(avg))          # 국내는 원 정수
    return {"code": code, "market": market, "shares": shares, "avg": avg}


def get_watchlist(email) -> list:
    email = norm_email(email)
    d = _load(email)
    items = d.get("watchlist")
    if isinstance(items, list):
        out = []
        for it in items:
            try:
                out.append(_clean_item(it))
            except ValueError:
                continue
        return out
    # 파일 없음: 마스터만 config 시드, 그 외 빈
    if email == default_account():
        return [{"code": c, "market": "KR", "shares": None, "avg": None}
                for c in settings.watchlist]
    return []


def set_watchlist(email, items) -> list:
    if not isinstance(items, list):
        raise ValueError("종목 목록(배열)이 필요해요")
    norm, seen = [], set()
    for it in items:
        c = _clean_item(it)
        key = (c["code"], c["market"])
        if key not in seen:
            seen.add(key)
            norm.append(c)
    if not norm:
        raise ValueError("관심종목은 최소 1개 필요해요")
    if len(norm) > MAX_ITEMS:
        raise ValueError("관심종목은 최대 %d개까지 저장할 수 있어요" % MAX_ITEMS)
    d = _load(norm_email(email))
    d["watchlist"] = norm
    _save(email, d)
    return norm


def get_kr_codes(email) -> list:
    return [i["code"] for i in get_watchlist(email) if i["market"] == "KR"]
```

- [ ] **Step 4: 통과** — `.venv/bin/python -m pytest tests/test_userstore.py -q` → all passed.
- [ ] **Step 5: 커밋** — `git commit -m "feat(userstore): 계정별 watchlist(dict배열)·get_kr_codes·검증·격리"`

---

### Task 3: `userstore` 감시선(watch_lines) — 비마스터 config 폴백 금지 (blocker)

**Files:** Modify `backend/flow/userstore.py`; Test `tests/test_userstore.py`

**Interfaces:** Produces `get_lines(email,code)->list`, `set_lines(email,code,lines)->list` (watch.py 검증 재사용).

- [ ] **Step 1: 실패 테스트** — 추가:

```python
def test_watch_lines_non_master_never_sees_config():
    """blocker 회귀 방지 — 비마스터 계정은 config 감시선(마스터 실매도가) 절대 못 봄."""
    from backend.flow import userstore as us
    from backend.config import settings
    settings.watch_lines = {"000660": [{"price": 1853000, "label": "절대선"}]}
    assert us.get_lines(B, "000660") == []                 # B는 빈(폴백 금지)
    assert us.get_lines(M, "000660")[0]["price"] == 1853000  # 마스터만 시드


def test_watch_lines_set_get_isolation():
    from backend.flow import userstore as us
    us.set_lines(M, "005930", [{"price": 70000, "label": "지지"}])
    assert us.get_lines(M, "005930")[0]["price"] == 70000
    assert us.get_lines(B, "005930") == []                 # 격리
```

- [ ] **Step 2: 실패 확인.**

- [ ] **Step 3: 구현** — `userstore.py`에 추가(watch.py의 검증 재사용):

```python
def get_lines(email, code) -> list:
    from backend.flow import watch
    email = norm_email(email)
    d = _load(email)
    lines = (d.get("watch_lines") or {}).get(code)
    if isinstance(lines, list):
        return watch._clean(lines)
    if email == default_account():
        return watch._clean(settings.watch_lines.get(code) or [])   # 마스터만 config 시드
    return []                                                        # 비마스터: 폴백 금지


def set_lines(email, code, lines) -> list:
    from backend.flow import watch
    norm = watch._validate_lines(lines)   # Task 3a: watch.py에 순수 검증 추출
    d = _load(norm_email(email))
    wl = d.get("watch_lines")
    if not isinstance(wl, dict):
        wl = {}
    wl[code] = norm
    d["watch_lines"] = wl
    _save(email, d)
    return norm
```

- [ ] **Step 3a: watch.py에 검증 추출** — `backend/flow/watch.py`의 `set_lines` 본문 검증부를 순수 함수로:

```python
def _validate_lines(lines) -> list:
    """감시선 검증·정규화(저장 무관). 위반 시 ValueError."""
    if not isinstance(lines, list):
        raise ValueError("감시선 목록(배열)이 필요해요")
    if len(lines) > MAX_LINES:
        raise ValueError("감시선은 최대 %d개까지 저장할 수 있어요" % MAX_LINES)
    norm = []
    for i, item in enumerate(lines):
        n = i + 1
        if not isinstance(item, dict):
            raise ValueError("%d번째 줄 형식이 올바르지 않아요" % n)
        if not _finite_pos(item.get("price")):
            raise ValueError("%d번째 줄: 가격은 0보다 큰 숫자여야 해요" % n)
        label = ("" if item.get("label") is None else str(item.get("label"))).strip()
        if not (1 <= len(label) <= MAX_LABEL):
            raise ValueError("%d번째 줄: 라벨은 1~%d자여야 해요" % (n, MAX_LABEL))
        norm.append({"price": int(round(float(item["price"]))), "label": label})
    return norm
```
그리고 기존 `set_lines`가 이 함수를 쓰도록 교체(중복 제거, 동작 불변 — 기존 test_watch.py 통과 유지).

- [ ] **Step 4: 통과** — `.venv/bin/python -m pytest tests/test_userstore.py tests/test_watch.py -q`.
- [ ] **Step 5: 커밋** — `git commit -m "feat(userstore): 계정별 감시선 — 비마스터 config 폴백 금지(자산정보 격리 blocker)"`

---

### Task 4: `userstore` 토큰(유저파일 단일원) + `email_for_token` + 회전

**Files:** Modify `backend/flow/userstore.py`; Test `tests/test_userstore.py`

**Interfaces:** Produces `get_token(email)`, `ensure_token(email)->str`, `rotate_token(email)->str`, `email_for_token(token)->Optional[str]`, `register_env_token(token,email)`.

- [ ] **Step 1: 실패 테스트** — 추가:

```python
def test_token_lifecycle_and_reverse():
    from backend.flow import userstore as us
    t = us.ensure_token(M)
    assert len(t) >= 20 and us.email_for_token(t) == M
    assert us.email_for_token("nope-" + "x" * 20) is None      # 미매칭 None(폴백 금지)


def test_token_rotation_kills_old():
    from backend.flow import userstore as us
    old = us.ensure_token(M)
    new = us.rotate_token(M)
    assert new != old
    assert us.email_for_token(new) == M
    assert us.email_for_token(old) is None                     # 구 토큰 즉시 사망


def test_cross_account_token_never_crosses():
    from backend.flow import userstore as us
    ta, tb = us.ensure_token(M), us.ensure_token(B)
    assert us.email_for_token(ta) == M and us.email_for_token(tb) == B
    assert us.email_for_token(ta) != B                         # 교차 금지
```

- [ ] **Step 2: 실패 확인.**

- [ ] **Step 3: 구현** — `userstore.py`에 추가(디렉터리 mtime 캐시):

```python
_tok_cache = {"mtime": None, "map": {}}


def get_token(email):
    return _load(norm_email(email)).get("widget_token")


def ensure_token(email) -> str:
    email = norm_email(email)
    d = _load(email)
    if not d.get("widget_token"):
        d["widget_token"] = secrets.token_urlsafe(32)
        _save(email, d)
    return d["widget_token"]


def rotate_token(email) -> str:
    email = norm_email(email)
    d = _load(email)
    d["widget_token"] = secrets.token_urlsafe(32)
    _save(email, d)
    return d["widget_token"]


def register_env_token(token, email) -> None:
    """마이그레이션 전용 — env SM_WIDGET_TOKEN을 고정 마스터 유저파일에 1회 등록."""
    email = norm_email(email)
    d = _load(email)
    if not d.get("widget_token"):
        d["widget_token"] = token
        _save(email, d)


def _rebuild_token_map():
    d = _dir()
    try:
        mtime = os.path.getmtime(d)
    except OSError:
        mtime = None
    if mtime != _tok_cache["mtime"]:
        m = {}
        try:
            for f in os.listdir(d):
                if f.endswith(".json"):
                    try:
                        with open(d / f, encoding="utf-8") as fh:
                            j = json.load(fh)
                        tok = j.get("widget_token")
                        if tok:
                            m[tok] = norm_email(j.get("email"))
                    except Exception:
                        continue
        except OSError:
            pass
        _tok_cache["mtime"], _tok_cache["map"] = mtime, m
    return _tok_cache["map"]


def email_for_token(token):
    if not token:
        return None
    return _rebuild_token_map().get(token)
```
(주의: `_save`가 파일을 쓰면 디렉터리 mtime이 바뀌어 다음 조회 시 맵이 재빌드된다 — 회전 즉시 반영. 테스트에서 rotate 후 os.listdir mtime이 동일 초라 안 바뀔 수 있으니, `_rebuild_token_map`은 mtime 외에 파일 수/이름도 아니라 — 안전하게 회전 시 `_tok_cache["mtime"]=None`으로 무효화하도록 rotate_token·ensure_token·register_env_token 끝에 `_tok_cache["mtime"]=None` 추가.)

- [ ] **Step 3a: 캐시 무효화 보강** — `ensure_token`/`rotate_token`/`register_env_token`의 `_save` 뒤에 `_tok_cache["mtime"] = None` 추가(동일-초 회전에도 구토큰 즉시 사망 보장).

- [ ] **Step 4: 통과** — `.venv/bin/python -m pytest tests/test_userstore.py -q`.
- [ ] **Step 5: 커밋** — `git commit -m "feat(userstore): 위젯 토큰 유저파일 단일원 + email_for_token(디렉터리캐시) + 회전(구토큰 즉시 사망)"`

---

### Task 5: 마이그레이션 (전역 → 마스터 계정)

**Files:** Modify `backend/flow/userstore.py`; Test `tests/test_userstore.py`

**Interfaces:** Produces `migrate_globals()` — 앱 시작 시 1회. 전역 watchlist.json·watch_lines.json·env 토큰을 마스터 파일로.

- [ ] **Step 1: 실패 테스트**:

```python
def test_migration_promotes_globals(tmp_path, monkeypatch):
    import json, os
    from backend.config import settings
    from backend.flow import userstore as us
    # 전역 파일 시드
    with open(os.path.join(str(tmp_path), "watchlist.json"), "w") as f:
        json.dump({"codes": ["005930", "000660"]}, f)
    with open(os.path.join(str(tmp_path), "watch_lines.json"), "w") as f:
        json.dump({"000660": [{"price": 1853000, "label": "절대선"}]}, f)
    monkeypatch.setattr(settings, "widget_token", "e" * 32)
    us.migrate_globals()
    assert [i["code"] for i in us.get_watchlist(M)] == ["005930", "000660"]
    assert us.get_lines(M, "000660")[0]["price"] == 1853000
    assert us.email_for_token("e" * 32) == M          # env 토큰 → 마스터 고정
```

- [ ] **Step 2: 실패 확인.**

- [ ] **Step 3: 구현** — `userstore.py`:

```python
def migrate_globals() -> None:
    """전역 저장물을 마스터 계정 파일로 1회 승격(이미 있으면 건너뜀). 앱 시작 시 호출."""
    master = default_account()
    if not master:
        return
    d = _load(master)
    changed = False
    if "watchlist" not in d:
        try:
            with open(Path(settings.cache_dir) / "watchlist.json", encoding="utf-8") as f:
                codes = (json.load(f) or {}).get("codes") or []
            if codes:
                d["watchlist"] = [{"code": c, "market": "KR", "shares": None, "avg": None}
                                  for c in codes if _KR_RE.match(str(c))]
                changed = True
        except Exception:
            pass
    if "watch_lines" not in d:
        try:
            with open(Path(settings.cache_dir) / "watch_lines.json", encoding="utf-8") as f:
                wl = json.load(f)
            if isinstance(wl, dict):
                d["watch_lines"] = wl
                changed = True
        except Exception:
            pass
    if settings.widget_token and not d.get("widget_token"):
        d["widget_token"] = settings.widget_token
        changed = True
    if changed:
        _save(master, d)
        _tok_cache["mtime"] = None
```

`backend/api/app.py`의 `create_app` 초입(위젯토큰 가드 뒤)에 호출:
```python
    from backend.flow import userstore as _userstore
    _userstore.migrate_globals()
```

- [ ] **Step 4: 통과** — `.venv/bin/python -m pytest tests/test_userstore.py -q`.
- [ ] **Step 5: 커밋** — `git commit -m "feat(userstore): 전역→마스터 계정 마이그레이션(watchlist·watch_lines·env토큰 고정)"`

---

### Task 6: 소비자 전환 (KR 코드만) + `/api/watchlist` items 계약 + 라우트 email 해석

**Files:** Modify `backend/api/app.py`, `backend/cli.py`, `backend/mcp/tools.py`, `backend/report/live_page.py`; Test `tests/test_widget.py`·`tests/test_auth.py`

**Interfaces:**
- Consumes: `userstore.get_watchlist/get_kr_codes/get_lines/set_lines/set_watchlist`, `default_account`.
- Produces: 라우트 헬퍼 `_email(request)->str` (세션 없으면 default_account); `GET/POST /api/watchlist` items 계약.

- [ ] **Step 1: 실패 테스트** — `tests/test_widget.py`에 추가:

```python
def test_watchlist_api_items_contract(tmp_path, monkeypatch):
    from backend.config import settings
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "default_account", "master@gmail.com")
    c = TestClient(create_app(_settings(tmp_path, default_account="master@gmail.com")))
    r = c.post("/api/watchlist", json={"items": [{"code": "005930", "market": "KR", "shares": 10, "avg": 230000}]})
    assert r.status_code == 200
    got = c.get("/api/watchlist").json()["items"]
    assert got[0]["code"] == "005930" and got[0]["shares"] == 10
    assert c.post("/api/watchlist", json={"codes": ["005930"]}).status_code == 400  # 구 계약 거부
```
(`_settings` 헬퍼에 `default_account` kwarg 전달 반영. `tests/test_auth.py`는 이미 통과해야 — 라우트가 세션 email로.)

- [ ] **Step 2: 실패 확인.**

- [ ] **Step 3: 구현** — `backend/api/app.py`:

라우트 email 헬퍼(모듈 상단 함수):
```python
def _req_email(request, settings):
    """세션 이메일(있으면) 없으면 default_account. request.session 직접 접근 금지(게이트 방어와 동일)."""
    from backend.flow.userstore import default_account
    sess = request.scope.get("session") or {}
    return (sess.get("email") or default_account())
```

`/api/watchlist` GET/POST 교체:
```python
    @app.get("/api/watchlist")
    def watchlist_get(request: Request):
        from backend.flow import userstore
        from backend.market.universe import get_cached, name_map
        from backend.news.names import resolve_name
        nm = name_map(get_cached())
        email = _req_email(request, settings)
        items = [{**i, "name": (resolve_name(i["code"], nm) if i["market"] == "KR"
                                else _us_name(i["code"]))}
                 for i in userstore.get_watchlist(email)]
        return JSONResponse({"items": items})

    @app.post("/api/watchlist")
    async def watchlist_set(request: Request):
        from backend.flow import userstore
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "본문(JSON)을 읽을 수 없어요"}, status_code=400)
        items = body.get("items") if isinstance(body, dict) else None
        if items is None:
            return JSONResponse({"error": "items 배열이 필요해요"}, status_code=400)
        try:
            saved = userstore.set_watchlist(_req_email(request, settings), items)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"items": saved})
```
(`_us_name(code)`는 Task 9의 usquote에서 import; Phase 3 이전엔 `lambda c: c`로 임시 두고 Task 11에서 교체 — 또는 이 태스크에서 `backend.flow.semi.US_NAMES.get(code, code)`로.)

`index`/`prices_api`/watch 라우트를 KR 코드·email로:
```python
    # index(): build_dashboard(userstore.get_kr_codes(_req_email(request,settings)), ...)  → index에 request 인자 추가
    # prices_api(): fetch_live_prices(userstore.get_kr_codes(_req_email(request,settings)))
    # watch_get/watch_set: _watch.get_lines/set_lines → userstore.get_lines(email,code)/set_lines(email,code,lines)
    # widget_api(): Task 8에서 email 기반으로 교체
```
`backend/cli.py`: `main`의 report는 `get_kr_codes(default_account())`; `backend/mcp/tools.py` `_analyze`도 `get_kr_codes(default_account())`.
`backend/report/live_page.py:1217` `watch_mod.get_lines(code)` → `userstore.get_lines(email, code)`; `render_live_page`·`live()`에 email 인자 전파(`live()`는 `_req_email`).

- [ ] **Step 4: 통과** — `.venv/bin/python -m pytest tests/ -q`(전체 — 소비자 광범위 변경이라 전 스위트).
- [ ] **Step 5: 커밋** — `git commit -m "feat(watchlist): 소비자 계정화 — KR코드만 KR파이프라인, /api/watchlist items 계약, 라우트 email 해석"`

---

# Phase 2 — 위젯 토큰 계정화

### Task 7: AuthGate Bearer → email + scope 전달

**Files:** Modify `backend/api/auth.py`, `backend/api/widget.py`, `backend/api/app.py`; Test `tests/test_auth.py`·`tests/test_widget.py`

**Interfaces:**
- Consumes: `userstore.email_for_token`.
- Produces: 게이트가 유효 토큰이면 `scope["state"]={"widget_email":email}` 세팅 후 통과; `widget_data(email, codes)` 시그니처.

- [ ] **Step 1: 실패 테스트** — `tests/test_auth.py`:

```python
def test_widget_token_maps_to_account(tmp_path, monkeypatch):
    """계정 토큰으로 그 계정 데이터, 미매칭 401(default 폴백 금지)."""
    from backend.config import settings
    from backend.flow import userstore
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "default_account", "master@gmail.com")
    tok = userstore.ensure_token("master@gmail.com")
    c = _client(_auth_settings(tmp_path, default_account="master@gmail.com"))
    r = c.get("/api/widget", headers={"Authorization": "Bearer " + tok})
    assert r.status_code in (200, 503)          # 게이트 통과(핸들러 도달)
    assert c.get("/api/widget", headers={"Authorization": "Bearer wrong" + "x" * 20}).status_code == 401
```

- [ ] **Step 2: 실패 확인.**

- [ ] **Step 3: 구현** — `backend/api/auth.py` `_widget_blocked` 교체(email 매핑 + scope 세팅):

```python
    def _widget_blocked(self, scope):
        import secrets as _secrets_mod
        from starlette.responses import JSONResponse
        from backend.flow.userstore import email_for_token
        auth = b""
        for k, v in scope.get("headers") or ():
            if k == b"authorization":
                auth = v
                break
        raw = auth[7:] if auth[:7].lower() == b"bearer " else b""
        try:
            token = raw.decode("utf-8") if raw else ""
        except Exception:
            token = ""
        email = email_for_token(token) if token else None
        if email:
            st = scope.get("state")
            if not isinstance(st, dict):
                st = {}
                scope["state"] = st
            st["widget_email"] = email
            return None
        return JSONResponse({"error": "unauthorized"}, status_code=401)
```
(AuthGate가 더 이상 정적 widget_token 불필요 — `__init__`의 widget_token 인자·install의 전달 유지하되 미사용 or 제거. 미설정 503은 핸들러로 이관.)

`backend/api/widget.py`: `widget_data(codes)` → `widget_data(email, codes)`; `widget_api`가 `scope["state"]["widget_email"]`로 email 취득 후 `userstore.get_watchlist(email)`.

- [ ] **Step 4: 통과** — `.venv/bin/python -m pytest tests/test_auth.py tests/test_widget.py -q`.
- [ ] **Step 5: 커밋** — `git commit -m "feat(widget): AuthGate Bearer→계정 매핑 + scope 전달(미매칭 401·default 폴백 금지)"`

---

### Task 8: `/widget-setup` 계정별 토큰 + 회전 버튼

**Files:** Modify `backend/report/widget_setup.py`, `backend/api/app.py`; Test `tests/test_widget_setup.py`

**Interfaces:** Consumes `userstore.ensure_token/rotate_token`, `_req_email`. Produces 계정별 토큰 표시 + [재발급].

- [ ] **Step 1: 실패 테스트** — `tests/test_widget_setup.py`:

```python
def test_setup_shows_account_token(tmp_path, monkeypatch):
    from backend.config import Settings
    from backend.api.app import create_app
    from fastapi.testclient import TestClient
    s = Settings(cache_dir=str(tmp_path), flow_mode="demo", default_account="master@gmail.com",
                 kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    c = TestClient(create_app(s))
    r = c.get("/widget-setup")
    assert r.status_code == 200 and "Scriptable" in r.text          # 세션없음→default 계정 토큰
```

- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현** — `widget_setup_page`가 `settings.widget_token` 대신 `userstore.ensure_token(_req_email(request,settings))`로 토큰 확보해 페이지 렌더. `render_widget_setup(token, base_url)`은 그대로. 재발급 라우트 `POST /widget-setup/rotate` → `userstore.rotate_token(email)` 후 새 토큰 반환(페이지에 [재발급] 버튼).
- [ ] **Step 4: 통과** — `.venv/bin/python -m pytest tests/test_widget_setup.py -q`.
- [ ] **Step 5: 커밋** — `git commit -m "feat(widget): /widget-setup 계정별 토큰 발급·재발급"`

---

# Phase 3 — 보유/수익

### Task 9: 수익 계산 순수 함수 `pnl.py`

**Files:** Create `backend/flow/pnl.py`; Test `tests/test_pnl.py`

**Interfaces:** Produces `compute(price, avg, shares) -> {pnl, pnl_pct}` (avg/shares None이면 None).

- [ ] **Step 1: 실패 테스트**:

```python
# tests/test_pnl.py
def test_pnl_basic():
    from backend.flow.pnl import compute
    assert compute(253500, 230000, 10) == {"pnl": 235000, "pnl_pct": round((253500/230000-1)*100, 2)}
def test_pnl_none_when_no_holding():
    from backend.flow.pnl import compute
    assert compute(100, None, 5) == {"pnl": None, "pnl_pct": None}
    assert compute(100, 90, None) == {"pnl": None, "pnl_pct": None}
    assert compute(None, 90, 5) == {"pnl": None, "pnl_pct": None}
def test_pnl_us_float():
    from backend.flow.pnl import compute
    r = compute(189.70, 170.55, 5)
    assert abs(r["pnl"] - (189.70-170.55)*5) < 1e-6
```

- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현** — `backend/flow/pnl.py`:

```python
from __future__ import annotations
"""보유 수익 계산 순수 함수. 통화 무관(KR=원, US=$ — 호출부가 통화 일관 보장)."""


def compute(price, avg, shares):
    if price is None or avg is None or shares is None or avg <= 0:
        return {"pnl": None, "pnl_pct": None}
    pnl = (price - avg) * shares
    if isinstance(avg, int) and isinstance(price, (int, float)) and float(price).is_integer():
        pnl = int(round(pnl))
    return {"pnl": pnl, "pnl_pct": round((price / avg - 1) * 100, 2)}
```

- [ ] **Step 4: 통과** — `.venv/bin/python -m pytest tests/test_pnl.py -q`.
- [ ] **Step 5: 커밋** — `git commit -m "feat(pnl): 보유 수익 계산 순수 함수"`

---

### Task 10: `/api/widget` 보유/수익 + 계정 items

**Files:** Modify `backend/api/widget.py`; Test `tests/test_widget.py`

**Interfaces:** Consumes `pnl.compute`, `userstore.get_watchlist(email)`. Produces 응답 items에 `market,currency,shares,avg,pnl,pnl_pct`.

- [ ] **Step 1: 실패 테스트** — KR 보유 종목의 pnl이 응답에 포함되고 화이트리스트(감시선 등 없음) 확인. (모킹: KIS 없음→universe 폴백로 price 주입.) 코드 생략 없이 test_widget.py에 추가:

```python
def test_widget_includes_pnl_and_whitelist(tmp_path, monkeypatch):
    import asyncio
    from backend.config import settings
    from backend.flow import userstore
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    monkeypatch.setattr(settings, "default_account", "m@x.com")
    _seed_universe(str(tmp_path), [{"code": "005930", "name": "삼성전자", "close": 253500.0, "change": -9.3}])
    userstore.set_watchlist("m@x.com", [{"code": "005930", "market": "KR", "shares": 10, "avg": 230000}])
    d = asyncio.run(widget_data("m@x.com", userstore.get_watchlist("m@x.com")))
    it = d["items"][0]
    assert it["pnl"] == 235000 and it["market"] == "KR" and it["currency"] == "KRW"
    assert set(it.keys()) <= {"code","name","market","currency","price","change","shares","avg","pnl","pnl_pct","us_open"}
```

- [ ] **Step 2-5:** 구현(`widget_data(email, items)`가 KR/US 분기 + pnl.compute) → 통과 → 커밋 `feat(widget): 계정 보유 수익 응답(화이트리스트 갱신)`.

---

### Task 11: Scriptable 위젯 2줄 재디자인(실선·폰트·색·동적 용량)

**Files:** Modify `backend/report/widget_setup.py` (_SCRIPT); Test `tests/test_widget_setup.py`

**Interfaces:** 위젯 스크립트가 종목당 1~2줄, 구분 실선, 상승빨강/하락파랑(등락%·수익), 세로예산 동적 컷.

- [ ] **Step 1: 실패 테스트** — 스크립트 마커: `"pnl"`, `"addSpacer"`, divider(실선) helper, `"budget"` 또는 누적로직 함수명, KR/US 통화 포맷. node --check 통과.
- [ ] **Step 2-5:** 구현(2줄 렌더 + `fmtMoney(currency)` + `pnlColor` + 세로예산 누적 후 "+N종목") → node --check → 커밋 `feat(widget): 위젯 2줄 보유/수익 재디자인 — 실선·폰트·상승빨강/하락파랑·세로예산`.

---

# Phase 4 — 미국 주식

### Task 12: `usquote.py` 거래소 순회 시세

**Files:** Create `backend/flow/usquote.py`; Modify `backend/flow/semi.py`(공유); Test `tests/test_usquote.py`

**Interfaces:** Produces `price_us(client, sym)->{price,change,currency,exch}` (async, 캐시), `us_name(sym)->str`.

- [ ] **Step 1: 실패 테스트** — 모킹된 client로 NAS 성공 / NAS None→NYS 성공 / 전부 None. `us_name("NVDA")=="엔비디아"`, `us_name("ZZZZ")=="ZZZZ"`:

```python
# tests/test_usquote.py
import asyncio
class _C:
    def __init__(self, ok): self.ok = ok; self.calls = []
    async def _get(self, path, tr, params):
        self.calls.append(params["EXCD"])
        if params["EXCD"] == self.ok:
            return {"rt_cd": "0", "output": {"last": "189.70", "rate": " -0.85", "sign": "5", "tvol": "1"}}
        return {"rt_cd": "0", "output": {"last": "0"}}
def test_price_us_walks_exchanges():
    from backend.flow.usquote import price_us
    c = _C("NYS")
    q = asyncio.run(price_us(c, "XYZ"))
    assert q and q["exch"] == "NYS" and c.calls[:2] == ["NAS", "NYS"]
def test_price_us_all_fail():
    from backend.flow.usquote import price_us
    assert asyncio.run(price_us(_C("NONE"), "ZZZZ")) is None
def test_us_name():
    from backend.flow.usquote import us_name
    assert us_name("NVDA") == "엔비디아" and us_name("ZZZZ") == "ZZZZ"
```

- [ ] **Step 2-5:** 구현(semi.parse_us_quote 재사용, EXCD NAS→NYS→AMS 순회, `last>0 and tvol`, 12h 거래소 캐시, US_NAMES) → 통과 → 커밋 `feat(usquote): 미국 시세 거래소 순회(NAS→NYS→AMS)·이름·캐시`.

---

### Task 13: 위젯/검색 KR·US 통합

**Files:** Modify `backend/api/widget.py`(US 분기), `backend/report/dashboard.py`(US 티커 검색 감지); Test `tests/test_widget.py`·`tests/test_dashboard.py`

- [ ] US 종목이 위젯 items에 `$`·us_open으로 나오고, 검색창이 대문자 티커에 "＋담기(US)" 제안. 담기 시 서버 price_us 존재확인 400. TDD 각 단계 → 커밋 `feat(us): 위젯 US 종목 + 검색 티커 감지·존재확인`.

---

# Phase 5 — 편집 UX (가장 나중)

### Task 14: 관리 리스트 + 버튼 폴백 (progressive base)

**Files:** Modify `backend/report/dashboard.py`; Test `tests/test_dashboard.py`

- [ ] 관리 리스트(행: 핸들·이름·현재가·▲▼·×·[보유]) — **버튼(▲▼/×)이 항상 동작**(드래그 없이도). node --check(메인+편집 블록). 카드 편집버튼 제거. 각 단계 TDD → 커밋 `feat(dashboard): 관심종목 관리 리스트(버튼 폴백 항상 동작)`.

### Task 15: 드래그/스와이프 (별도 script + try/catch)

**Files:** Modify `backend/report/dashboard.py`; Test `tests/test_dashboard.py`

- [ ] **별도 `<script>` 블록**에 Pointer Events 드래그(핸들)·스와이프(각도 임계) 얹기, `try/catch`로 실패 시 "편집 비활성"(버튼 폴백 유지). node --check 두 블록. → 커밋 `feat(dashboard): 드래그 순서변경·스와이프 삭제(별도 script·try/catch degrade)`.

---

# Phase 6 — 가이드·검증

### Task 16: 가이드 갱신 + 전체 검증 + 실기기

**Files:** Modify `docs/widget-guide.md`; 전체 스위트.

- [ ] 가이드: 계정별 토큰(각 사용자 /widget-setup 설치), **수익=자산정보 경고 강화**, 큰 위젯 권장, US 티커, 드래그/스와이프·보유입력. 
- [ ] `.venv/bin/python -m pytest tests/ -q` 전체 통과.
- [ ] 실기기(마스터): 계정 토큰 설치, 드래그/스와이프/보유입력, 위젯 2줄/색/실선/오버플로, US 종목.
- [ ] 커밋 `docs(widget): v2 가이드 — 계정토큰·수익경고·US·드래그편집`.

---

## Self-Review (계획 작성 후 점검)

- **스펙 커버리지**: 계정저장소(T1-5)·소비자KR분리(T6)·토큰계정화(T7-8)·수익(T9-11)·US(T12-13)·편집(T14-15)·가이드(T16). 교차계정 격리 테스트는 T2/T3/T4/T7에 분산+게이트. 전 항목 매핑.
- **자리표시자**: T10-15는 스펙에 코드/계약이 확정돼 있어 TDD 골격+핵심 코드로 기술(구현자는 스펙 해당 절 참조). T3a·T4 캐시무효화·T6 `_us_name` 임시처리 등 함정 명시.
- **타입 일관성**: `get_watchlist->list[dict]`, `get_kr_codes->list[str]`, `get_lines(email,code)`, `email_for_token->Optional[str]`, `widget_data(email,items)`, `pnl.compute->{pnl,pnl_pct}`, `price_us->{price,change,currency,exch}` 교차 참조 일치.
- **빌드 게이트**: Phase 1(T2-4) 격리 테스트가 GREEN이어야 Phase 3(P&L) 진입 — subagent-driven 실행 시 T5 후 격리 스위트 확인.
