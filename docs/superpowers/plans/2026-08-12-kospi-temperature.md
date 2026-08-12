# '코스피 온도' Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** '지수' 섹션에 `코스피 온도` 그룹(이격도·EMA 이격·하락폭)을 얹어, 코스피 지수값이 최근 흐름에서 어디쯤인지를 판정 단어와 함께 보여준다.

**Architecture:** 서버는 `kis.index_daily("0001")` **한 콜**로 100거래일을 받아 순수 계산 3개를 하고, 판정 단어까지 실어 `/api/kospi-temp`로 내린다. 계산은 종가 리스트 하나의 순수 함수라 KIS를 모킹하지 않고 테스트한다. 프런트는 기존 칩 문법(`gchip`)을 한 줄 확장해 판정 단어를 값 옆에 무채색으로 붙이고, 세 번째 줄(`.gb`)은 다른 칩과 똑같이 신선도를 유지한다.

**Tech Stack:** Python 3.9 호환 · asyncio · pytest · 인라인 JS(빌드 없음) · node 하니스 · CDP 실렌더

**설계 문서:** `docs/superpowers/specs/2026-08-12-kospi-temperature-design.md` — 판단 근거·실측·기각 항목이 전부 거기 있다. 충돌하면 설계 문서가 이긴다.

## Global Constraints

- **Python 3.9 호환.** `match`, `X | Y` 타입 표기, dict `|` 병합 금지. `Optional[...]`을 쓴다.
- **모르는 값은 `None`.** 0.0으로 뭉개지 않는다. None인 항목은 응답 `items`에서 **빠진다**(null로 보내지 않는다).
- **프런트는 추측하지 않는다.** 판정 단어(`verdict`)는 서버가 실어 보낸다. 임계값을 프런트에 두면 판정 기준이 두 군데로 갈라진다.
- **`.gb`(칩 세 번째 줄)은 신선도 전용이다.** 판정 단어를 그 줄에 넣지 마라 — 한 섹션 안에서 같은 줄이 두 가지를 뜻하게 된다.
- **새 디자인 언어 금지.** 기존 `.mchip/.ml/.mv/.mr`(theme.py 단일 출처)를 그대로 쓴다.
- **⚠️ `dashboard.py`의 JS/CSS 주석에 `__대문자__` 치환 토큰을 글자 그대로 적지 마라.** `render_dashboard()`의 `.replace()` 18곳은 주석을 가리지 않아, 렌더 시 주석 한복판에 코드가 치환돼 인라인 JS가 통째로 깨진다(2026-08-12 실제로 밟았다). 뜻만 풀어 적는다.
- **테스트는 전부 오프라인.** `tests/conftest.py`의 네트워크 가드가 외부 호출을 차단하고 **기록해 테스트를 실패시킨다** — 스텁을 빼먹으면 조용히 넘어가지 않는다.
- **`worldidx`에 넣지 않는다.** 그 모듈은 해외 전용이다.
- 파이썬은 `.venv/bin/python`. **8000 실서버를 건드리지 않는다.**
- 커밋 메시지는 저장소 관례(한국어 conventional commit)를 따른다.

---

### Task 1: 순수 계산 + 판정 단어

**Files:**
- Create: `backend/flow/kospitemp.py`
- Modify: `backend/education/glossary.py`
- Test: `tests/test_kospitemp.py` (신규)

**Interfaces:**
- Consumes: 없음(첫 태스크)
- Produces:
  - `kospitemp.compute(closes: list) -> dict` — `{"ma_gap": float|None, "ema_gap": float|None, "down_avg": float|None}`
  - `glossary.read_temp(key: str, v) -> Optional[str]` — 판정 단어. Task 2가 응답 조립에 쓴다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_kospitemp.py` 신규:

```python
"""'코스피 온도' 순수 계산 — 종가 리스트만 넣는다(KIS 모킹 없음).

days[-1].v == now.price가 실측으로 참이라(2026-08-12) 현재가를 따로 받지 않는다.
그래서 이 모듈의 계산부는 네트워크와 완전히 분리된다.
"""
import pytest

from backend.education import glossary
from backend.flow import kospitemp as kt


def test_ma_gap_is_distance_from_the_simple_mean():
    """현재가가 평균보다 얼마나 위/아래인가 — 백분율."""
    # 평균 100, 현재 110 → +10%
    closes = [90.0, 100.0, 110.0]
    assert kt.compute(closes)["ma_gap"] == 10.0


def test_ema_gap_weights_recent_days_more():
    """EMA는 최근에 가중이 실린다 — 단조 상승이면 현재가가 EMA보다 위다."""
    closes = [float(x) for x in range(100, 140)]
    g = kt.compute(closes)["ema_gap"]
    assert g is not None and g > 0


