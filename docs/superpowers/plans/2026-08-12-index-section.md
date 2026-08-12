# '지수' 섹션 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 접힌 '글로벌' 섹션을 '지수'로 바꾸고 상단 스트립의 코스피·코스닥·선물 칩을 그 안에 미러링하며, 칩마다 정확한 신선도 줄을 붙이고 미국 금리를 장중(CNBC/Tradeweb) 원천으로 승격한다.

**Architecture:** 서버(`worldidx.py`)는 원천별 격리 골격을 그대로 두고 `basis_kind` 한 필드를 추가한다. 미국 금리는 `CNBC 우선 → 재무부 폴백` 2단이 되고, 원자재/금리의 "지금 살아 있나" 판정은 ET 벽시계 세션 헬퍼 하나를 공유한다. 프런트(`dashboard.py`)는 `/api/market`·`/api/futures`의 마지막 응답을 어댑터로 감싸 worldidx 그룹 앞에 붙이는 단일 렌더 함수 `renderIdx()`로 합친다. 국내 그룹에 대한 새 API 호출은 없다.

**Tech Stack:** Python 3.9 호환 · asyncio · requests · pytest · 인라인 JS(빌드 없음) · node 하니스 테스트

**설계 문서:** `docs/superpowers/specs/2026-08-12-index-section-design.md` — 판단 근거·기각된 후보·실측값이 전부 거기 있다. 충돌하면 설계 문서가 이긴다.

## Global Constraints

- **Python 3.9 호환.** `match`, `X | Y` 타입 표기, `dict |` 병합 금지. `Optional[...]`을 쓴다.
- **모르는 값은 `None`.** `0.0`으로 뭉개지 않는다. `kis._f`(전부 0.0으로 뭉갬)를 이 모듈에서 쓰지 않는다 — `_num`/`_pct`만 쓴다.
- **프런트는 아무것도 추측하지 않는다.** 단위(`unit`)·등락단위(`rate_unit`)·신선도(`basis_kind`)는 전부 서버가 실어 보낸다. `basis` 문자열 모양이나 그룹 이름으로 분기 금지.
- **새 디자인 언어 금지.** 칩은 기존 `.mchip/.ml/.mv/.mr`(theme.py 단일 출처)를 그대로 쓴다.
- **테스트는 전부 오프라인.** `tests/test_worldidx.py`의 autouse `_offline` 픽스처가 모든 원천에 '반드시 터지는' 스텁을 먼저 깐다. CNBC 실호출을 CI에 넣지 않는다.
- **`/api/*` 기존 응답 필드는 이름·타입·내용 불변.** 추가는 `basis_kind` 하나뿐이다.
- **8000 실서버를 건드리지 않는다.** 라이브 확인은 `python -m harness verify` 경로로.
- 커밋 메시지는 저장소 관례(한국어 conventional commit)를 따른다.

---

### Task 1: 세션 헬퍼 + `basis_kind` + 나스닥 라벨

**Files:**
- Modify: `backend/flow/worldidx.py`
- Test: `tests/test_worldidx.py`

**Interfaces:**
- Consumes: 없음(첫 태스크)
- Produces:
  - `worldidx.cme_open(now_et: Optional[dt.datetime] = None) -> bool` — Task 2가 CNBC 호출 게이트로 재사용
  - `worldidx._item(key, label, value, unit, rate, sign, basis, src, rate_unit="%", basis_kind="date") -> dict` — 반환 dict에 `"basis_kind"` 키 추가
  - `/api/worldidx` Item에 `basis_kind: "live" | "date"` 필드 — Task 3 프런트가 소비

- [ ] **Step 1: 세션 헬퍼 실패 테스트 작성**

`tests/test_worldidx.py` 맨 끝에 추가:

```python
# ── CME/현금국채 세션 판정 ────────────────────────────────────────────────

def _et(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=wi.adr._ET)


def test_cme_open_covers_the_globex_window():
    """일 18:00 ET 개장 → 금 17:00 ET 마감, 매일 17:00~18:00 ET 휴식."""
    assert wi.cme_open(_et(2026, 8, 12, 21, 0)) is True    # 수 저녁 = 한국 목 오전
    assert wi.cme_open(_et(2026, 8, 12, 17, 30)) is False  # 일일 휴식
    assert wi.cme_open(_et(2026, 8, 12, 18, 0)) is True    # 휴식 끝, 재개장
    assert wi.cme_open(_et(2026, 8, 14, 17, 0)) is False   # 금 17:00 마감 직후
    assert wi.cme_open(_et(2026, 8, 14, 16, 59)) is True   # 마감 직전
    assert wi.cme_open(_et(2026, 8, 16, 18, 0)) is True    # 일 18:00 재개장
    assert wi.cme_open(_et(2026, 8, 16, 17, 59)) is False  # 그 직전


def test_cme_open_says_closed_on_the_saturday_trap():
    """토요일 10:00 KST — 설계 문서가 경고한 구멍.

    그 시각 마지막 호가는 토 06:00 KST(= 금 17:00 ET 정산)라 '값의 시각이 오늘(KST)'
    판정을 쓰면 정산된 값에 live가 붙고, 일요일엔 같은 숫자가 마감으로 뒤집힌다.
    판정 기준은 달력 날짜가 아니라 세션이다."""
    sat_10_kst = dt.datetime(2026, 8, 15, 10, 0, tzinfo=KST)
    assert wi.cme_open(sat_10_kst.astimezone(wi.adr._ET)) is False
    sun_10_kst = dt.datetime(2026, 8, 16, 10, 0, tzinfo=KST)
    assert wi.cme_open(sun_10_kst.astimezone(wi.adr._ET)) is False
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx.py -k cme_open -v`
Expected: FAIL — `AttributeError: module 'backend.flow.worldidx' has no attribute 'cme_open'`

- [ ] **Step 3: 세션 헬퍼 구현**

`backend/flow/worldidx.py`의 `_last_us_session()` 정의 **바로 아래**에 추가:

```python
def cme_open(now_et: Optional[dt.datetime] = None) -> bool:
    """CME Globex(원자재)와 현금 국채 시장이 열려 있는가 — **ET 벽시계**.

    일 18:00 ET 개장 → 금 17:00 ET 마감, 매일 17:00~18:00 ET 휴식.
    두 시장의 창이 사실상 같아 **헬퍼 하나를 공유한다** — 같은 판정을 두 군데서
    흉내내면 한쪽만 고쳐지는 날이 온다(원자재 신선도 + CNBC 호출 게이트).

    KST 벽시계로 판정하면 미국 서머타임 전환마다 한 시간씩 어긋나므로 adr._ET를 쓴다
    (_last_us_session과 같은 시계 — DST 처리를 두 군데서 흉내내지 않는다).

    **절대 쓰면 안 되는 대안**: "값의 시각이 오늘(KST)이면 열림". 토요일 10:00 KST면
    마지막 호가가 토 06:00 KST(= 금 17:00 ET 정산)라 '오늘'이 되어 정산된 값에 live가
    붙고, 일요일 10:00엔 같은 숫자가 '오늘이 아니'라 마감으로 뒤집힌다.

    한계: 미국 휴장일 달력은 없다 — 휴장일엔 정산된 값에 '실시간'이 붙을 수 있다.
    adr.us_market_open·futures.session_of가 이미 같은 한계를 안고 같은 이유로
    받아들인다(휴장일 하루를 위해 달력을 들이는 값어치가 없다)."""
    n = now_et or kst.now().astimezone(adr._ET)
    wd, hm = n.weekday(), n.strftime("%H:%M")      # 월=0 … 토=5, 일=6
    if wd == 5:                                    # 토요일은 종일 휴장
        return False
    if wd == 6:                                    # 일요일은 18:00 ET에 열린다
        return hm >= "18:00"
    if wd == 4 and hm >= "17:00":                  # 금요일 17:00 마감 → 주말
        return False
    return not ("17:00" <= hm < "18:00")           # 평일 일일 휴식
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx.py -k cme_open -v`
Expected: PASS (2 passed)

- [ ] **Step 5: `basis_kind` 실패 테스트 작성**

`tests/test_worldidx.py` 맨 끝에 추가:

