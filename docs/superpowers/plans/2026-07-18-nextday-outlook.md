# 내일장 예상 + 종목 상세 고도화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관심종목 상세를 값 인식형 쉬운말로 설명하고, 오늘 신호(미국장·ADR·수급·모멘텀)를 규칙으로 조합해 "내일 방향 배지 + 근거 + 주의"를 대시보드/‌live에 보여준다.

**Architecture:** 순수 함수 2개(glossary 쉬운말, nextday 규칙엔진)를 TDD로 만들고, marketdata가 신호를 수집해 엔진에 넣어 엔드포인트로 노출, /live·대시보드가 렌더한다. LLM 없음 — 규칙 하나 = 근거 한 줄.

**Tech Stack:** Python 3.9(match문·`X|Y`힌트 금지), FastAPI, 순수 파서/규칙 함수, KIS REST(캐시 토큰), 클라이언트 렌더 JS(node 문법/‌render 하니스로 검증).

## Global Constraints

- Python 3.9 호환만(zoneinfo OK, match·PEP604 금지).
- KIS 토큰 **재발급 금지** — 캐시(`data/cache/kis_token.json`) 재사용, 매 라이브 프로브 전 `expires_at` 선검사.
- **웹소켓 미접촉**(1키1세션 — 마스터 실시간 세션 보호). REST만.
- 실서버(8000) 재기동은 `.venv/bin/python`, graceful SIGTERM 후 healthz 확인.
- 모든 예상에 **"시나리오·확정 아님·빗나갈 수 있음"** + 근거 공개 + 리스크 한 줄. 기존 면책 유지. 개인용 전제.
- 값 없음/신호 결측은 에러 아니라 **생략**(조용히). 위젯 화이트리스트 불변.
- 테스트: `.venv/bin/python -m pytest`. 커밋은 feature 단위 green 후.

---

### Task 1: glossary 값 인식형 쉬운말 (순수 함수)

**Files:**
- Modify: `backend/education/glossary.py` (read_* 함수 추가)
- Test: `tests/test_glossary.py` (없으면 생성)

**Interfaces:**
- Produces: `read_per(v)`, `read_pbr(v)`, `read_w52_pos(v)`, `read_roe(v)`, `read_debt(v)`, `read_bid_ratio(v)`, `read_flow(frgn_net, orgn_net)` → `Optional[str]` (값 None이면 None).

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_glossary.py`

```python
from backend.education.glossary import (
    read_per, read_pbr, read_w52_pos, read_roe, read_debt, read_bid_ratio, read_flow)


def test_read_per_bands():
    assert read_per(None) is None
    assert "적자" in read_per(0)                 # <=0
    assert "싼 편" in read_per(8)
    assert "보통" in read_per(15)
    assert "비싼 편" in read_per(31)
    assert "매우 비쌈" in read_per(80)


def test_read_w52_and_debt_and_flow():
    assert "고점 부근" in read_w52_pos(85)
    assert "저점 부근" in read_w52_pos(12)
    assert "적은 편" in read_debt(36)            # 안정
    assert "많은 편" in read_debt(180)
    assert read_flow(None, None) is None
    assert "쌍끌이" in read_flow(1000, 2000) or "동반 순매수" in read_flow(1000, 2000)
    assert "동반 순매도" in read_flow(-500, -300)
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_glossary.py -q` · Expected: ImportError(read_per 없음)

- [ ] **Step 3: 최소 구현** — `backend/education/glossary.py`에 추가

```python
from typing import Optional


def _g(v):  # 정수/실수 표기 정리(31.0 → 31)
    return ("%g" % v)


def read_per(v) -> Optional[str]:
    if v is None:
        return None
    if v <= 0:
        return "PER — 적자거나 계산 불가라 PER로는 판단이 어려워요"
    if v < 10:
        return "PER %s — 이익 대비 싼 편이에요 (업종마다 달라요)" % _g(v)
    if v < 20:
        return "PER %s — 보통 수준이에요" % _g(v)
    if v < 40:
        return "PER %s — 이익의 %s배, 비싼 편이에요" % (_g(v), _g(v))
    return "PER %s — 매우 비쌈(기대가 크게 반영)" % _g(v)