def test_down_avg_is_the_mean_drop_not_a_stdev():
    """하락일 평균 하락률(양수 %p). 표준편차가 아니다 — 그건 초보에게 안 읽힌다."""
    # -10%, -10%, -10% 세 번(사이에 보합) → 평균 하락률 10.0
    closes = [100.0, 90.0, 81.0, 72.9]
    assert kt.compute(closes)["down_avg"] == 10.0


def test_too_few_down_days_is_unknown_not_zero():
    """하락일이 3일 미만이면 표본이 너무 작다 — None이지 0이 아니다."""
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]      # 하락일 0
    assert kt.compute(closes)["down_avg"] is None
    assert kt.compute([100.0, 99.0, 100.0, 99.5])["down_avg"] is None   # 2개


def test_short_or_dirty_input_is_all_none():
    """종가 2개 미만이면 전부 None. NaN·0·음수는 버린다(값이 아니다)."""
    assert kt.compute([])["ma_gap"] is None
    assert kt.compute([100.0])["ma_gap"] is None
    assert kt.compute([float("nan"), 0.0, -3.0, 100.0])["ma_gap"] is None


def test_verdict_bands_use_strict_less_than_everywhere():
    """경계는 전부 `<`(미만)로 통일 — 섞으면 경계값에서 읽는 사람도 테스트도 헷갈린다."""
    assert glossary.read_temp("ma_gap", -10.01) == "크게 눌림"
    assert glossary.read_temp("ma_gap", -10.0) == "눌림"      # 경계는 아래 구간
    assert glossary.read_temp("ma_gap", -3.0) == "비슷"
    assert glossary.read_temp("ma_gap", 2.99) == "비슷"
    assert glossary.read_temp("ma_gap", 3.0) == "위"
    assert glossary.read_temp("ma_gap", 10.0) == "크게 위"
    assert glossary.read_temp("ema_gap", 0.0) == "비슷"
    assert glossary.read_temp("down_avg", 0.99) == "잔잔"
    assert glossary.read_temp("down_avg", 3.5) == "거침"


def test_verdict_of_unknown_value_or_key_is_none():
    """모르는 값에 판정을 지어내지 않는다."""
    assert glossary.read_temp("ma_gap", None) is None
    assert glossary.read_temp("없는키", 1.0) is None


def test_todays_measured_values_are_reproducible():
    """2026-08-12 코스피 100거래일 실측 회귀 — 계산을 바꾸면 여기가 먼저 빨개진다.

    설계 문서 '실측' 절의 숫자와 같아야 한다: 이격도 -6.34 / EMA 이격 +2.63 /
    하락일 평균 하락률 4.99. 리스트는 그날 응답에서 뽑은 종가다."""
    closes = _KOSPI_20260812
    d = kt.compute(closes)
    assert d["ma_gap"] == pytest.approx(-6.34, abs=0.01)
    assert d["ema_gap"] == pytest.approx(2.63, abs=0.01)
    assert d["down_avg"] == pytest.approx(4.99, abs=0.01)
    assert glossary.read_temp("ma_gap", d["ma_gap"]) == "눌림"
    assert glossary.read_temp("ema_gap", d["ema_gap"]) == "위"
    assert glossary.read_temp("down_avg", d["down_avg"]) == "거침"
```

> `_KOSPI_20260812`는 Step 3에서 실제 응답으로 채운다. 그 전까지는 이 테스트가
> `NameError`로 실패하는 게 정상이다.

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_kospitemp.py -v -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: backend.flow.kospitemp`

- [ ] **Step 3: 실측 픽스처를 뽑아 테스트에 심는다**

```bash
.venv/bin/python -c "
import asyncio
from backend.flow import kst, candles
async def m():
    c = candles._get_client()
    d = await c.index_daily('0001', kst.now().strftime('%Y%m%d'))
    v = [x['v'] for x in d['days']]
    print('_KOSPI_20260812 = [')
    for i in range(0, len(v), 8):
        print('    ' + ', '.join('%.2f' % x for x in v[i:i+8]) + ',')
    print(']')
asyncio.run(m())
" 2>&1 | grep -v Warning
```

출력을 `tests/test_kospitemp.py` 맨 위(import 아래)에 붙여넣는다.

**주의**: 이 한 번만 실호출한다. 장중이면 마지막 봉이 움직이므로 `test_todays_measured_values_are_reproducible`의 기대값(-6.34 / 2.63 / 4.99)이 안 맞을 수 있다. 그러면 **계산을 고치지 말고**, 방금 뽑은 리스트로 다시 계산해 나온 값으로 기대값 세 개를 갱신하고 그 사실을 커밋 메시지에 적는다(판정 단어는 그대로 눌림/위/거침이어야 한다 — 아니면 멈추고 escalation).