```python
# ── basis_kind — 신선도를 데이터에 실어 내린다 ────────────────────────────

def test_basis_kind_rides_on_every_item(monkeypatch):
    """재무부는 항상 date(일 1회 확정치), 원자재는 세션, 해외지수는 미국장 개장 여부.

    프런트가 basis 문자열 모양이나 그룹 이름으로 신선도를 추측하기 시작하면 이 모듈이
    unit·rate_unit을 실어 막으려던 추측 사고가 렌더러에서 재발한다."""
    _fix_now(monkeypatch, FIXTURE_NOW)             # 2026-08-11 21:40 KST = 08:40 ET
    _treasury(monkeypatch)
    _fdr(monkeypatch)
    _kis(monkeypatch)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    monkeypatch.setattr(wi.adr, "us_market_open", lambda now_et=None: False)
    g = _groups(asyncio.run(wi.get_worldidx()))
    assert {i["basis_kind"] for i in g["미국 금리"]["items"]} == {"date"}
    assert {i["basis_kind"] for i in g["원자재"]["items"]} == {"live"}
    assert {i["basis_kind"] for i in g["해외지수"]["items"]} == {"date"}


def test_basis_kind_flips_with_the_sessions(monkeypatch):
    """세션이 닫히면 원자재는 date, 미국장이 열리면 해외지수는 live."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    _treasury(monkeypatch)
    _fdr(monkeypatch)
    _kis(monkeypatch)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: False)
    monkeypatch.setattr(wi.adr, "us_market_open", lambda now_et=None: True)
    g = _groups(asyncio.run(wi.get_worldidx()))
    assert {i["basis_kind"] for i in g["원자재"]["items"]} == {"date"}
    assert {i["basis_kind"] for i in g["해외지수"]["items"]} == {"live"}


def test_nasdaq_composite_label_is_unambiguous(monkeypatch):
    """'나스닥'은 섹션 안에서 '나스닥 선물' 칩과 나란히 뜬다 — COMP는 종합지수다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    _treasury(monkeypatch)
    _fdr(monkeypatch)
    _kis(monkeypatch)
    g = _groups(asyncio.run(wi.get_worldidx()))
    assert _items(g["해외지수"])["comp"]["label"] == "나스닥 종합"
```

- [ ] **Step 6: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx.py -k "basis_kind or nasdaq_composite" -v`
Expected: FAIL — `KeyError: 'basis_kind'` 및 `assert '나스닥' == '나스닥 종합'`

- [ ] **Step 7: `_item`에 `basis_kind` 추가**

`backend/flow/worldidx.py`의 `_item()`을 통째로 교체:

```python
def _item(key, label, value, unit, rate, sign, basis, src, rate_unit="%",
          basis_kind="date") -> dict:
    """칩 하나 — 키 구성은 설계 문서의 Item + `rate_unit`·`basis_kind`(프런트 계약).

    `rate_unit`·`basis_kind`를 **데이터에 실는** 이유는 `unit`과 같다: 프런트가 등락
    단위나 신선도를 추측하기 시작하면 이 파일이 막으려는 사고가 렌더러에서 재발한다.

    basis_kind: "date"=그날 확정/마감값 / "live"=지금 움직이는 중.
    "live"여도 basis는 그대로 싣는다 — 폴백 경계에서 필드 모양이 바뀌지 않게."""
    return {"key": key, "label": label, "value": value, "unit": unit,
            "rate": rate, "sign": sign, "basis": basis, "src": src,
            "rate_unit": rate_unit, "basis_kind": basis_kind}
```

- [ ] **Step 8: 세 그룹에 `basis_kind` 싣기 + 나스닥 라벨**

`_INDICES` 정의를 교체:

```python
# (key, label, KIS ISCD) — 늘리기 전에 위 '함정' 문단을 읽을 것.
# comp 라벨이 '나스닥 종합'인 이유: '지수' 섹션에서 '나스닥 선물' 칩과 나란히 뜬다.
# COMP는 실제로 나스닥 종합지수라 더 정확하기도 하다.
_INDICES = (("spx", "S&P500", "SPX"), ("comp", "나스닥 종합", "COMP"),
            ("vix", "VIX", "VIX"))
```

`_treasury_group()`의 `items.append(...)` 호출을 교체(재무부는 일 1회 확정치라 항상 `date`):

```python
        items.append(_item(key, label, value, "%", rate, sign, basis, "treasury",
                           rate_unit="bp", basis_kind="date"))
```

`_commodity_group()`에서 `items = []` **바로 위**에 한 줄 추가하고 `append`를 교체:

```python
    # 마지막 봉은 세션이 열려 있으면 '진행 중'이라 값이 현재가다(2026-08-12 실측:
    # 90초 간격 호출에 값이 계속 바뀐다). 닫혀 있으면 완료된 세션의 종가다.
    kind = "live" if cme_open() else "date"
```

```python
        items.append(_item(key, label, q["value"], unit, q["rate"], q["sign"],
                           _mmdd(q["basis"]), "fdr", basis_kind=kind))
```

`_index_group()`에서 `items = []` **바로 위**에 한 줄 추가하고 `append`를 교체:

```python
    kind = "live" if adr.us_market_open() else "date"
```

```python
        items.append(_item(key, label, q["value"], "idx", q["rate"], q["sign"],
                           _mmdd(basis), "kis", basis_kind=kind))
```

- [ ] **Step 9: 통과 확인 + 회귀 없음**

Run: `.venv/bin/python -m pytest tests/test_worldidx.py tests/test_worldidx_api.py tests/test_worldidx_bp.py -v`
Expected: 전부 PASS. `test_worldidx_page.py`는 아직 손대지 않았으므로 이 명령에 포함하지 않는다(Task 3에서 함께 고친다).

- [ ] **Step 10: 잘못된 기록 정정**

`worldidx.parse_fdr_last`의 docstring 첫 두 문단을 교체:

```python
def parse_fdr_last(df) -> Optional[dict]:
    """FDR 일봉 → {'value','rate','sign','basis'(date)}. 마지막 유효 행 기준.

    **마지막 행은 종가가 아니라 진행 중 세션의 현재가다**(2026-08-12 실측: 90초 간격
    3회 호출에 금 4427.10 → 4428.20 → 4428.10). FDR `_validate_dates`의 end 기본값이
    자정이 아니라 `datetime.today()`(현재 시각)라 오늘 봉이 안 잘린다. 야후 분봉 교차
    확인 지연은 금 10.1분 / WTI 11.8분. 그런데 야후는 그 진행 중 봉에 **하루 전 날짜**를
    찍으므로 basis만 어제가 된다 — 그래서 화면 신선도는 basis가 아니라 basis_kind
    (cme_open)로 정한다. 등락률(직전 완료 세션 종가 대비 현재가)은 의미가 맞다.

    FDR은 거래일인데도 통째로 NaN인 행을 실제로 내보낸다(결측 — futures.pick_latest_pair
    가 같은 함정을 이미 기록해뒀다). 그 행은 값도 기준일도 쓰지 않는다. 유효 행이
    하나뿐이면 rate=None.

    값은 소수 2자리로 정규화한다 — FDR은 float32에서 승격된 값을 준다(2026-08-11 실호출:
    WTI 81.9800033569336, 금 4455.2998046875). 그대로 내리면 그 잡음이 API 응답과
    화면에 그대로 나간다. 등락률은 반올림 전 원값으로 계산한다."""
```

`docs/superpowers/specs/2026-08-11-global-indices-design.md`의 원천 표에서 WTI·금 행의 `기준` 칸 `08-10`을 `08-10*`으로 바꾸고, 표 바로 아래에 한 줄 추가:

```markdown
\* **정정(2026-08-12 실측)**: FDR 일봉의 마지막 행은 종가가 아니라 진행 중 세션의
현재가다(10~12분 지연). 값은 실시간이고 날짜 라벨만 하루 전이다 —
`docs/superpowers/specs/2026-08-12-index-section-design.md` 실측 1 참조.
```

- [ ] **Step 11: 커밋**

```bash
git add backend/flow/worldidx.py tests/test_worldidx.py \
        docs/superpowers/specs/2026-08-11-global-indices-design.md
git commit -m "$(cat <<'EOF'
feat(worldidx): 신선도를 basis_kind로 실어 내린다 + CME 세션 헬퍼

화면 신선도를 basis(날짜)로 정하면 원자재가 틀린다 — FDR 마지막 봉은 진행 중
세션이라 값은 실시간인데 야후가 하루 전 날짜를 찍기 때문이다. 판정을 세션으로
옮기고 결과를 basis_kind로 실어 프런트가 추측하지 않게 한다.

cme_open은 원자재 신선도와 (다음 커밋의) CNBC 호출 게이트가 공유한다 — 창이
사실상 같고, 같은 판정을 두 군데서 흉내내면 한쪽만 고쳐지는 날이 온다.