def read_pbr(v) -> Optional[str]:
    if v is None or v <= 0:
        return None
    if v < 1:
        return "PBR %s — 순자산보다 싸게 거래돼요" % _g(v)
    if v < 2:
        return "PBR %s — 보통 수준" % _g(v)
    return "PBR %s — 순자산의 %s배, 비싼 편" % (_g(v), _g(v))


def read_w52_pos(v) -> Optional[str]:
    if v is None:
        return None
    if v >= 80:
        return "52주 %s%% — 1년 고점 부근" % _g(v)
    if v <= 20:
        return "52주 %s%% — 1년 저점 부근" % _g(v)
    return "52주 %s%% — 1년 범위 중간쯤" % _g(v)


def read_roe(v) -> Optional[str]:
    if v is None:
        return None
    if v >= 15:
        return "ROE %s%% — 자본 대비 잘 버는 편" % _g(v)
    if v >= 5:
        return "ROE %s%% — 보통" % _g(v)
    return "ROE %s%% — 수익성 약한 편" % _g(v)


def read_debt(v) -> Optional[str]:
    if v is None:
        return None
    if v < 50:
        return "부채비율 %s%% — 빚 적은 편, 안정적" % _g(v)
    if v < 150:
        return "부채비율 %s%% — 보통 수준" % _g(v)
    return "부채비율 %s%% — 빚 많은 편, 주의" % _g(v)


def read_bid_ratio(v) -> Optional[str]:
    if v is None:
        return None
    if v >= 55:
        return "매수세 %s%% — 사자(받침)가 더 두꺼움" % _g(v)
    if v <= 45:
        return "매수세 %s%% — 팔자(벽)가 더 두꺼움" % _g(v)
    return "매수세 %s%% — 사자·팔자 팽팽" % _g(v)


def read_flow(frgn_net, orgn_net) -> Optional[str]:
    if frgn_net is None and orgn_net is None:
        return None
    f, o = frgn_net or 0, orgn_net or 0
    if f > 0 and o > 0:
        return "외국인·기관 쌍끌이 순매수 — 수급 받침"
    if f < 0 and o < 0:
        return "외국인·기관 동반 순매도 — 수급 부담"
    return "외국인·기관 수급 혼조"
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_glossary.py -q` · Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/education/glossary.py tests/test_glossary.py
git commit -m "feat(education): 값 인식형 쉬운말 리더(PER·PBR·52주·ROE·부채·매수세·수급)"
```

---

### Task 2: nextday 규칙 엔진 (순수 함수)

**Files:**
- Create: `backend/signals/nextday.py`
- Test: `tests/test_nextday.py`

**Interfaces:**
- Consumes: 없음(입력 dict만).
- Produces: `outlook(signals: dict) -> dict` — 반환 `{direction, score, reasons:[{text,dir}], caution, session, framing}`. `signals` 키: `session:str`, `is_semi:bool`, `us:{sox_rate,nasdaq_rate,us_open}|None`, `adr:{overnight_rate}|None`, `flow:{frgn_net,orgn_net}|None`, `momentum:{rate,overheated}|None`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_nextday.py`

```python
from backend.signals.nextday import outlook


def _sig(**kw):
    base = {"session": "us_closed", "is_semi": True, "us": None,
            "adr": None, "flow": None, "momentum": None}
    base.update(kw)
    return base


def test_bullish_when_us_up_and_dual_buy():
    o = outlook(_sig(us={"sox_rate": 2.1, "nasdaq_rate": 1.2, "us_open": False},
                     flow={"frgn_net": 1000, "orgn_net": 2000}))
    assert o["direction"] == "up"
    assert any("반도체" in r["text"] or "미국" in r["text"] for r in o["reasons"])
    assert o["caution"]                                   # 항상 주의 한 줄


def test_overheated_pulls_to_neutral_with_caution():
    o = outlook(_sig(momentum={"rate": 12.0, "overheated": True},
                     flow={"frgn_net": -500, "orgn_net": 300}))
    assert o["direction"] == "neutral"
    assert "되돌림" in o["caution"] or "과열" in o["caution"]


def test_adr_gap_up_drives_bullish():
    o = outlook(_sig(adr={"overnight_rate": 2.5}))
    assert o["direction"] == "up"
    assert any("ADR" in r["text"] or "DR" in r["text"] for r in o["reasons"])


def test_bearish_when_us_down_and_outflow():
    o = outlook(_sig(us={"sox_rate": -2.5, "nasdaq_rate": -1.5, "us_open": False},
                     flow={"frgn_net": -900, "orgn_net": -400}))
    assert o["direction"] == "down"