- [ ] **Step 4: 계산 모듈 구현**

`backend/flow/kospitemp.py` 신규:

```python
from __future__ import annotations

"""'코스피 온도' — 코스피 지수값이 최근 흐름에서 어디쯤인지.

'지수' 섹션은 값을 보여준다(코스피 6,598). 그런데 초보에게 6,598은 그 자체로 의미가
없다 — 최근 흐름에서 어디쯤인지를 모르기 때문이다. 여기서 그 답을 만든다.

**새 원천이 없다.** VKOSPI에 이미 쓰는 TR(FHPUP02120000)을 0001(코스피)로 부르면
100거래일이 한 번에 온다.

**계산은 종가 리스트 하나의 순수 함수다.** `days[-1].v == now.price`가 실측으로 참이라
(2026-08-12) 현재가를 따로 받지 않는다 — 입력이 리스트뿐이면 테스트가 KIS를 안 거친다.

Python 3.9 호환.
"""

from typing import Optional

_EMA_SPAN = 12
_DOWN_WINDOW = 20
# 하락일이 이보다 적으면 표본이 너무 작다 — 평균을 내도 뜻이 없다.
_MIN_DOWN_DAYS = 3


def _clean(closes) -> list:
    """숫자이고 양수인 값만. NaN·0·음수는 지수 종가가 아니다."""
    out = []
    for v in closes or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == f and f > 0:            # NaN 판정(math 임포트 없이)
            out.append(f)
    return out


def _ema(vals: list, span: int) -> float:
    k = 2.0 / (span + 1)
    e = vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
    return e


def _down_avg(vals: list) -> Optional[float]:
    """최근 20 수익률 중 **음수만**의 평균 하락률(양수 %p).

    표준편차가 아니라 평균인 이유: "하락한 날엔 평균 5.0% 빠졌어요"는 읽히지만
    표준편차는 안 읽힌다. 이 지표를 넣는 목적이 그것이다."""
    rets = [(vals[i] - vals[i - 1]) / vals[i - 1] * 100
            for i in range(1, len(vals))]
    down = [r for r in rets[-_DOWN_WINDOW:] if r < 0]
    if len(down) < _MIN_DOWN_DAYS:
        return None
    return round(sum(-r for r in down) / len(down), 2)


def compute(closes) -> dict:
    """종가 리스트(오래된 순, 마지막이 현재가) → 세 지표. 모르면 None.

    ma_gap의 평균에는 오늘 진행 중 봉이 포함된다(가중치 1/100이라 무시할 수 있다).
    ema_gap도 마지막 값이 오늘을 15%쯤 포함한다(k=2/13) — 자기참조지만 관례대로 둔다."""
    vals = _clean(closes)
    if len(vals) < 2:
        return {"ma_gap": None, "ema_gap": None, "down_avg": None}
    cur = vals[-1]
    ma = sum(vals) / len(vals)
    ema = _ema(vals, _EMA_SPAN)
    return {"ma_gap": round((cur - ma) / ma * 100, 2) if ma else None,
            "ema_gap": round((cur - ema) / ema * 100, 2) if ema else None,
            "down_avg": _down_avg(vals)}
```

- [ ] **Step 5: 판정 단어 구현**

`backend/education/glossary.py`의 `concept()` 정의 **바로 위**에 추가:

```python
# ── '코스피 온도' 판정 단어 ───────────────────────────────────────────────
# (상한, 판정) — 값이 상한 **미만**이면 그 판정. 마지막 항목(상한 None)이 나머지 전부.
# 비교를 전부 `<`로 통일한다: 구간마다 `≤`와 `<`를 섞으면 경계값에서 헷갈린다.
#
# **이 숫자들은 잠정이다.** 근거가 약하다 — 장기 표본이 없다. 그리고 관측에 쓴 최근
# 100거래일이 통째로 격동 구간이라(하락일 평균 하락률 중앙값 3.69%p, 평상시는 0.6~1.0)
# 거기 맞춰 잡으면 4.99%p가 '보통'으로 읽힌다. 그래서 **절대 수준**으로 잡았다.
# 관찰하며 조정할 것 — 설계 문서 2026-08-12-kospi-temperature-design.md E절.
_TEMP_BANDS = {
    "ma_gap": ((-10.0, "크게 눌림"), (-3.0, "눌림"), (3.0, "비슷"),
               (10.0, "위"), (None, "크게 위")),
    "ema_gap": ((-5.0, "크게 아래"), (-1.5, "아래"), (1.5, "비슷"),
                (5.0, "위"), (None, "크게 위")),
    "down_avg": ((1.0, "잔잔"), (2.0, "보통"), (3.5, "출렁임"), (None, "거침")),
}
# ma_gap과 ema_gap이 같은 어휘를 쓰는 것은 의도다 — 둘 다 "평균 대비 위치"라 같은 축이고,
# 어휘가 다르면 나란히 놓았을 때 비교가 안 된다. 구간 폭만 다르다(장기 넓게, 단기 좁게).


def read_temp(key, v) -> Optional[str]:
    """'코스피 온도' 판정 단어. 값이 없거나 모르는 키면 None(지어내지 않는다)."""
    bands = _TEMP_BANDS.get(key)
    if bands is None or v is None:
        return None
    for hi, word in bands:
        if hi is None or v < hi:
            return word
    return None
```