'나스닥' → '나스닥 종합': '지수' 섹션에서 '나스닥 선물' 칩과 나란히 뜬다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 미국 금리 — CNBC 우선 + 재무부 폴백

**Files:**
- Modify: `backend/flow/worldidx.py`
- Test: `tests/test_worldidx.py`

**Interfaces:**
- Consumes: `worldidx.cme_open()`(Task 1), `worldidx._item(..., basis_kind=)`(Task 1)
- Produces:
  - `worldidx.parse_cnbc_yield(js: dict) -> Optional[dict]` — `{"value": float, "prev": Optional[float], "basis": Optional[dt.date]}`
  - `worldidx._fetch_cnbc(symbol: str) -> dict` — 테스트가 monkeypatch하는 지점
  - `_treasury_group()`이 `src="cnbc"` + `basis_kind="live"` items를 내거나 재무부로 폴백

- [ ] **Step 1: autouse 픽스처에 CNBC 스텁 추가**

`tests/test_worldidx.py`의 `_offline` 픽스처에 두 줄 추가(스텁 주입을 빼먹으면 라이브 호출이 아니라 RuntimeError가 나야 한다):

```python
    def _boom_cnbc(symbol):
        raise RuntimeError("CNBC 스텁 미지정")

    monkeypatch.setattr(wi, "_fetch_cnbc", _boom_cnbc)
```

그리고 헬퍼를 `_kis()` 아래에 추가:

```python
def _cnbc(monkeypatch, values=None, boom=()):
    """CNBC 단건 응답 스텁. values={'US10Y': ('4.69%', '4.684%')} 형태."""
    calls = []
    vals = values if values is not None else {
        "US2Y": ("4.22%", "4.218%"), "US10Y": ("4.69%", "4.684%"),
        "US30Y": ("5.24%", "5.237%")}

    def fetch(symbol):
        calls.append(symbol)
        if symbol in boom:
            raise RuntimeError("CNBC 실패 스텁")
        last, prev = vals[symbol]
        return {"FormattedQuoteResult": {"FormattedQuote": [{
            "symbol": symbol, "last": last, "previous_day_closing": prev,
            "last_time": "2026-08-11T21:03:06.000-0400",
            "exchange": "Tradeweb", "realTime": "true"}]}}

    monkeypatch.setattr(wi, "_fetch_cnbc", fetch)
    return calls
```

- [ ] **Step 2: 파서 실패 테스트 작성**

`tests/test_worldidx.py` 맨 끝에 추가:

```python
# ── CNBC 장중 미국금리 ────────────────────────────────────────────────────

def _cnbc_js(**over):
    q = {"symbol": "US10Y", "last": "4.69%", "previous_day_closing": "4.684%",
         "last_time": "2026-08-11T21:03:06.000-0400"}
    q.update(over)
    return {"FormattedQuoteResult": {"FormattedQuote": [q]}}


def test_parse_cnbc_reads_the_percent_string():
    """last는 '4.69%' 문자열이다 — %를 떼고 읽는다. last_time에서 기준일도 나온다."""
    q = wi.parse_cnbc_yield(_cnbc_js())
    assert q["value"] == 4.69
    assert q["prev"] == 4.684
    assert q["basis"] == dt.date(2026, 8, 11)


def test_parse_cnbc_rejects_the_silent_empty_response():
    """심볼을 여러 개 붙이면 에러가 아니라 last=null인 빈 응답이 온다(2026-08-12 실측).

    사설 API는 조용히 깨진다 — 값이 없으면 '모른다'이지 0이 아니다."""
    assert wi.parse_cnbc_yield(_cnbc_js(last=None)) is None
    assert wi.parse_cnbc_yield({"FormattedQuoteResult": {"FormattedQuote": []}}) is None
    assert wi.parse_cnbc_yield({}) is None


def test_parse_cnbc_range_guard_drops_impossible_yields():
    """미국 국채 수익률이 0 이하나 15% 이상일 리 없다 — 스키마가 조용히 바뀌어
    엉뚱한 필드가 들어앉는 실패 모드를 막는다(marketdata._NGT_SANE와 같은 관례)."""
    assert wi.parse_cnbc_yield(_cnbc_js(last="0%")) is None
    assert wi.parse_cnbc_yield(_cnbc_js(last="97.5469")) is None   # 채권 가격이 들어옴
    assert wi.parse_cnbc_yield(_cnbc_js(last="4.69")) is not None  # %가 없어도 읽는다


def test_parse_cnbc_missing_prev_means_unknown_not_zero():
    """직전 종가를 모르면 rate=None이다 — 0.0bp(보합)로 꾸미지 않는다."""
    q = wi.parse_cnbc_yield(_cnbc_js(previous_day_closing=None))
    assert q["value"] == 4.69 and q["prev"] is None
    assert wi._bp_sign(q["value"], q["prev"]) == (None, "flat")
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx.py -k parse_cnbc -v`
Expected: FAIL — `AttributeError: module 'backend.flow.worldidx' has no attribute 'parse_cnbc_yield'`

- [ ] **Step 4: 파서 구현**

`backend/flow/worldidx.py`의 `# ── 미 재무부 일별 금리곡선 ──` 섹션 **바로 위**에 추가:

```python
# ── CNBC 장중 미국금리(Tradeweb) ──────────────────────────────────────────
# 2026-08-12 한국 장중 실측: US2Y 4.222 / US10Y 4.69 / US30Y 5.24, 지연 약 30초,
# 재무부 확정치 대비 0~1bp. 값이 그만큼 가까워서 폴백해도 화면 숫자가 튀지 않는다.
# **심볼은 반드시 한 건씩** 부른다 — 여러 개 붙이면 에러가 아니라 last=null인 빈 응답이
# 조용히 온다(실측). 재배포 제약: Tradeweb 라이선스 피드라 야후보다 리스크가 크다 —
# 공개 전환 시 1순위 제거 대상이다(설계 문서 실측 2).

_CNBC_URL = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/"
             "symbol?symbols={sym}&requestMethod=itv&noform=1&partnerId=2"
             "&fund=1&exthrs=1&output=json&events=1")
# (key, label, CNBC 심볼) — key·label을 _TENORS와 **똑같이** 맞춘다. 폴백 경계에서
# 칩 자리가 바뀌면 원천이 바뀐 게 사용자에겐 칩이 움직인 것으로 보인다.
_CNBC_TENORS = (("ust2y", "2년", "US2Y"), ("ust10y", "10년", "US10Y"),
                ("ust30y", "30년", "US30Y"))
_YIELD_MIN, _YIELD_MAX = 0.0, 15.0


def _pct(v) -> Optional[float]:
    """'4.69%' → 4.69. %가 없어도 읽는다. 못 읽으면 None(0.0으로 뭉개지 않는다)."""
    if v is None:
        return None
    return _num(str(v).replace("%", "").replace(",", "").strip())


def parse_cnbc_yield(js: dict) -> Optional[dict]:
    """CNBC 단건 시세 → {'value','prev','basis'(date|None)}.

    범위 가드(0 < y < 15%)를 통과하지 못하면 None이다. 사설 API가 조용히 깨지는 것을
    전제로 짠다 — 실측에서 겪은 실패 모드가 예외가 아니라 `last: null`이었다."""
    rows = (((js or {}).get("FormattedQuoteResult") or {})
            .get("FormattedQuote") or [])
    if not rows:
        return None
    o = rows[0]
    value = _pct(o.get("last"))
    if value is None or not (_YIELD_MIN < value < _YIELD_MAX):
        return None
    try:                       # '2026-08-11T21:03:06.000-0400'
        basis = dt.date.fromisoformat(str(o.get("last_time") or "")[:10])
    except ValueError:
        basis = None
    return {"value": value, "prev": _pct(o.get("previous_day_closing")),
            "basis": basis}


def _fetch_cnbc(symbol: str) -> dict:
    """동기 HTTP — to_thread로 감싸 호출한다. 테스트는 이 지점을 갈아끼운다."""
    import requests
    r = requests.get(_CNBC_URL.format(sym=symbol), headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


async def _cnbc_items() -> list:
    """CNBC 3만기 — **한 건씩 순차**로 부른다(마스터 지시: 사설 API에 버스트 금지).

    _index_group이 KIS에 쓰는 것과 같은 _GAP 관례. 만기별로 시차를 두지는 않는다 —
    호출은 1/3로 줄지만 한 그룹 안에서 세 만기의 기준 시각이 섞이고, 금리 곡선은
    만기 간 관계를 보는 값이라 시각이 어긋나면 곡선 자체가 거짓이 된다."""
    items = []
    for i, (key, label, sym) in enumerate(_CNBC_TENORS):
        if i:
            await asyncio.sleep(_GAP)
        try:
            q = parse_cnbc_yield(await _blocking(_fetch_cnbc, sym))
        except Exception:
            log.warning("CNBC %s 실패 — 이 만기만 생략", sym, exc_info=True)
            q = None
        if not q:
            continue
        rate, sign = _bp_sign(q["value"], q["prev"])
        items.append(_item(key, label, q["value"], "%", rate, sign,
                           _mmdd(q["basis"]), "cnbc", rate_unit="bp",
                           basis_kind="live"))
    return items
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx.py -k parse_cnbc -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 그룹 폴백 실패 테스트 작성**

`tests/test_worldidx.py` 맨 끝에 추가:

```python
def test_treasury_group_prefers_cnbc_when_the_market_is_open(monkeypatch):
    """장중이면 CNBC — src=cnbc, basis_kind=live, 등락 단위는 bp."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    calls = _cnbc(monkeypatch)
    g = asyncio.run(wi._treasury_group())
    it = {i["key"]: i for i in g["items"]}
    assert calls == ["US2Y", "US10Y", "US30Y"]      # 순차, 세 만기 전부
    assert it["ust10y"]["value"] == 4.69
    assert it["ust10y"]["src"] == "cnbc"
    assert it["ust10y"]["basis_kind"] == "live"
    assert it["ust10y"]["rate_unit"] == "bp"
    assert it["ust10y"]["rate"] == 0.6              # (4.69-4.684)*100


def test_treasury_group_never_calls_cnbc_when_the_market_is_closed(monkeypatch):
    """휴장이면 **호출이 0건**이고 재무부로 간다.

    절약이기 전에 더 정확하다 — 시장이 닫혀 있으면 확정치가 애초에 맞는 값이다.
    이 테스트가 없으면 세션 게이트가 조용히 무력화돼도 아무도 모른다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: False)
    calls = _cnbc(monkeypatch)
    _treasury(monkeypatch)
    g = asyncio.run(wi._treasury_group())
    assert calls == []
    assert {i["src"] for i in g["items"]} == {"treasury"}
    assert {i["basis_kind"] for i in g["items"]} == {"date"}