def test_framing_follows_session():
    assert "밤" in outlook(_sig(session="kr_closed_us_pending"))["framing"]
    assert "간밤" in outlook(_sig(session="us_closed"))["framing"]
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_nextday.py -q` · Expected: ModuleNotFoundError

- [ ] **Step 3: 최소 구현** — `backend/signals/nextday.py`

```python
from __future__ import annotations

"""내일장 방향 규칙 엔진 — 순수 함수. 신호(미국장·ADR·수급·모멘텀)를 가중 합산해
방향 배지 + 근거 + 주의를 만든다. LLM 없음: 규칙 하나 = 근거 한 줄. 개인용·참고용.
Python 3.9 호환."""

_UP, _DOWN = 2, -2   # 방향 임계값

_FRAMING = {
    "kr_closed_us_pending": "오늘 마감 기준 · 오늘 밤 미국장이 변수예요",
    "us_live": "미국장 진행 중 흐름 반영",
    "us_closed": "간밤 미국·ADR 반영",
    "kr_open": "오늘 장중 흐름",
}


def _rate(d, *keys):
    for k in keys:
        v = (d or {}).get(k)
        if v is not None:
            return v
    return None


def outlook(signals: dict) -> dict:
    session = signals.get("session", "us_closed")
    reasons, caution, score = [], [], 0

    # 1) ADR 오버나잇(가장 직접적) — ADR 종목·데이터 있을 때
    adr = signals.get("adr")
    if adr and adr.get("overnight_rate") is not None:
        r = adr["overnight_rate"]
        w = 2 if r > 1.5 else 1 if r > 0.5 else -2 if r < -1.5 else -1 if r < -0.5 else 0
        if w:
            score += w
            reasons.append({"text": "나스닥 DR이 밤새 %+.1f%% — 내일 갭%s 여지" % (
                r, "업" if w > 0 else "다운"), "dir": "up" if w > 0 else "down"})

    # 2) 미국 반도체/나스닥 — 반도체·수출 상관 종목
    us = signals.get("us")
    if us and signals.get("is_semi"):
        sr = _rate(us, "sox_rate", "nasdaq_rate")
        if sr is not None and session != "kr_closed_us_pending":
            w = 2 if sr > 2 else 1 if sr > 1 else -2 if sr < -2 else -1 if sr < -1 else 0
            if w:
                score += w
                reasons.append({"text": "간밤 미국 반도체 %s(SOX %+.1f%%)" % (
                    "강세" if w > 0 else "약세", sr), "dir": "up" if w > 0 else "down"})
        elif sr is not None:
            caution.append("오늘 밤 미국 반도체 방향이 큰 변수예요")

    # 3) 수급(오늘)
    flow = signals.get("flow")
    if flow:
        f, o = flow.get("frgn_net") or 0, flow.get("orgn_net") or 0
        if f > 0 and o > 0:
            score += 1
            reasons.append({"text": "오늘 외국인·기관 쌍끌이 순매수(받침)", "dir": "up"})
        elif f < 0 and o < 0:
            score -= 1
            reasons.append({"text": "오늘 외국인·기관 동반 순매도(부담)", "dir": "down"})

    # 4) 모멘텀(오늘) — 과열은 0점 + 되돌림 주의
    mo = signals.get("momentum")
    if mo and mo.get("rate") is not None:
        if mo.get("overheated"):
            caution.append("오늘 급등 — 내일 되돌림(차익실현) 나올 수 있어요")
        elif mo["rate"] > 3:
            score += 1
            reasons.append({"text": "오늘 강한 상승 흐름 지속", "dir": "up"})
        elif mo["rate"] < -3:
            score -= 1
            reasons.append({"text": "오늘 약세 흐름", "dir": "down"})

    direction = "up" if score >= _UP else "down" if score <= _DOWN else "neutral"
    # 반대 신호를 주의로(방향과 다른 dir의 근거)
    opp = [r["text"] for r in reasons if r["dir"] != direction and direction != "neutral"]
    if opp:
        caution.append("다만 " + opp[0] + " 는 반대 요인")
    caution.append("예상일 뿐 빗나갈 수 있어요 · 참고용")

    return {"direction": direction, "score": score, "reasons": reasons,
            "caution": " · ".join(caution), "session": session,
            "framing": _FRAMING.get(session, _FRAMING["us_closed"])}
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_nextday.py -q` · Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/signals/nextday.py tests/test_nextday.py
git commit -m "feat(signals): 내일장 방향 규칙 엔진(미국·ADR·수급·모멘텀→배지+근거+주의)"
```