- [ ] **Step 6: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_kospitemp.py -v -p no:warnings`
Expected: 8 passed

- [ ] **Step 7: 커밋**

```bash
git add backend/flow/kospitemp.py backend/education/glossary.py tests/test_kospitemp.py
git commit -m "$(cat <<'EOF'
feat(kospitemp): 코스피 온도 3지표 순수 계산 + 판정 단어

계산이 종가 리스트 하나의 순수 함수다 — days[-1].v == now.price가 실측으로
참이라 현재가를 따로 받지 않는다. 덕분에 테스트가 KIS를 안 거친다.

하방 변동성은 표준편차가 아니라 하락일 평균 하락률이다. "하락한 날엔 평균
5.0% 빠졌어요"는 읽히지만 표준편차는 안 읽힌다 — 이 지표를 넣는 목적이 그것.

판정 구간은 절대 수준으로 잡았다. 관측에 쓴 최근 100거래일이 통째로 격동
구간이라(하락일 평균 중앙값 3.69%p, 평상시 0.6~1.0) 거기 맞추면 오늘의
4.99%p가 '보통'으로 읽힌다. 근거가 약하다는 점을 상수 옆에 적어뒀다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: KIS 조회 + 캐시 + 라우트

**Files:**
- Modify: `backend/flow/kospitemp.py`, `backend/api/app.py`
- Test: `tests/test_kospitemp.py`, `tests/test_kospitemp_api.py` (신규)

**Interfaces:**
- Consumes: `kospitemp.compute()`, `glossary.read_temp()`(Task 1)
- Produces:
  - `kospitemp.get_temp() -> dict` — `{"asof": ISO(KST), "items": [{"key","label","value","unit","verdict"}, …]}`
  - `GET /api/kospi-temp` — Task 3 프런트가 소비

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_kospitemp.py` 맨 끝에 추가:

```python
# ── 조회·조립 ─────────────────────────────────────────────────────────────

import asyncio
import datetime as dt

from backend.flow import candles
from backend.flow.kst import KST

FIXED_NOW = dt.datetime(2026, 8, 12, 12, 50, tzinfo=KST)


class _FakeKis:
    """index_daily만 답하는 가짜 클라이언트 — 요청 인자도 기록한다."""

    def __init__(self, days=None, boom=False):
        self.days = days
        self.boom = boom
        self.calls = []

    async def index_daily(self, iscd, date):
        self.calls.append((iscd, date))
        if self.boom:
            raise RuntimeError("KIS 실패 스텁")
        return {"now": None, "days": self.days}


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    """캐시 리셋 + 클라이언트 기본 스텁(터짐). 스텁 주입을 빼먹으면 라이브가 아니라 예외."""
    kt._cache["ts"], kt._cache["data"] = 0.0, None

    def _boom():
        raise RuntimeError("KIS 스텁 미지정")

    monkeypatch.setattr(candles, "_get_client", _boom)
    monkeypatch.setattr(kt.kst, "now", lambda: FIXED_NOW)


def _days(closes):
    return [{"d": "2026080%d" % (i % 9 + 1), "v": v} for i, v in enumerate(closes)]


def test_get_temp_carries_the_verdict_from_the_server(monkeypatch):
    """판정은 서버가 실어 내린다 — 프런트가 임계값을 들면 기준이 두 군데로 갈라진다."""
    c = _FakeKis(days=_days(_KOSPI_20260812))
    monkeypatch.setattr(candles, "_get_client", lambda: c)
    d = asyncio.run(kt.get_temp())
    keys = {i["key"]: i for i in d["items"]}
    assert set(keys) == {"ma_gap", "ema_gap", "down_avg"}
    assert keys["ma_gap"]["verdict"] == "눌림"
    assert keys["ma_gap"]["unit"] == "%"
    assert keys["down_avg"]["unit"] == "%p"
    assert keys["ma_gap"]["label"] == "100일 평균"
    assert d["asof"].startswith("2026-08-12T12:50")
    assert c.calls == [("0001", "20260812")]