def test_treasury_group_falls_back_when_every_tenor_fails(monkeypatch):
    """CNBC 3만기가 전부 죽으면 재무부 확정치로 조용히 강등된다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    _cnbc(monkeypatch, boom=("US2Y", "US10Y", "US30Y"))
    _treasury(monkeypatch)
    g = asyncio.run(wi._treasury_group())
    assert {i["src"] for i in g["items"]} == {"treasury"}
    assert {i["basis_kind"] for i in g["items"]} == {"date"}


def test_partial_cnbc_success_never_mixes_live_and_date(monkeypatch):
    """일부만 성공하면 성공분만 live로 낸다 — 한 그룹에 live/date를 섞지 않는다.

    기준이 섞이면 '10년만 더 최신'으로 읽히고, 금리 곡선은 만기 간 관계를 보는
    값이라 그 순간 곡선 자체가 거짓이 된다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    _cnbc(monkeypatch, boom=("US2Y",))
    _treasury(monkeypatch)
    g = asyncio.run(wi._treasury_group())
    keys = {i["key"] for i in g["items"]}
    assert keys == {"ust10y", "ust30y"}             # 2년물은 빠진다
    assert {i["basis_kind"] for i in g["items"]} == {"live"}


def test_cnbc_failure_does_not_get_hammered_while_cached(monkeypatch):
    """거절당하는 중에 1분마다 다시 두드리는 건 최악의 행동이다 — 물러선다.

    CNBC가 죽어도 재무부 폴백이 **성공하므로** 그룹은 None이 아니고 600초 캐시에
    들어간다. 그 사이 CNBC를 다시 부르지 않는 것이 back-off의 실체다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    ccalls = _cnbc(monkeypatch, boom=("US2Y", "US10Y", "US30Y"))
    tcalls = _treasury(monkeypatch)
    assert asyncio.run(wi._treasury_group()) is not None
    assert len(ccalls) == 3 and len(tcalls) == 1
    asyncio.run(wi._treasury_group())               # TTL 안이면 캐시 히트
    assert len(ccalls) == 3, "TTL 안인데 CNBC를 또 불렀다"
    assert wi._TTL["treasury"] == 600.0
    assert wi._COOLDOWN["treasury"] == 600.0


def test_both_sources_dead_backs_off_without_hammering(monkeypatch):
    """CNBC도 재무부도 죽으면 그룹을 생략하고 쿨다운에 들어간다 — 재호출 0건."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    ccalls = _cnbc(monkeypatch, boom=("US2Y", "US10Y", "US30Y"))
    tcalls = _treasury(monkeypatch, pages={})       # 어느 달을 물어도 404
    assert asyncio.run(wi._treasury_group()) is None
    n_c, n_t = len(ccalls), len(tcalls)
    assert asyncio.run(wi._treasury_group()) is None
    assert len(ccalls) == n_c and len(tcalls) == n_t, "쿨다운인데 다시 두드렸다"