---

### Task 3: marketdata 신호 수집 + 엔드포인트

**Files:**
- Modify: `backend/api/marketdata.py` (get_outlook, get_outlook_brief, get_stock_detail 확장)
- Modify: `backend/api/app.py` (`/api/outlook` 추가)
- Test: `tests/test_marketdata.py` (조립·캐시)

**Interfaces:**
- Consumes: `nextday.outlook`, `glossary.read_*`, 기존 `_client()`, `KisClient.fundamentals/financials/asking_price`, `backend.flow.adr`, `backend.flow.semi`.
- Produces: `get_outlook(code, client=None) -> dict|None`(풀), `get_outlook_brief(codes, client=None) -> dict`(code→{direction,reason}), `get_stock_detail(code)` 반환에 `outlook`·`explains` 추가.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_marketdata.py`에 추가

```python
def test_get_outlook_assembles_and_caches(monkeypatch):
    from backend.api import marketdata as md
    md._outlook_cache.clear()

    class C:
        def __init__(self): self.calls = 0
        async def fundamentals(self, code): return {"per": 31.0, "w52_pos": 58.0}
        async def financials(self, code): return [{"period": "2026-03", "roe": 61.0, "debt": 36.0}]
        async def asking_price(self, code): return {"bid_ratio": 44.0}
    # 신호 소스 스텁(미국·ADR·수급) — 모두 강세
    async def fake_signals(code, client): 
        return {"session": "us_closed", "is_semi": True,
                "us": {"sox_rate": 2.1, "nasdaq_rate": 1.0, "us_open": False},
                "adr": {"overnight_rate": 2.0}, "flow": {"frgn_net": 1, "orgn_net": 1},
                "momentum": {"rate": 1.0, "overheated": False}}
    monkeypatch.setattr(md, "_gather_signals", fake_signals)
    c = C()
    o = asyncio.run(md.get_outlook("000660", client=c))
    assert o["direction"] == "up" and o["reasons"]
    asyncio.run(md.get_outlook("000660", client=c))         # 60초 캐시
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_marketdata.py -q -k outlook` · Expected: AttributeError(_outlook_cache/_gather_signals 없음)

- [ ] **Step 3: 최소 구현** — `backend/api/marketdata.py`에 추가/확장

```python
from backend.signals import nextday
from backend.education import glossary

_OUTLOOK_TTL = 60.0
_outlook_cache: dict = {}   # code -> (ts, dict)


async def _gather_signals(code, client):
    """미국·ADR·수급·모멘텀 신호 수집(부분 실패 허용). session은 market_status/adr로 판정."""
    from backend.flow import semi, adr, market_status
    from backend.flow.candles import _get_client  # noqa
    now = None
    sig = {"is_semi": True, "us": None, "adr": None, "flow": None, "momentum": None}
    # 세션
    us_open = adr.us_market_open()
    kr_open = market_status.wallclock_open()
    sig["session"] = ("kr_open" if kr_open else "us_live" if us_open else
                      "us_closed")
    try:
        ov = await semi.get_overview()
        g = {x["sym"]: x for x in (ov.get("us") or [])}
        sig["us"] = {"sox_rate": (g.get("SOX") or {}).get("rate"),
                     "nasdaq_rate": (g.get("NDX") or g.get("COMP") or {}).get("rate"),
                     "us_open": ov.get("us_open")}
    except Exception:
        pass
    try:
        q = await adr.get_quote(client, code)
        if q and q.get("usd") and q.get("base_usd"):
            sig["adr"] = {"overnight_rate": (q["usd"] / q["base_usd"] - 1) * 100}
    except Exception:
        pass
    # 수급/모멘텀은 있으면 채움(없으면 생략)
    try:
        rows = await client.daily_investor(code)
        if rows:
            sig["flow"] = {"frgn_net": rows[0].get("frgn"), "orgn_net": rows[0].get("orgn")}
    except Exception:
        pass
    try:
        p = await client.price(code)
        if p and p.get("rate") is not None:
            sig["momentum"] = {"rate": p["rate"], "overheated": p["rate"] >= 10}
    except Exception:
        pass
    return sig