def test_unknown_items_are_dropped_not_nulled(monkeypatch):
    """None인 항목은 items에서 빠진다 — null로 보내면 프런트가 대시를 그린다."""
    c = _FakeKis(days=_days([100.0, 101.0, 102.0]))   # 하락일 0 → down_avg None
    monkeypatch.setattr(candles, "_get_client", lambda: c)
    d = asyncio.run(kt.get_temp())
    assert {i["key"] for i in d["items"]} == {"ma_gap", "ema_gap"}


def test_dead_source_yields_empty_items_not_an_error(monkeypatch):
    """KIS가 죽으면 items=[]다 — 그건 에러가 아니라 '그룹을 감추라'는 신호다."""
    monkeypatch.setattr(candles, "_get_client", lambda: _FakeKis(boom=True))
    assert asyncio.run(kt.get_temp())["items"] == []


def test_second_call_within_ttl_does_not_hit_kis(monkeypatch):
    """60초 캐시 — 마지막 봉이 장중에 움직이므로 해외지수와 같은 주기."""
    c = _FakeKis(days=_days(_KOSPI_20260812))
    monkeypatch.setattr(candles, "_get_client", lambda: c)
    asyncio.run(kt.get_temp())
    asyncio.run(kt.get_temp())
    assert len(c.calls) == 1
    assert kt._TTL == 60.0
```

`tests/test_kospitemp_api.py` 신규:

```python
"""GET /api/kospi-temp — 라우트 계약."""
import asyncio
import datetime as dt

from fastapi.testclient import TestClient

from backend.api.app import app
from backend.flow import candles
from backend.flow import kospitemp as kt
from backend.flow.kst import KST

ITEM_KEYS = {"key", "label", "value", "unit", "verdict"}


class _Fake:
    def __init__(self, closes):
        self.closes = closes

    async def index_daily(self, iscd, date):
        return {"now": None, "days": [{"d": "20260812", "v": v}
                                      for v in self.closes]}


def test_route_returns_the_full_item_shape(monkeypatch):
    kt._cache["ts"], kt._cache["data"] = 0.0, None
    monkeypatch.setattr(kt.kst, "now",
                        lambda: dt.datetime(2026, 8, 12, 12, 50, tzinfo=KST))
    monkeypatch.setattr(candles, "_get_client",
                        lambda: _Fake([100.0, 95.0, 99.0, 94.0, 98.0, 93.0, 97.0]))
    r = TestClient(app).get("/api/kospi-temp")
    assert r.status_code == 200
    d = r.json()
    assert d["items"], "항목이 하나도 없다"
    for it in d["items"]:
        assert set(it) == ITEM_KEYS, it
        assert it["verdict"], "판정 단어 누락 — 프런트가 지어내면 안 되는 값이다"


def test_route_is_200_with_empty_items_when_the_source_dies(monkeypatch):
    """503으로 끊지 않는다 — 그룹 하나가 빠질 뿐 섹션은 떠야 한다."""
    kt._cache["ts"], kt._cache["data"] = 0.0, None

    def _boom():
        raise RuntimeError("KIS 없음")

    monkeypatch.setattr(candles, "_get_client", _boom)
    r = TestClient(app).get("/api/kospi-temp")
    assert r.status_code == 200 and r.json()["items"] == []
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_kospitemp.py tests/test_kospitemp_api.py -p no:warnings`
Expected: FAIL — `AttributeError: module 'backend.flow.kospitemp' has no attribute '_cache'` / 404

- [ ] **Step 3: 조회·조립 구현**

`backend/flow/kospitemp.py`의 import 줄을 교체하고 파일 **맨 끝**에 추가:

```python
import logging
import time
from typing import Optional

from backend.education import glossary
from backend.flow import candles, kst
```

```python
# ── KIS 조회 + 조립 ───────────────────────────────────────────────────────

log = logging.getLogger(__name__)

_ISCD = "0001"                      # 코스피
_TTL = 60.0                         # 마지막 봉이 장중에 움직인다 — 해외지수와 같은 주기
_cache = {"ts": 0.0, "data": None}

# (key, label, unit) — 화면 순서. 장기 → 단기 → 변동폭.
_ITEMS = (("ma_gap", "100일 평균", "%"),
          ("ema_gap", "12일 평균", "%"),
          ("down_avg", "하락폭(20일)", "%p"))