def test_treasury_rows_are_cached_separately_from_the_group(monkeypatch):
    """rows를 그룹과 같이 캐시하면 CNBC가 죽어 있는 동안 재무부를 10분마다 새로
    두드리게 된다 — 하루 한 번 갱신되는 값에 대고 할 짓이 아니다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    _cnbc(monkeypatch, boom=("US2Y", "US10Y", "US30Y"))
    tcalls = _treasury(monkeypatch)
    assert asyncio.run(wi._treasury_group()) is not None
    wi._cache["treasury"]["ts"] = 0.0               # 그룹 TTL만 만료(rows는 1시간)
    assert asyncio.run(wi._treasury_group()) is not None
    assert len(tcalls) == 1, "rows 캐시를 안 타고 재무부를 다시 불렀다"
    assert wi._TTL["treasury_rows"] == 3600.0
```

- [ ] **Step 7: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx.py -k "treasury_group or partial_cnbc or hammered or both_sources or rows_are_cached" -v`
Expected: FAIL — CNBC를 아예 안 부르므로 `src`가 전부 `treasury`이고, `wi._COOLDOWN`이 없다

- [ ] **Step 8: TTL·쿨다운·그룹 재구성**

`_TTL`·`_cache`·`_FAIL_COOLDOWN` 블록을 통째로 교체:

```python
_ORDER = ("treasury", "commodity", "index")   # 화면 그룹 — treasury_rows는 내부 슬롯이다
_TTL = {"treasury": 600.0,      # CNBC 사이클 — 10분에 한 번(마스터 지시: 사설 API 배려)
        "treasury_rows": 3600.0,  # 재무부 원본(폴백 바닥) — 하루 한 번 갱신되는 값
        "commodity": 600.0,     # FDR(비공식 경유)은 아껴 쓴다
        "index": 60.0}          # KIS 지수는 지연 실시간
# fail_ts: 실패한 원천을 매 폴링마다 다시 두드리지 않기 위한 쿨다운 시각.
# 없으면 재무부가 죽었을 때 폴링마다 두 달치 타임아웃을 물고 락을 잡은 채 서 있어,
# 멀쩡히 캐시된 나머지 그룹까지 같이 늦어진다.
_cache = {k: {"ts": 0.0, "data": None, "fail_ts": 0.0} for k in _TTL}
_FAIL_COOLDOWN = 60.0
# CNBC는 기본보다 길게 물러선다. 우리를 거절하는 중이라면 1분마다 다시 두드리는 게
# 최악의 행동이다 — 그동안 화면은 재무부 확정치로 조용히 강등된다.
_COOLDOWN = {"treasury": 600.0}
```

`_cooling()`을 교체:

```python
def _cooling(name: str) -> bool:
    return (time.time() - _cache[name]["fail_ts"]
            < _COOLDOWN.get(name, _FAIL_COOLDOWN))
```

`_treasury_group()`을 통째로 교체(기존 본문은 `_treasury_fallback`으로 옮겨간다):

```python
async def _treasury_group() -> Optional[dict]:
    """CNBC 우선 + 재무부 폴백.

    값이 0~1bp 차이라 원천이 바뀌어도 화면 숫자가 튀지 않는다 — 사용자에겐 신선도
    줄이 '실시간(지연)' ↔ '08-11 확정'으로 바뀌는 것으로만 보인다. 이 성질이 폴백
    설계를 정당화한다(값이 크게 달랐다면 원천을 섞을 수 없다)."""
    hit = _cached("treasury")
    if hit is not None or _cooling("treasury"):
        return hit
    # 미 채권장이 닫혀 있으면 CNBC를 **아예 안 부른다**. 절약이기 전에 더 정확하다 —
    # 시장이 닫혀 있으면 재무부 확정치가 애초에 맞는 값이다.
    items = await _cnbc_items() if cme_open() else []
    if items:
        return _store("treasury", {"label": "미국 금리", "items": items})
    return _store("treasury", await _treasury_fallback())


async def _treasury_fallback() -> Optional[dict]:
    """재무부 확정치 — 폴백의 바닥. rows는 **별도 슬롯에 1시간** 캐시한다.

    같이 캐시하면 CNBC가 죽어 있는 동안 재무부를 10분마다 새로 두드리게 된다."""
    rows = _cached("treasury_rows")
    if rows is None:
        if _cooling("treasury_rows"):
            return None
        rows = _store("treasury_rows", (await _treasury_rows()) or None)
    if not rows:
        return None
    last, prev = rows[-1], (rows[-2] if len(rows) >= 2 else {})
    basis = _mmdd(last["date"])
    items = []
    for key, label, field in _TENORS:
        value = last.get(field)
        if value is None:
            continue
        rate, sign = _bp_sign(value, prev.get(field))
        items.append(_item(key, label, value, "%", rate, sign, basis, "treasury",
                           rate_unit="bp", basis_kind="date"))
    return {"label": "미국 금리", "items": items} if items else None
```

- [ ] **Step 9: 통과 확인 + 전체 회귀**

Run: `.venv/bin/python -m pytest tests/test_worldidx.py tests/test_worldidx_api.py tests/test_worldidx_bp.py -v`
Expected: 전부 PASS

- [ ] **Step 10: 모듈 docstring의 '버린 후보' 갱신**

`worldidx.py` 모듈 docstring의 `버린 후보(재조사 방지):` 문단을 교체:

```
버린 후보(재조사 방지): FRED는 최신 관측이 나흘~일주일 지연, ETF 프록시(GLD·USO)는
단위가 달라 "금 402"처럼 틀린 숫자로 읽히고, KIS 해외선물(CLU26·GCQ26)은 파라미터가
아니라 거래소 신청 권한이 없어 막힌다(EGW00551/EGW00553).
장중 미국금리 후보도 2026-08-12에 전부 실측했다: 야후 ^TNX는 값은 맞지만 미 채권장
시간에만 움직이고 **2년물 지수가 없다**(^FVX는 5년물). CME 마이크로 수익률선물은
유동성이 없어 **만료된 월물을 조용히 계속 준다**(2YY=F가 07-15 만료 계약값). CBOT
국채선물 ZN=F/ZT=F는 살아 움직이지만 가격 호가라 108.45는 금리가 아니다(수익률 변환은
CTD·전환계수가 필요). MarketWatch는 401, stooq는 404. **CNBC만 유일하게 된다.**
```

- [ ] **Step 11: 커밋**

```bash
git add backend/flow/worldidx.py tests/test_worldidx.py
git commit -m "$(cat <<'EOF'
feat(worldidx): 장중 미국금리 — CNBC(Tradeweb) 우선 + 재무부 폴백

한국 장중 실측에서 CNBC가 US2Y/US10Y/US30Y를 약 30초 지연으로 준다. 재무부
확정치 대비 0~1bp라 폴백해도 화면 숫자가 안 튄다 — 사용자에겐 신선도 줄만
바뀐다. 그 성질이 원천을 섞을 수 있게 해준다.

호출은 10분에 한 사이클, 3만기 순차(마스터 지시: 사설 API에 버스트 금지).
실패 쿨다운도 600초 — 거절당하는 중에 1분마다 두드리는 건 최악의 행동이다.
미 채권장 휴장이면 아예 호출하지 않는다(절약이기 전에 더 정확하다).

방어는 사설 API가 조용히 깨지는 것을 전제로: 범위 가드 0~15%, last=null 처리
(실측한 실패 모드), 그룹에 live/date 혼재 금지.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 프런트 — 섹션 이름·아이콘 + 신선도 줄 + 푸터

**Files:**
- Modify: `backend/report/dashboard.py`
- Test: `tests/test_worldidx_page.py`

**Interfaces:**
- Consumes: `/api/worldidx` Item의 `basis_kind`·`src`(Task 1·2)
- Produces:
  - JS `gfresh(it) -> string` — Task 4의 국내 어댑터가 `it.fresh`로 덮어쓸 수 있는 지점
  - `gchip(it)`이 `.gb` 줄에 `gfresh(it)` 출력

- [ ] **Step 1: 실패 테스트 작성 — 기존 기대값 갱신 + 신선도**

`tests/test_worldidx_page.py`의 `_it()`와 `_payload()`를 교체(계약에 `basis_kind`가 늘었다). 이 태스크는 기존 테스트 **두 개를 이름째 교체**한다 — `test_every_chip_prints_its_own_basis`는 삭제하고 아래 두 테스트로 대체하며, `test_footer_names_the_sources_and_the_query_time`은 본문만 바뀐다.

```python
def _it(key, label, value, unit, rate, sign, basis, src, basis_kind="date",
        rate_unit="%"):
    """worldidx.Item 계약 그대로 — 키가 늘거나 줄면 프런트가 먼저 깨져야 한다."""
    return {"key": key, "label": label, "value": value, "unit": unit,
            "rate": rate, "sign": sign, "basis": basis, "src": src,
            "rate_unit": rate_unit, "basis_kind": basis_kind}


def _payload(**over):
    """2026-08-11 실측값(설계 문서의 원천 표)을 그대로 쓴다."""
    d = {"asof": "2026-08-11T21:40:00+09:00",
         "groups": [
             {"label": "미국 금리", "items": [
                 _it("ust2y", "2년", 4.25, "%", 1.43, "up", "08-10", "treasury",
                     rate_unit="bp"),
                 _it("ust10y", "10년", 4.72, "%", 1.51, "up", "08-10", "treasury",
                     rate_unit="bp"),
                 _it("ust30y", "30년", 5.25, "%", 0.0, "flat", "08-10", "treasury",
                     rate_unit="bp")]},
             {"label": "원자재", "items": [
                 _it("wti", "WTI", 82.13, "$/bbl", 0.77, "up", "08-10", "fdr"),
                 _it("gold", "금", 4361.80, "$/oz", 1.67, "up", "08-10", "fdr")]},
             {"label": "해외지수", "items": [
                 _it("spx", "S&P500", 7753.11, "idx", -0.06, "down", "08-11", "kis"),
                 _it("comp", "나스닥 종합", 26605.36, "idx", 0.31, "up", "08-11", "kis"),
                 _it("vix", "VIX", 15.54, "idx", 0.52, "up", "08-11", "kis")]}]}
    d.update(over)
    return d
```

`test_every_chip_prints_its_own_basis`를 통째로 교체:

```python
@needs_node
def test_every_chip_prints_its_own_freshness(tmp_path):
    """**항목마다** 신선도 줄. 그룹 하나에 한 번이 아니다 — 원천이 달라 상태가 섞인다.

    살아 있는 코스피 칩 아래에서 상태 없는 숫자는 지금 값으로 읽힌다. 재무부는
    일 1회 '확정'이고 나머지 date는 '마감'이다 — 문구를 가르는 건 src다."""
    res = _run(tmp_path, _payload())
    assert res["display"] == ""                     # 데이터가 오면 섹션이 뜬다
    body = res["body"]
    assert body.count('class="gb"') == 8            # 3 + 2 + 3, 칩 하나에 하나씩
    assert body.count("08-10 확정") == 3            # 미국채(treasury)
    assert body.count("08-10 마감") == 2            # 원자재(fdr)
    assert body.count("08-11 마감") == 3            # 해외지수(kis)
    assert "기준 " not in body                      # 옛 문구는 사라져야 한다
    for label in ("미국 금리", "원자재", "해외지수"):
        assert label in body, label + " 소제목 누락"


@needs_node
def test_live_items_say_so_instead_of_printing_a_date(tmp_path):
    """basis_kind=live면 날짜가 아니라 상태를 찍는다.

    FDR 마지막 봉은 진행 중 세션이라 값은 실시간인데 야후가 하루 전 날짜를 찍는다 —
    그 날짜를 그대로 보여주면 살아 있는 값이 어제 종가로 읽힌다(정반대 착시)."""
    live = [{"label": "원자재", "items": [
        _it("wti", "WTI", 83.51, "$/bbl", 0.37, "up", "08-11", "fdr",
            basis_kind="live")]},
        {"label": "미국 금리", "items": [
            _it("ust10y", "10년", 4.69, "%", 0.6, "up", "08-11", "cnbc",
                basis_kind="live", rate_unit="bp")]}]
    body = _run(tmp_path, _payload(groups=live))["body"]
    assert body.count("실시간(지연)") == 2
    assert "08-11" not in body                      # live면 날짜를 안 찍는다
    assert "4.69%" in body and "0.6bp" in body
```

`test_unknown_rate_and_basis_render_a_dash_not_a_fake_zero`의 마지막 줄을 교체:

```python
    assert "– 마감" in res["body"]                  # 기준일을 모르면 대시
```

`test_footer_names_the_sources_and_the_query_time`을 교체:

```python
@needs_node
def test_footer_names_the_sources_and_the_query_time(tmp_path):
    """각주는 원천과 조회 시각을 숨기지 않는다 — 이 값들이 무지연이 아님을 말한다."""
    foot = _run(tmp_path, _payload())["foot"]
    assert "재무부" in foot and "KIS" in foot
    assert "21:40" in foot                          # asof(KST)에서 시:분
    assert "지연" in foot


@needs_node
def test_footer_names_tradeweb_when_the_yields_are_live(tmp_path):
    """CNBC로 승격된 동안은 각주도 그렇게 말한다 — 원천을 숨기지 않는다."""
    live = [{"label": "미국 금리", "items": [
        _it("ust10y", "10년", 4.69, "%", 0.6, "up", "08-11", "cnbc",
            basis_kind="live", rate_unit="bp")]}]
    foot = _run(tmp_path, _payload(groups=live))["foot"]
    assert "Tradeweb" in foot and "재무부" not in foot
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx_page.py -v`
Expected: FAIL — `기준 08-10`이 그대로 나오고 `class="gb"`는 있지만 문구가 다르며 `Tradeweb`이 없다

- [ ] **Step 3: 섹션 셸 이름·아이콘 교체**

`backend/report/dashboard.py`의 `#gsec` summary(현재 244~245행)를 교체:

```html
<details class="sec" id="gsec" style="display:none">
  <summary><svg class="hic secic"><use href="#i-bars"/></svg> 지수
    <span class="gdig" id="gsec-dig"></span><span class="chev">▾</span></summary>
```

CSS 주석 헤더(현재 150행)도 이름을 맞춘다:

```css
/* ── '지수' 섹션(국내·선물·미국채·원자재·해외지수) ──
```

- [ ] **Step 4: 신선도 렌더러 구현**

`gchip()` 정의 **바로 위**에 추가:

```js
// 신선도 줄 — 상태만 말하고 시계는 안 찍는다. 어느 칩도 '09:02 기준'처럼 쓰지 않는다:
// 그 줄만 다른 언어가 되고 "KST인가 ET인가"라는 질문을 새로 만든다. 시각은 푸터 한 곳뿐.
// basis_kind·src는 서버가 실어 보낸다 — basis 문자열 모양이나 그룹 이름으로 추측하면
// unit·rate_unit을 실어 막으려던 사고가 렌더러에서 재발한다.
function gfresh(it){
  if(it.fresh) return it.fresh;                     // 프런트 어댑터가 직접 정한 국내 칩
  if(it.basis_kind==='live') return '실시간(지연)';
  return (it.basis||'–')+(it.src==='treasury'?' 확정':' 마감');
}
```

`gchip()`의 마지막 줄(`'<div class="gb">기준 '+esc(it.basis||'–')+'</div></div>'`)을 교체:

```js
    +'<div class="gb">'+esc(gfresh(it))+'</div></div>';
```

- [ ] **Step 5: 푸터 교체**

`loadWorldidx()`의 푸터 블록을 교체:

```js
  const foot=document.getElementById('gsec-foot');
  if(foot){
    // 금리가 CNBC로 승격됐는지에 따라 앞부분이 바뀐다 — 원천을 숨기지 않는다.
    const live=gs.some(function(g){return (g.items||[]).some(function(x){
      return x&&x.src==='cnbc';});});
    foot.textContent=(live?'미국채 Tradeweb':'미 재무부(일 1회 확정)')
      +' · 야후 선물 · KIS 해외지수 — 약 10~15분 지연'
      +(d&&d.asof?' · '+String(d.asof).slice(11,16)+' 조회':'');
  }
```

원자재 지연 실측은 10~12분이었지만 화면엔 **10~15분으로 넉넉히** 적는다 — 원천이 보장한 수치가 아니라 한 시점의 관측이라, 좁게 적으면 지키지도 못할 약속이 된다.

- [ ] **Step 6: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx_page.py -v`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add backend/report/dashboard.py tests/test_worldidx_page.py
git commit -m "$(cat <<'EOF'
feat(dashboard): '글로벌' → '지수', 칩마다 신선도 줄

기준일 대신 상태를 찍는다. 원자재는 값이 실시간인데 야후가 하루 전 날짜를
찍어서 '기준 08-11'이 살아 있는 값을 어제 종가로 읽히게 만들고 있었다 —
칩마다 basis를 실은 목적(신선도 착시 방지)을 정반대로 배신하던 자리다.

어느 칩도 시계를 안 찍는다. '09:02 기준'처럼 쓰면 그 줄만 다른 언어가 되고
"KST인가 ET인가"라는 질문을 새로 만든다. 시각은 푸터 한 곳뿐이다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 프런트 — 국내 두 그룹 미러링 + `renderIdx()` 통합

**Files:**
- Modify: `backend/report/dashboard.py`
- Test: `tests/test_worldidx_page.py`

**Interfaces:**
- Consumes: `gfresh(it)`(Task 3) — 국내 칩은 `it.fresh`로 문구를 직접 넘긴다
- Produces:
  - JS `renderIdx()` — Task 5의 폴링 스케줄러가 호출
  - JS 모듈 변수 `MKT`·`FUT`·`WIDX` — 각 로더의 마지막 응답

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_worldidx_page.py`의 `_HARNESS`를 수정한다. `global.setInterval` 줄 **아래**에 두 줄 추가(Task 5가 쓰는 API를 미리 깔아둔다):

```javascript
global.clearInterval = () => {};
```

`global.fetch`를 교체(이제 `/api/market`·`/api/futures`도 답해야 한다):

```javascript
const mkt = process.argv[5] ? JSON.parse(process.argv[5]) : null;
global.fetch = async (u) => {
  const s = String(u);
  if (s.indexOf('/api/worldidx') >= 0) return {ok: !fail, json: async () => payload};
  if (mkt && s.indexOf('/api/market') >= 0) return {ok: true, json: async () => mkt.market};
  if (mkt && s.indexOf('/api/futures') >= 0) return {ok: true, json: async () => mkt.futures};
  return {ok: false, json: async () => ({})};
};
```

하니스가 `loadMarket`도 실행하도록 스크립트 선택과 결과 출력을 교체:

```javascript
const code = scripts.find(s => s.indexOf('loadWorldidx') >= 0);
```
는 그대로 두고(같은 `<script>` 블록 안에 `loadMarket`도 있다), 출력 직전 대기를 늘린다:

```javascript
    await new Promise(r => setTimeout(r, 60));   // loadMarket + loadWorldidx 둘 다
```

`_run()`을 교체:

```python
def _run(tmp_path, payload, fail=False, mkt=None):
    html = tmp_path / "dash.html"
    html.write_text(render_dashboard([], [], "2026-08-11"), encoding="utf-8")
    data = tmp_path / "world.json"
    data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    js = tmp_path / "h.js"
    js.write_text(_HARNESS, encoding="utf-8")
    argv = ["node", str(js), str(html), str(data), "fail" if fail else "-"]
    if mkt is not None:
        argv.append(json.dumps(mkt, ensure_ascii=False))
    out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert "error" not in res, res["error"]
    return res
```

> `fail` 인자가 위치 4번에서 `'fail'`/`'-'`로 바뀌었으므로 하니스의 `const fail = process.argv[4] === 'fail';`는 그대로 동작한다.

맨 끝에 테스트 추가:

```python
def _mkt():
    """/api/market + /api/futures 실응답 모양(장중)."""
    return {"market": {"kospi": {"price": 6525.01, "rate": 3.0},
                       "kosdaq": {"price": 856.4, "rate": -0.17}},
            "futures": {"k200": {"label": "K200선물", "price": 880.25,
                                 "rate": 2.8, "closed": False},
                        "nq": {"label": "나스닥 선물", "price": 29641.0,
                               "rate": -0.34}}}


@needs_node
def test_domestic_chips_are_mirrored_into_the_section(tmp_path):
    """상단 스트립의 칩이 섹션 안에도 뜬다 — 이동이 아니라 미러링이다.

    새 API 호출은 없다. loadMarket이 이미 받아온 마지막 응답을 섹션이 읽어 쓰므로
    두 곳이 같은 순간의 같은 값을 그린다."""
    res = _run(tmp_path, _payload(), mkt=_mkt())
    body = res["body"]
    assert "국내 지수" in body and "지수 선물" in body
    assert body.count('class="mchip"') == 12        # 2 + 2 + 3 + 2 + 3
    for txt in ("코스피", "코스닥", "K200선물", "나스닥 선물"):
        assert txt in body, txt + " 미러링 누락"
    # 국내 그룹이 맨 앞이다
    assert body.index("국내 지수") < body.index("지수 선물") < body.index("미국 금리")


@needs_node
def test_futures_chip_freshness_comes_from_the_server_flags(tmp_path):
    """마감·지연은 서버가 주는 closed·stale 플래그가 정한다 — 프런트가 안 지어낸다."""
    m = _mkt()
    m["futures"]["k200"]["closed"] = True
    m["futures"]["nq"]["stale"] = True
    body = _run(tmp_path, _payload(), mkt=m)["body"]
    assert "마감" in body and "지연" in body


@needs_node
def test_section_shows_up_on_domestic_alone_when_every_remote_source_dies(tmp_path):
    """해외 원천이 다 죽어도 코스피는 보여야 한다 — 그룹이 하나라도 있으면 뜬다."""
    res = _run(tmp_path, _payload(groups=[]), mkt=_mkt())
    assert res["display"] == ""
    assert res["body"].count('class="mchip"') == 4
    assert "미국 금리" not in res["body"]


@needs_node
def test_section_still_hides_when_absolutely_nothing_is_available(tmp_path):
    """전부 비면 종전대로 감춘다 — 빈 껍데기가 '데이터 없음'처럼 자리 차지 금지."""
    res = _run(tmp_path, _payload(groups=[]))
    assert res["display"] == "none" and res["body"] == ""


@needs_node
def test_worldidx_poll_does_not_erase_the_domestic_groups(tmp_path):
    """두 로더가 주기가 달라도 한 렌더 함수를 쓴다.

    합치지 않으면 worldidx 폴링(느림)이 국내 그룹(빠름)을 덮어써서 지운다."""
    res = _run(tmp_path, _payload(), mkt=_mkt())
    assert "코스피" in res["body"] and "미국 금리" in res["body"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx_page.py -k "domestic or futures_chip or worldidx_poll or absolutely_nothing" -v`
Expected: FAIL — `국내 지수` 없음, 칩 8개(12 아님), 그룹이 비면 섹션이 숨음

- [ ] **Step 3: `loadMarket`이 마지막 응답을 남기게 한다**

`loadMarket()`의 `let d={}, f={};` 줄과 그 아래 파싱부를 교체:

```js
    let d={}, f={};
    try{ if(rm&&rm.ok) d=await rm.json(); }catch(e){}
    try{ if(rf&&rf.ok) f=await rf.json(); }catch(e){}
    // 섹션이 읽어 쓴다 — 상단 스트립과 **같은 순간의 같은 값**이라 두 곳 숫자가
    // 어긋나지 않는다. 국내 그룹에 새 API 호출이 없는 것도 이 때문이다.
    MKT=d||{}; FUT=f||{};
```

그리고 `loadMarket()` 끝의 `if(parts.length){...}` **뒤**에 한 줄 추가:

```js
    renderIdx();
```

- [ ] **Step 4: 국내 어댑터 + `renderIdx()` 구현**

`const GKEY=[...]` 줄 **바로 위**에 추가:

```js
// ── '지수' 섹션 — 국내 어댑터. 서버는 이 두 그룹을 모른다(worldidx는 해외 전용). ──
let MKT={}, FUT={}, WIDX=null;      // 각 로더의 마지막 응답
// ⚠️ 설계 문서 C절은 판정 근거로 `pulseState()`를 적었으나 **여기서 벗어난다**:
// pulseState는 NXT 프리/애프터도 '장중'으로 치는데 그건 개별 종목 얘기지 지수가 아니다.
// 그대로 쓰면 20시에 코스피 칩이 '실시간'이라 우긴다. 코스피·코스닥 **지수**는
// 09:00~15:30(KRX 정규장)에만 움직이므로 그 창을 명시적으로 쓴다.
// (부수 효과: 서버 렌더 시 치환되는 __PULSE_EXT__에 이 판정이 매이지 않는다.)
function krIndexLive(){
  const n=new Date(), d=n.getDay(), hm=n.getHours()*60+n.getMinutes();
  return d>=1&&d<=5&&hm>=540&&hm<930;
}
// 국내 칩은 신선도를 서버가 안 주므로 어댑터가 직접 정해 `fresh`로 싣는다(gfresh가
// 그걸 우선한다). 값 모양은 worldidx.Item과 같게 맞춘다 — gchip 하나로 다 그린다.
function gadapt(label, o, fresh){
  if(!o||o.price==null) return null;
  const nm=o.label||label||'';
  return {key:nm, label:nm, value:o.price, unit:'idx',
          rate:(o.rate==null?null:o.rate),
          sign:(o.rate>0?'up':(o.rate<0?'down':'flat')),
          basis:null, src:'kr', rate_unit:'%', basis_kind:'live', fresh:fresh};
}
function gdomestic(){
  const gs=[], live=krIndexLive()?'실시간':'마감';
  const idx=[gadapt('코스피',MKT.kospi,live),
             gadapt('코스닥',MKT.kosdaq,live)].filter(Boolean);
  if(idx.length) gs.push({label:'국내 지수', items:idx});
  // 선물은 서버가 closed·stale을 준다 — 프런트가 세션을 다시 판정하지 않는다.
  const fx=function(o){ return gadapt(null,o,
    o&&o.closed?'마감':(o&&o.stale?'지연':'실시간')); };
  const fut=[fx(FUT.k200),fx(FUT.nq)].filter(Boolean);
  if(fut.length) gs.push({label:'지수 선물', items:fut});
  return gs;
}
```

- [ ] **Step 5: `loadWorldidx()`를 렌더와 분리**

`loadWorldidx()`를 통째로 교체:

```js
async function loadWorldidx(){
  let d=null;
  try{
    const r=await fetch('/api/worldidx');
    if(r&&r.ok) d=await r.json();
  }catch(e){}
  WIDX=d;
  renderIdx();
}
// 두 로더(loadMarket 30초 / loadWorldidx)가 **한 렌더 함수**를 쓴다. 합치지 않으면
// 느린 쪽 폴링이 빠른 쪽 그룹을 덮어써서 지운다.
function renderIdx(){
  const sec=document.getElementById('gsec'); if(!sec) return;
  // 한 원천이 죽으면 그 그룹만 빠지고 나머지는 뜬다(칩 스트립의 기존 원칙).
  const remote=((WIDX&&WIDX.groups)||[]).filter(function(g){
    return g&&(g.items||[]).length;});
  const gs=gdomestic().concat(remote);
  // 전부 비면 섹션을 통째로 감춘다 — 빈 껍데기가 '데이터 없음'처럼 자리 차지 금지.
  // 국내 그룹만 있어도 뜬다: 해외 원천이 다 죽어도 코스피는 보여야 한다.
  if(!gs.length){ sec.style.display='none'; return; }
  sec.style.display='';
  const body=document.getElementById('gsec-body');
  if(body) body.innerHTML=gs.map(ggroup).join('');
  const dig=document.getElementById('gsec-dig');
  if(dig) dig.textContent=gdigest(WIDX);
  const foot=document.getElementById('gsec-foot');
  if(foot){
    const live=remote.some(function(g){return (g.items||[]).some(function(x){
      return x&&x.src==='cnbc';});});
    foot.textContent=(live?'미국채 Tradeweb':'미 재무부(일 1회 확정)')
      +' · 야후 선물 · KIS 해외지수 — 약 10~15분 지연'
      +(WIDX&&WIDX.asof?' · '+String(WIDX.asof).slice(11,16)+' 조회':'');
  }
}
```

- [ ] **Step 6: 통과 확인 + 전체 회귀**

Run: `.venv/bin/python -m pytest tests/test_worldidx_page.py tests/test_dashboard.py tests/test_render.py -v`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add backend/report/dashboard.py tests/test_worldidx_page.py
git commit -m "$(cat <<'EOF'
feat(dashboard): 상단 지수·선물 칩을 '지수' 섹션에 미러링

이동이 아니라 미러링이다 — 상단 sticky 스트립은 그대로 둔다. 스크롤을 내려도
시장 상태가 따라오는 게 그 자리의 존재 이유다.

새 API 호출은 없다. 이미 30초마다 도는 loadMarket의 마지막 응답을 섹션이
읽어 쓰므로 두 곳이 같은 순간의 같은 값을 그린다.

두 로더가 renderIdx() 하나를 공유한다 — 합치지 않으면 느린 쪽 폴링이 빠른 쪽
그룹을 덮어써서 지운다. 그리고 그룹이 하나라도 있으면 섹션이 뜬다: 해외
원천이 다 죽어도 코스피는 보여야 한다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 폴링 주기 분기 + 390px 실렌더 검증

**Files:**
- Modify: `backend/report/dashboard.py`
- Test: `tests/test_worldidx_page.py`

**Interfaces:**
- Consumes: `renderIdx()`·`loadWorldidx()`(Task 4)
- Produces: 없음(마지막 태스크)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_worldidx_page.py`의 `_HARNESS`에서 Task 4가 만든 **`setInterval`·`clearInterval` 두 줄을** 아래로 교체(호출 주기를 기록한다):

```javascript
const timers = [];
global.setInterval = (fn, ms) => { timers.push(ms); return timers.length; };
global.clearInterval = () => {};
```

출력 JSON에 한 줄 추가:

```javascript
      timers: timers,
```

맨 끝에 테스트 추가:

```python
@needs_node
def test_polling_is_slow_while_the_section_is_collapsed(tmp_path):
    """접히면 5분, 펼치면 60초.

    접힌 줄의 세 값은 분 단위로 안 변한다. 아무도 안 보는 값에 CNBC를 분당 3콜씩
    때릴 이유가 없다. (서버 캐시가 실제 원격 호출량을 정하므로 60초 폴링이 CNBC
    호출을 늘리지는 않지만, 굳이 두드릴 이유도 없다.)"""
    res = _run(tmp_path, _payload(), mkt=_mkt())    # 하니스 mock은 open:false
    assert 300000 in res["timers"], res["timers"]
    assert 60000 not in res["timers"], "접힌 채로 60초 폴링 — 접힘 분기 없음"


def test_section_registers_a_toggle_listener():
    """펼침/접힘 전환에 주기를 다시 잡으려면 toggle을 들어야 한다."""
    html = render_dashboard([], [], "2026-08-11")
    assert "'toggle'" in html or '"toggle"' in html
    assert "widxSchedule" in html
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx_page.py -k "polling or toggle" -v`
Expected: FAIL — 현재는 항상 `setInterval(loadWorldidx,300000)` 고정이라 `widxSchedule`이 없다

- [ ] **Step 3: 폴링 스케줄러 구현**

`loadWorldidx(); setInterval(loadWorldidx,300000);` 줄(주석 두 줄 포함)을 교체:

```js
// 폴링 주기 — 펼치면 60초, 접히면 5분. 접힌 줄(digest)의 세 값은 분 단위로 안 변하고,
// 아무도 안 보는 값을 분당 여러 번 두드릴 이유가 없다. 실제 원격 호출량은 서버 캐시가
// 정한다(금리·원자재 600초, KIS 지수 60초) — 펼침 60초가 CNBC 호출을 늘리지는 않는다.
let _widxTimer=null, _widxMs=0;
function widxSchedule(){
  const sec=document.getElementById('gsec');
  const ms=(sec&&sec.open)?60000:300000;
  if(ms===_widxMs) return;                 // 같은 주기면 타이머를 새로 만들지 않는다
  _widxMs=ms;
  if(_widxTimer) clearInterval(_widxTimer);
  _widxTimer=setInterval(loadWorldidx, ms);
}
(function(){
  const sec=document.getElementById('gsec');
  if(sec&&sec.addEventListener) sec.addEventListener('toggle', function(){
    widxSchedule();
    if(sec.open) loadWorldidx();           // 펼치는 즉시 한 번 — 5분 묵은 값을 안 보여준다
  });
})();
loadWorldidx(); widxSchedule();
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_worldidx_page.py -v`
Expected: 전부 PASS

- [ ] **Step 5: 전체 테스트 스위트**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 전부 PASS. 실패가 있으면 이 계획이 건드린 파일(`worldidx.py`·`dashboard.py`) 때문인지 먼저 확인하고, 무관한 기존 실패면 그대로 두고 보고한다.

- [ ] **Step 6: 390px 실렌더 검증 — 이 계획의 진짜 게이트**

문자열 검사는 "칩이 그려졌다"까지만 말한다. **390px에서 5그룹 12칩이 어떻게 접히는지, 칩 높이가 맞는지는 실렌더로만 보인다** (`__LIB__` 미치환·원화 반올림 함정이 실렌더로만 잡혔던 전례가 있다).

```bash
.venv/bin/python -m harness verify --only dashboard --theme both
```

`harness/cmd/verify.py`의 `SCREENS`에 `("dashboard", "route", "/")`가 이미 있다. 데모 서버는 KIS 키를 차단하므로 8000 실서버와 무관하다. 결과 스크린샷은 `harness/artifacts/`에 떨어진다 — **열어서 눈으로 본다.** 헤드리스 크롬이 없으면 verify가 `"헤드리스 크롬 미설치 — verify 생략"`을 찍고 0으로 끝나므로, 그 문구가 보이면 검증이 **안 된 것**이다(통과로 읽지 말 것).

**눈으로 확인할 것:**
1. 5그룹이 `국내 지수 → 지수 선물 → 미국 금리 → 원자재 → 해외지수` 순
2. 그룹당 칩이 한 줄에 들어가고, 넘칠 때 잘리지 않고 **줄바꿈**된다
3. **모든 칩의 높이가 같다** — 신선도 줄이 하나라도 빠지면 그 칩만 짧아진다
4. 접힌 줄이 `미국채 10Y · WTI · 금` 세 값을 다 담는다(마지막 '금'이 잘리지 않는다)
5. 다크/라이트 양쪽에서 신선도 줄이 읽힌다

- [ ] **Step 7: 라이브 스모크**

데모/verify 경로에서 `/api/worldidx`를 한 번 호출해 응답을 눈으로 본다:

```bash
.venv/bin/python -c "
import asyncio, json
from backend.flow import worldidx
d = asyncio.run(worldidx.get_worldidx())
print(json.dumps(d, ensure_ascii=False, indent=1)[:2000])
"
```

**확인할 것:**
- `미국 금리` 그룹의 `src`가 장중이면 `cnbc`·`basis_kind`가 `live`, 휴장이면 `treasury`·`date`
- 금리 값이 상식 범위(2~6%)에 있고 `rate_unit`이 `bp`
- 모든 item에 `basis_kind`가 있다

- [ ] **Step 8: 커밋**

```bash
git add backend/report/dashboard.py tests/test_worldidx_page.py
git commit -m "$(cat <<'EOF'
feat(dashboard): '지수' 섹션 폴링 — 펼치면 60초, 접히면 5분

접힌 줄의 세 값은 분 단위로 안 변한다. 아무도 안 보는 값을 분당 여러 번
두드릴 이유가 없다. 펼치는 순간엔 즉시 한 번 불러 5분 묵은 값을 안 보여준다.

실제 원격 호출량은 서버 캐시가 정하므로(금리·원자재 600초, KIS 지수 60초)
펼침 60초가 CNBC 호출을 늘리지는 않는다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 완료 후

`docs/superpowers/specs/2026-08-12-index-section-design.md`의 '하지 않는 것'에 남긴 후속 과제는 그대로 둔다. 다음 주제는 [[market-sentiment-candidates]](아줌마 지수 대조 — 코스피 일별 1콜로 3지표)로, **이 계획이 끝난 뒤** 별도 브레인스토밍으로 착수한다.