async def get_outlook(code, client=None):
    client = client or _client()
    if client is None:
        return None
    hit = _outlook_cache.get(code)
    import time as _t
    if hit and _t.time() - hit[0] < _OUTLOOK_TTL:
        return hit[1]
    sig = await _gather_signals(code, client)
    if not any(sig.get(k) for k in ("us", "adr", "flow", "momentum")):
        return None
    o = nextday.outlook(sig)
    _outlook_cache[code] = (_t.time(), o)
    return o


def _explains(val, fin):
    """valuation+financials → 지표 쉬운말 맵."""
    v, f = val or {}, (fin or [{}])[0]
    out = {}
    for k, fn, src in (("per", glossary.read_per, v), ("pbr", glossary.read_pbr, v),
                       ("w52", glossary.read_w52_pos, v.get("w52_pos")),
                       ("roe", glossary.read_roe, f.get("roe")),
                       ("debt", glossary.read_debt, f.get("debt"))):
        pass
    out["per"] = glossary.read_per(v.get("per"))
    out["pbr"] = glossary.read_pbr(v.get("pbr"))
    out["w52"] = glossary.read_w52_pos(v.get("w52_pos"))
    out["roe"] = glossary.read_roe(f.get("roe"))
    out["debt"] = glossary.read_debt(f.get("debt"))
    return {k: x for k, x in out.items() if x}
```

그리고 기존 `get_stock_detail` 반환에 추가(‌valuation·financials 계산 뒤):

```python
    data = {"valuation": val, "financials": fin[:4],
            "outlook": await get_outlook(code, client),
            "explains": _explains(val, fin)}
```

`get_outlook_brief`(대시보드 경량):

```python
async def get_outlook_brief(codes, client=None):
    client = client or _client()
    if client is None or not codes:
        return {}
    out = {}
    for c in codes[:12]:
        o = await get_outlook(c, client)     # 캐시 공유
        if o:
            r = o["reasons"][0]["text"] if o["reasons"] else o["framing"]
            out[c] = {"direction": o["direction"], "reason": r}
    return out
```

- [ ] **Step 4: 엔드포인트** — `backend/api/app.py`의 `/api/fundamentals` 아래에 추가

```python
    @app.get("/api/outlook")
    async def outlook_api(request: Request):
        from backend.api import marketdata
        from backend.flow import userstore
        codes = userstore.get_kr_codes(_req_email(request, settings))
        return JSONResponse(await marketdata.get_outlook_brief(codes))
```

- [ ] **Step 5: 통과 확인 + 커밋**

Run: `.venv/bin/python -m pytest tests/test_marketdata.py -q` · Expected: PASS
```bash
git add backend/api/marketdata.py backend/api/app.py tests/test_marketdata.py
git commit -m "feat(api): 내일 예상 신호 수집(get_outlook)+쉬운말 explains+/api/outlook"
```

---

### Task 4: /live 렌더 — 내일 예상 카드 + 쉬운말 병기

**Files:**
- Modify: `backend/report/live_page.py` (hero 아래 outlook 카드 + fin 라인 쉬운말)
- Test: `tests/test_live_page_js.py`(구조/‌render 하니스) — 기존 하니스 통과 유지

**Interfaces:**
- Consumes: `/api/financials/{code}` 응답의 `outlook`·`explains`(Task 3).

- [ ] **Step 1: DOM + CSS 추가** — hero 안 `#ob` 아래

```html
  <div class="nd" id="nd" style="display:none"></div>
```
CSS(‌`.hero .ob` 아래):
```css
.hero .nd{margin-top:10px;border:1px solid var(--line);border-radius:12px;padding:11px 12px;background:var(--surface)}
.nd .badge-nd{font-weight:800;font-size:14px}
.nd.up .badge-nd{color:var(--up)} .nd.down .badge-nd{color:var(--down)} .nd.neutral .badge-nd{color:var(--text-2)}
.nd ul{margin:7px 0 0;padding-left:16px;font-size:12.5px;color:var(--text-2)}
.nd .cau{margin-top:6px;font-size:11.5px;color:var(--text-2)}
```

- [ ] **Step 2: loadFin 확장** — 기존 loadFin에서 outlook·explains 렌더 추가(‌`el.style.display='block'` 뒤)