async def get_temp() -> dict:
    """{'asof': ISO(KST), 'items': [{key,label,value,unit,verdict}, …]}.

    실패하면 items=[]다 — 에러가 아니라 '그룹을 감추라'는 신호다(빈 껍데기 금지).
    키 없음도 여기서 막지 않는다: 클라이언트 생성 실패가 아래 except로 흡수된다
    (/api/worldidx와 같은 관례 — 게이트를 앞에 두면 테스트가 설정에 끌려간다)."""
    now = kst.now().replace(microsecond=0).isoformat()
    if _cache["data"] is not None and time.time() - _cache["ts"] < _TTL:
        return {"asof": now, "items": _cache["data"]}
    try:
        client = candles._get_client()      # 모듈 경유 — 테스트가 이 지점만 갈아끼운다
        d = await client.index_daily(_ISCD, kst.now().strftime("%Y%m%d"))
    except Exception:
        log.warning("코스피 온도 조회 실패 — 그룹 생략", exc_info=True)
        return {"asof": now, "items": []}
    vals = [x.get("v") for x in ((d or {}).get("days") or [])]
    got = compute(vals)
    items = []
    for key, label, unit in _ITEMS:
        v = got.get(key)
        if v is None:
            continue                        # 모르는 항목은 빼고 보낸다(null 금지)
        items.append({"key": key, "label": label, "value": v, "unit": unit,
                      "verdict": glossary.read_temp(key, v)})
    if items:
        _cache["ts"], _cache["data"] = time.time(), items
    return {"asof": now, "items": items}
```

- [ ] **Step 4: 라우트 추가**

`backend/api/app.py`의 `@app.get("/api/vkospi")` 블록 **바로 위**에 추가:

```python
    @app.get("/api/kospi-temp")
    async def kospi_temp_api():
        """코스피 온도 — 지수값이 최근 흐름에서 어디쯤인지(이격도·EMA 이격·하락폭).

        판정 단어까지 서버가 실어 내린다. 프런트가 임계값을 들고 있으면 판정 기준이
        두 군데로 갈라진다(unit·rate_unit·basis_kind를 데이터에 실은 것과 같은 이유).

        실패하면 items=[]로 200이다 — 그룹 하나가 빠질 뿐 섹션은 떠야 한다."""
        from backend.flow import kospitemp
        return JSONResponse(await kospitemp.get_temp())
```

- [ ] **Step 5: 통과 확인 + 회귀**

Run: `.venv/bin/python -m pytest tests/ -q -p no:warnings`
Expected: 전부 PASS(신규 테스트만큼 늘어난다). 줄었으면 멈추고 escalation.

- [ ] **Step 6: 커밋**

```bash
git add backend/flow/kospitemp.py backend/api/app.py \
        tests/test_kospitemp.py tests/test_kospitemp_api.py
git commit -m "$(cat <<'EOF'
feat(api): GET /api/kospi-temp — 코스피 온도 조회 + 60초 캐시

VKOSPI에 이미 쓰는 TR(FHPUP02120000)을 0001로 부른다 — 새 원천이 없다.
worldidx에 넣지 않는다(그 모듈은 해외 전용). /api/market에도 안 넣는다
(30초 폴링이라 100거래일 조회를 얹으면 무거워진다).

모르는 항목은 items에서 뺀다 — null로 보내면 프런트가 대시를 그린다.
실패는 503이 아니라 items=[]다: 에러가 아니라 그룹을 감추라는 신호다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 프런트 그룹 + 판정 배지 + 390px 실렌더

**Files:**
- Modify: `backend/report/dashboard.py`
- Test: `tests/test_worldidx_page.py`

**Interfaces:**
- Consumes: `GET /api/kospi-temp`(Task 2), 기존 `gchip`·`gfresh`·`renderIdx`·`krIndexLive`
- Produces: 없음(마지막 태스크)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_worldidx_page.py`의 `_HARNESS`에서 `global.fetch`에 한 분기를 더한다(`/api/futures` 줄 **아래**):

```javascript
  if (mkt && s.indexOf('/api/kospi-temp') >= 0) return {ok: true, json: async () => mkt.temp};
```

`_mkt()`에 `temp` 키를 더한다:

```python
def _mkt():
    """/api/market + /api/futures + /api/kospi-temp 실응답 모양(장중)."""
    return {"market": {"kospi": {"price": 6525.01, "rate": 3.0},
                       "kosdaq": {"price": 856.4, "rate": -0.17}},
            "futures": {"k200": {"label": "K200선물", "price": 880.25,
                                 "rate": 2.8, "closed": False},
                        "nq": {"label": "나스닥 선물", "price": 29641.0,
                               "rate": -0.34}},
            "temp": {"asof": "2026-08-12T12:50:00+09:00", "items": [
                {"key": "ma_gap", "label": "100일 평균", "value": -6.34,
                 "unit": "%", "verdict": "눌림"},
                {"key": "ema_gap", "label": "12일 평균", "value": 2.63,
                 "unit": "%", "verdict": "위"},
                {"key": "down_avg", "label": "하락폭(20일)", "value": 4.99,
                 "unit": "%p", "verdict": "거침"}]}}
```

맨 끝에 테스트 추가:

```python
@needs_node
def test_kospi_temperature_group_sits_right_after_the_domestic_index(tmp_path):
    """읽는 순서 — '코스피 6,525' 다음에 '그게 최근 대비 어디쯤인가'."""
    body = _run(tmp_path, _payload(), mkt=_mkt())["body"]
    assert "코스피 온도" in body
    assert body.index("국내 지수") < body.index("코스피 온도") < body.index("지수 선물")
    assert body.count('class="mchip"') == 15        # 2 + 3 + 2 + 3 + 2 + 3


@needs_node
def test_verdict_sits_next_to_the_value_not_on_the_freshness_line(tmp_path):
    """판정은 값 옆에, 세 번째 줄은 다른 칩과 똑같이 신선도.

    .gb를 판정에 내주면 한 섹션 안에서 같은 줄이 두 가지를 뜻하게 된다 — 이 저장소가
    반복해서 잡아온 '라벨이 조용히 틀리는' 결함과 같은 부류다."""
    body = _run(tmp_path, _payload(), mkt=_mkt())["body"]
    for w in ("눌림", "위", "거침"):
        assert w in body, w + " 판정 누락"
    # 판정 단어가 신선도 줄에 들어가지 않았는지 — .gb 안엔 실시간/마감/기준일만 온다.
    import re
    for gb in re.findall(r'<div class="gb">([^<]*)</div>', body):
        assert "눌림" not in gb and "거침" not in gb, gb
    assert body.count('class="gb"') == 15           # 칩마다 하나씩, 높이 균일


@needs_node
def test_verdict_is_colourless(tmp_path):
    """판정에 up/down 색을 쓰지 않는다 — 이격도가 음수라고 '나쁨'이 아니다."""
    body = _run(tmp_path, _payload(), mkt=_mkt())["body"]
    i = body.index("눌림")
    seg = body[max(0, i - 120):i]
    assert 'class="mr up"' not in seg and 'class="mr down"' not in seg


@needs_node
def test_temperature_group_vanishes_when_its_source_dies(tmp_path):
    """items=[]면 그 그룹만 빠지고 나머지는 그대로 뜬다."""
    m = _mkt()
    m["temp"] = {"asof": "2026-08-12T12:50:00+09:00", "items": []}
    body = _run(tmp_path, _payload(), mkt=m)["body"]
    assert "코스피 온도" not in body
    assert "국내 지수" in body and "지수 선물" in body
    assert body.count('class="mchip"') == 12
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx_page.py -k "temperature or verdict" -v -p no:warnings`
Expected: FAIL — `코스피 온도`가 없다

- [ ] **Step 3: `gchip`이 판정을 알아보게 한다**

`gchip()`의 `const ru=...` 줄 **위**에 추가하고, 반환문의 `.mr` 부분을 교체:

```js
  // 판정 단어(코스피 온도)는 등락률 자리에 **무채색으로** 앉는다. up/down 색을 쓰지
  // 않는 이유: 이격도가 음수라고 '나쁨'이 아니다(눌린 게 기회일 수도 있다) — 색으로
  // 말할 방향이 없다. 신선도 줄(.gb)은 다른 칩과 똑같이 유지한다.
  if(it.verdict) return '<div class="mchip"><div class="ml">'+esc(it.label)+'</div>'
    +'<div class="mv">'+gnum(it.value)+gunitHtml(it.unit)
    +'<span class="mr flat">'+esc(it.verdict)+'</span></div>'
    +'<div class="gb">'+esc(gfresh(it))+'</div></div>';
```

- [ ] **Step 4: 온도 로더 + 그룹 조립**

`let MKT={}, FUT={}, WIDX=null;` 줄을 교체:

```js
let MKT={}, FUT={}, WIDX=null, TEMP=null;      // 각 로더의 마지막 응답
```

`gdomestic()`의 `if(idx.length) gs.push(...)` **바로 다음**에 추가:

```js
  // '코스피 온도' — 국내 지수 바로 다음. "코스피 6,525" 다음에 "그게 최근 대비 어디쯤".
  // 신선도는 국내 지수 칩과 **같은 판정**이어야 한다(같은 원천의 같은 봉이다).
  const tp=((TEMP&&TEMP.items)||[]).map(function(x){
    return {key:x.key, label:x.label, value:x.value, unit:x.unit,
            verdict:x.verdict, fresh:live};});
  if(tp.length) gs.push({label:'코스피 온도', items:tp});