```javascript
  // 쉬운말 병기
  const ex=d.explains||{};
  const exline=['per','pbr','w52','roe','debt'].map(k=>ex[k]).filter(Boolean);
  if(exline.length){ el.title=exline.join('\n'); }   // 길게: 지표 위 설명
  // 내일 예상 카드
  const o=d.outlook, nd=document.getElementById('nd');
  if(o&&o.direction){
    const ko={up:'🔴 강세 우세',down:'🔵 약세 우세',neutral:'⚪ 중립'}[o.direction];
    nd.className='nd '+o.direction;
    nd.innerHTML='<span class="badge-nd">🔮 내일 예상: '+ko+'</span> '
      +'<span style="font-size:11.5px;color:var(--text-2)">· '+esc(o.framing)+'</span>'
      +'<ul>'+(o.reasons||[]).map(r=>'<li>'+esc(r.text)+'</li>').join('')+'</ul>'
      +'<div class="cau">⚠ '+esc(o.caution)+'</div>';
    nd.style.display='block';
  }
```

- [ ] **Step 3: 검증** — Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -q` (render 하니스 통과) + 구조 렌더로 `id="nd"`/‌`🔮 내일 예상` 존재 + `node --check` JS 문법. Expected: PASS

- [ ] **Step 4: 커밋**

```bash
git add backend/report/live_page.py tests/test_live_page_js.py
git commit -m "feat(live): 내일 예상 카드(배지+근거+주의) + 지표 쉬운말 병기"
```

---

### Task 5: 대시보드 카드 배지

**Files:**
- Modify: `backend/report/dashboard.py` (cardHtml에 nd 배지 슬롯 + loadOutlook)

**Interfaces:**
- Consumes: `/api/outlook`(Task 3) — code→{direction,reason}.

- [ ] **Step 1: cardHtml 슬롯 + JS** — `.cval` 아래에 `<div class="cnd" data-code>` 추가, loadFundamentals 옆에 loadOutlook

```javascript
async function loadOutlook(){
  try{
    const r=await fetch('/api/outlook'); if(!r.ok)return;
    const d=await r.json();
    for(const code in d){ const o=d[code]; if(!o)continue;
      const ko={up:'🔴강세',down:'🔵약세',neutral:'⚪중립'}[o.direction]||'';
      document.querySelectorAll('.cnd[data-code="'+code+'"]').forEach(function(el){
        el.textContent='내일 '+ko+' · '+o.reason; });
    }
  }catch(e){}
}
loadOutlook(); setInterval(loadOutlook,300000);
```
CSS: `.cnd{font-size:12px;color:var(--text-2);margin-top:3px;font-weight:600}`

- [ ] **Step 2: 검증 + 커밋** — 구조 렌더로 `class="cnd"`/‌`loadOutlook`/‌`/api/outlook` 존재 + `node --check`. 전체 스위트 green.

```bash
git add backend/report/dashboard.py
git commit -m "feat(dashboard): 카드에 내일 예상 배지(한 줄)"
```

---

### Task 6: 라이브 검증 + 배포

- [ ] **Step 1: 라이브 신호 1회 확인**(캐시 토큰·REST만) — `get_outlook("000660")` 실행해 direction/reasons 실데이터 확인. 재발급 0.
- [ ] **Step 2: 전체 스위트** — `.venv/bin/python -m pytest -q` green.
- [ ] **Step 3: 배포** — `.venv/bin/python`으로 8000 graceful 재기동 + healthz 200 + 엔드포인트 등록 확인.
- [ ] **Step 4: 문서 갱신** — 스펙 상태 완료 표기, 커밋.

---

## Self-Review

- **Spec coverage:** ①쉬운말=Task1 · ②규칙엔진=Task2 · ③신호수집/엔드포인트=Task3 · ④/live 렌더=Task4 · ⑤대시보드=Task5 · 안전프레이밍=Task2(caution)+Task4(⚠) · 테스트=각 Task · 라이브/배포=Task6. 누락 없음.
- **Placeholder:** `_explains`의 미사용 루프 잔재 제거할 것(구현 시 정리) — 실제 매핑은 명시됨.
- **Type consistency:** outlook 반환 키(direction/reasons[{text,dir}]/caution/framing) Task2↔3↔4↔5 일치. get_outlook_brief는 {direction,reason} — 대시보드 소비와 일치.