```

`loadMarket()`의 `renderIdx();` **바로 위**에 로더를 붙인다(같은 30초 주기 — 국내 지수와
같은 봉이라 주기가 갈리면 두 그룹이 어긋난 순간을 보여준다):

```js
    try{
      const rt=await fetch('/api/kospi-temp');
      if(rt&&rt.ok) TEMP=await rt.json();
    }catch(e){}
```

- [ ] **Step 5: 통과 확인 + 회귀**

Run: `.venv/bin/python -m pytest tests/ -q -p no:warnings`
Expected: 전부 PASS

- [ ] **Step 6: 390px 실렌더 — 이 계획의 게이트**

**`harness verify --only dashboard`로는 이 섹션을 볼 수 없다**(데모가 KIS를 차단하고
`cdp.shot` 대기가 3초 고정이라 섹션이 숨은 채로 찍힌다 —
`2026-08-12-index-section-design.md`에 근거가 있다). 캔 데이터를 주입해 찍는다:

`dashboard.py`가 만든 HTML을 그대로 띄우고 `/api/market`·`/api/futures`·`/api/kospi-temp`·
`/api/worldidx`만 고정 응답으로 돌려주는 임시 서버를 스크래치패드에 세운 뒤,
390px 라이트/다크를 찍고 **Read 도구로 열어 눈으로 본다.** 페이로드는
`tests/test_worldidx_page.py`의 `_payload()`·`_mkt()`를 그대로 쓴다.

**눈으로 확인할 것:**
1. `코스피 온도`가 `국내 지수`와 `지수 선물` 사이에 있다
2. **칩 높이가 여전히 균일하다** — 판정 단어가 값 옆에 있어 줄 수가 안 늘었는지
3. 판정 단어가 무채색이다(상승 빨강·하락 파랑이 아니다)
4. `-6.34%  눌림`이 390px에서 한 줄에 들어간다(안 넘치면 줄바꿈되는지)
5. 라이트·다크 양쪽에서 판정 단어가 읽힌다

- [ ] **Step 7: 라이브 스모크**

```bash
.venv/bin/python -c "
import asyncio, json
from backend.flow import kospitemp
print(json.dumps(asyncio.run(kospitemp.get_temp()), ensure_ascii=False, indent=1))
" 2>&1 | grep -v Warning
```

세 항목이 다 오고 `verdict`가 전부 채워졌는지, 값이 상식 범위인지(이격도·EMA 이격은
±30% 안, 하락폭은 0~10%p 안) 확인한다.

- [ ] **Step 8: 커밋**

```bash
git add backend/report/dashboard.py tests/test_worldidx_page.py
git commit -m "$(cat <<'EOF'
feat(dashboard): '코스피 온도' 그룹 — 값 옆에 판정, 신선도 줄은 그대로

.gb(칩 세 번째 줄)은 "이 값이 얼마나 신선한가"로 계약이 잡힌 자리다. 판정
단어를 거기 넣으면 한 섹션 안에서 같은 줄이 두 가지를 뜻하게 된다 — 그래서
판정은 등락률 자리에 두고 세 번째 줄은 다른 칩과 똑같이 유지했다. 칩 높이
균일도 그대로다.

판정에 up/down 색을 쓰지 않는다: 이격도가 음수라고 '나쁨'이 아니다(눌린 게
기회일 수도 있다) — 색으로 말할 방향이 없다.

온도 로더는 loadMarket과 같은 주기로 돈다. 국내 지수와 같은 봉이라 주기가
갈리면 두 그룹이 어긋난 순간을 보여주게 된다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review 기록

- **Spec coverage**: A(칩 모양)=Task 3 Step 3 · B(위치)=Task 3 Step 4 · C(모듈 경계)=Task 1·2 ·
  D(계산)=Task 1 Step 4 · E(판정 구간)=Task 1 Step 5 · F(신선도)=Task 3 Step 4 ·
  G(응답 계약)=Task 2 Step 3 · 실패 처리=Task 2 Step 3 · 테스트=각 태스크.
- **경계 조건**: 설계 E절의 `≤`를 `<`로 통일하고 설계 문서도 함께 고쳤다(커밋 참조).
- **`_KOSPI_20260812`**: Task 1 Step 1이 참조하고 Step 3이 채운다. 그 사이 `NameError`가
  나는 것이 정상이며 Step 2의 Expected가 그것을 덮는다.
- **장중 재실행 시**: Step 3의 실측 기대값이 어긋날 수 있다. 계산이 아니라 기대값을
  갱신하고 커밋 메시지에 남긴다(판정 단어가 바뀌면 멈추고 escalation).
