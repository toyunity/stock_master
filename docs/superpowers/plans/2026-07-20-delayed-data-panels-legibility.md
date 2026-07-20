# 지연 데이터 패널 초보 가독성 개선 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/live/{code}`의 대차잔고·공매도·신용융자 패널을 3단 공개(초보→중급→🔬전문가) 카드로 재구성해, 타이밍(T+1/T+2)·실시간vs확정·개념·가독성을 초보가 바로 읽게 한다.

**Architecture:** 데이터는 SSE 스냅샷 `S`(S.shortbal/S.shortsale/S.credit)로 오고 `live_page.py`의 단일 `render(S)` JS가 DOM id로 채운다. 이 작업은 **표시(껍데기)만** 바꾼다 — 마크업 재구성 + JS 라벨/전문가 지표 채우기 + CSS. 유일한 엔진 변경은 대차 L3 순증용 `parse_kofia`에 체결/상환 필드 추가.

**Tech Stack:** FastAPI 서빙 자기완결 HTML(외부 CDN 0), 클라이언트 JS, KIS/KOFIA 데이터, pytest + node 실행 스모크.

**Spec:** `docs/superpowers/specs/2026-07-20-delayed-data-panels-legibility-design.md` (커밋 c023991, 3183537)

## Global Constraints

- **Python 3.9 호환**(`shortbal.py`): `match`·`X | Y` 금지, `Optional[...]` 사용.
- **자기완결 HTML**: 외부 폰트/CDN 0. 공유 태그 CSS는 `theme.py`(`.tag-live`/`.tag-fixed`), 패널 전용 CSS는 `live_page.py`의 `<style>` 블록.
- **엔진 산출 불변**: shortsale/credit 반환 필드·수집 주기 변경 없음. `parse_kofia`만 `contract`/`repay` 추가(기존 `qty`/`value` 불변).
- **데이터 경로**: 렌더는 `render(S)`가 `S.shortbal={rows,signal}`·`S.shortsale={rows}`·`S.credit={rows,signal}`를 읽어 채운다. 서버 스냅샷 구조는 안 바꾼다(대차 rows에 contract/repay가 얹혀 자동 전달).
- **카피 verbatim**(스펙 카피 목록):
  - 알약: `🕐 {날짜} 기준 · T+1`(대차·공매도) / `🕐 {날짜} 기준 · T+2`(신용). 데이터 대기 시 `🕐 데이터 대기`.
  - 초보 1줄: 대차 `빌려간 주식(공매도 준비 물량). 늘면 매도 부담 ↑, 줄면 상환 신호.` / 공매도 `실제로 공매도로 쏜 물량. 비중 높으면 그날 매도 압력이 셌다는 뜻.` / 신용 `빚내서 산 주식. 급락하면 다음 날 아침 반대매매(강제청산) 연료 — 클수록 하락 가속.`
  - L2 토글 `ⓘ 자세히 ▾` · L3 토글 `🔬 전문가 지표 ▾` · 태그 `🟢 실시간`/`🕐 확정`.
- **접근성**: 알약·태그는 색 + 텍스트(🕐/🟢, T+1/T+2) 병기(색만으로 구분 금지). 기존 theme 토큰만(신규 하드코딩 색 0). `<details>` 네이티브 접힘·키보드 포커스 유지. 새 애니메이션은 `prefers-reduced-motion` 존중.
- **테스트 실행**: `.venv/bin/python -m pytest tests/ -q -p no:warnings` (프로젝트 루트). node 실행 스모크는 node 없으면 skip(기존 `needs_node` 패턴).
- **커밋**: 한국어 conventional commits. 메시지 끝에 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01AfTjj4WQcXs5qsfWaAgtCi`.

## File Structure

| 파일 | 역할 | 태스크 |
|---|---|---|
| `backend/flow/shortbal.py` | `parse_kofia`+`_fetch_kofia` 행에 체결/상환(TMPV3/4) | T1 |
| `backend/report/theme.py` | `.tag-live`/`.tag-fixed` 공유 알약 토큰 | T2 |
| `backend/report/live_page.py` | `<style>`(밴드·카드·`.det`·`.pro`) + 3패널 마크업 재구성 + 확정 밴드 + render JS(pill·초보1줄·L3) | T2·T3·T4 |
| `tests/test_shortbal.py` | parse_kofia 체결/상환 단언 | T1 |
| `tests/test_live_page_js.py` | 하네스 출력 id 추가 + 픽스처 contract/repay + pill/L3 단언 | T2·T3·T4 |

---

### Task 1: `parse_kofia`에 체결/상환 추가 (대차 L3 순증 원천)

**Files:**
- Modify: `backend/flow/shortbal.py:48-56`(parse_kofia), `:174-176`(_fetch_kofia 행 조립)
- Test: `tests/test_shortbal.py`

**Interfaces:**
- Produces: `parse_kofia(js, code) -> {"qty":int,"value":int,"contract":int,"repay":int} | None`.
- Produces: KOFIA 경로 대차 rows에 `contract`/`repay` 키 추가(SEIBro 폴백 행엔 없음 → 소비측 `undefined`).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_shortbal.py` 끝에 추가

```python
def test_parse_kofia_returns_contract_and_repay():
    """TMPV3 체결·TMPV4 상환을 추가 반환(L3 순증=체결-상환용). 기존 qty/value 불변."""
    from backend.flow.shortbal import parse_kofia
    js = {"ds1": [{"TMPV2": "000660", "TMPV3": "420000", "TMPV4": "300000",
                   "TMPV5": "14140221", "TMPV6": "30825681780000"}]}
    got = parse_kofia(js, "000660")
    assert got == {"qty": 14140221, "value": 30825681780000,
                   "contract": 420000, "repay": 300000}


def test_parse_kofia_missing_flow_fields_default_zero():
    from backend.flow.shortbal import parse_kofia
    js = {"ds1": [{"TMPV2": "000660", "TMPV5": "100", "TMPV6": "200"}]}
    got = parse_kofia(js, "000660")
    assert got["contract"] == 0 and got["repay"] == 0
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_shortbal.py -k parse_kofia -q`
Expected: FAIL — 반환 dict에 `contract`/`repay` 키 없음(KeyError 또는 `!=`).

- [ ] **Step 3: 구현** — `backend/flow/shortbal.py`

`parse_kofia`(48행) 반환부를 교체:

```python
    for r in js.get("ds1") or []:
        if str(r.get("TMPV2", "")) == code:
            return {"qty": int(r.get("TMPV5") or 0),
                    "value": int(r.get("TMPV6") or 0),
                    "contract": int(r.get("TMPV3") or 0),   # 신규 대차 체결
                    "repay": int(r.get("TMPV4") or 0)}      # 상환
    return None
```

`_fetch_kofia`의 행 조립(175-176행)에 두 필드 추가:

```python
            rows.append({"date": d.isoformat(), "qty": found["qty"],
                         "value": found["value"], "src": "kofia",
                         "contract": found.get("contract"),
                         "repay": found.get("repay")})
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_shortbal.py -q`
Expected: 전부 passed (기존 shortbal 테스트 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add backend/flow/shortbal.py tests/test_shortbal.py
git commit -m "feat(shortbal): parse_kofia 체결/상환(TMPV3/4) 반환 — 대차 순증(L3 전문가) 원천

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AfTjj4WQcXs5qsfWaAgtCi"
```

---

### Task 2: 확정 밴드 + 실시간/확정 태그 CSS + [왜 늦어요?]

**Files:**
- Modify: `backend/report/theme.py`(BASE_CSS 끝, `img,canvas` 위)
- Modify: `backend/report/live_page.py:316`(sechd → 확정 밴드), `<style>` 블록(67행 `.advtoggle` 근처)
- Test: `tests/test_live_page_js.py`

**Interfaces:**
- Produces: CSS 클래스 `.tag-live`·`.tag-fixed`(theme.py) · `.fixed-band`·`.whyfixed`(live_page).
- Produces: 확정 밴드 헤더 + `<details class="whyfixed">` 펼침(마커: `왜 늦어요`).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_live_page_js.py`의 `test_render_js_executes_and_fills_all_panels`에 추가(함수 끝 단언 뒤). HTML 자체 검사이므로 `html_p` 텍스트를 읽어 단언:

```python
    # 확정 밴드 · 태그(설계 2026-07-20)
    page = html_p.read_text(encoding="utf-8")
    assert "tag-fixed" in page and "tag-live" in page
    assert "왜 늦어요" in page
    assert "실시간 아님" in page
```

(참고: `html_p`는 이 테스트가 이미 `render_live_page(...)`로 만들어 파일에 쓴 페이지 — 기존 `_run`/`test_render...`에서 생성. 없으면 Step 3 후 이 단언이 그 문자열을 검사.)

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -k fills_all_panels -q`
Expected: FAIL — `tag-fixed`/`왜 늦어요` 마커 없음(AssertionError).

- [ ] **Step 3: 구현**

`backend/report/theme.py` — BASE_CSS 안, `img,canvas{max-width:100%}`(문자열 내) 바로 앞에 추가:

```python
/* 실시간/확정 상태 태그(초보용 구분) */
.tag-live,.tag-fixed{display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:800;
  border-radius:var(--r-pill);padding:2px 8px;vertical-align:middle;letter-spacing:0}
.tag-live{background:var(--good-bg);color:var(--good)}
.tag-fixed{background:var(--warn-bg);color:var(--warn)}
```

`backend/report/live_page.py` — `<style>` 블록의 `.advtoggle` 규칙(67행) 뒤에 추가:

```css
/* 확정 밴드(대차·공매도·신용) — 하루~이틀 전 데이터임을 초보에게 명시 */
.fixed-band{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
.whyfixed{margin-left:auto}
.whyfixed>summary{list-style:none;cursor:pointer;font-size:11.5px;font-weight:800;color:var(--primary);
  background:var(--info-bg);border-radius:var(--r-sm);padding:3px 9px;min-height:32px;
  display:inline-flex;align-items:center}
.whyfixed>summary::-webkit-details-marker{display:none}
.whyfixed-body{font-size:12.5px;color:var(--text-2);line-height:1.55;margin-top:8px;
  background:var(--surface-2);border-radius:var(--r-sm);padding:9px 12px}
```

`backend/report/live_page.py:316`의 `<div class="sechd">⚠️ 위험 신호 · 떨어질 연료</div>`를 교체:

```html
<div class="sechd fixed-band">
  <span><span class="tag-fixed">🕐 확정</span> 하루~이틀 전 · 실시간 아님 · 떨어질 때 연료</span>
  <details class="whyfixed"><summary>왜 늦어요? ▾</summary>
    <div class="whyfixed-body">장 마감 뒤 집계·정산돼서 다음 영업일(공매도·대차)~이틀 뒤(신용융자)에
    확정돼요. 그래서 오늘이 아니라 며칠 전 날짜로 보이는 게 정상이에요. 지금 이 순간의 매수·매도
    압력은 위의 <span class="tag-live">🟢 실시간</span> 수급·호가·체결에서 보세요.</div>
  </details>
</div>
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -q`
Expected: passed(또는 node 없으면 해당 스모크 skip, HTML 문자열 단언은 통과)

- [ ] **Step 5: 커밋**

```bash
git add backend/report/theme.py backend/report/live_page.py tests/test_live_page_js.py
git commit -m "feat(live): 확정 밴드 + 실시간/확정 태그 + [왜 늦어요?] — 지연 데이터 구분

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AfTjj4WQcXs5qsfWaAgtCi"
```

---

### Task 3: 3패널 초보 카드 (L1 핵심 + L2 자세히) — 타이밍 알약·큰 숫자·초보 1줄

**Files:**
- Modify: `backend/report/live_page.py:317-364`(3패널 마크업), `<style>`(카드·`.det` CSS), render JS(1055-1088 대차 / 1122-1142 공매도 / 1144-1171 신용)
- Test: `tests/test_live_page_js.py`(하네스 id 추가 + pill 단언)

**Interfaces:**
- Consumes: 스냅샷 `SB/SS/CR`(rows·signal), 기존 헬퍼 `num`·`shares`·`cls`·`jo`·`spark`·`srcKo`.
- Produces: 새 DOM id `sb-pill`·`ss-pill`·`cr-pill`(타이밍 알약). 기존 id(sb-qty/sb-sig/…) 역할 유지, 위치만 재배치.
- Produces: JS 헬퍼 `fmtD(iso)` → `M/D(요일)` 문자열.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_live_page_js.py`

(a) 하네스 `_HARNESS`의 `TXT:` 출력 id 목록(49-52행)에 `'sb-pill','ss-pill','cr-pill'` 추가.
(b) `test_render_js_executes_and_fills_all_panels`의 기존 단언을 교체·추가:

```python
    # 타이밍 알약(설계 2026-07-20) — 지연이 알약으로 명시
    assert "T+1" in texts["sb-pill"] and "7/10" in texts["sb-pill"]
    assert "T+1" in texts["ss-pill"] and "7/10" in texts["ss-pill"]
    assert "T+2" in texts["cr-pill"] and "7/10" in texts["cr-pill"]
    # 초보 1줄이 페이지에 존재
    page = html_p.read_text(encoding="utf-8")
    assert "빌려간 주식(공매도 준비 물량)" in page
    assert "빚내서 산 주식" in page and "반대매매" in page
```

기존 190행 `assert "기준일: 2026-07-10" in texts["ss-fresh"]` → 삭제(타이밍은 이제 ss-pill).
기존 192행 `assert ... in texts["cr-fresh"] and "T+2" in texts["cr-fresh"]` → `assert texts["cr-fresh"]`(출처 문구 존재만) 로 완화, T+2 단언은 위 cr-pill로 이동.
174행 `assert "금융투자협회" in texts["sb-fresh"]`·173행 `"건강한 상승" in texts["sb-sig"]`·193행 `cr-sig startswith("판정:")` 는 **유지**(출처는 sb-fresh, 판정은 sig에 그대로 남김).

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -k fills_all_panels -q`
Expected: FAIL — `sb-pill` 등 미정의(빈 문자열) → 단언 실패.

- [ ] **Step 3: 마크업 재구성** — `backend/report/live_page.py:317-364` 3개 `.panel`을 아래로 교체(id 보존 + 카드 구조):

```html
<div class="panel dp">
  <div class="dp-h"><h2>🩳 대차잔고</h2><span class="pill fixed" id="sb-pill">🕐 데이터 대기</span></div>
  <div class="dp-key"><span class="dp-num" id="sb-qty">–</span><span class="sig" id="sb-sig"></span></div>
  <p class="dp-one">빌려간 주식(공매도 준비 물량). 늘면 매도 부담 ↑, 줄면 상환 신호.</p>
  <div class="dp-foot"><span class="sparkwrap"><span class="sk-cap">대차 20일</span><span class="sk-svg" id="sb-spark"></span></span></div>
  <details class="det"><summary class="a-more">ⓘ 자세히 ▾</summary>
    <div class="det-body">
      <div class="grid3">
        <div><div class="lbl">전일 대비</div><div class="val" id="sb-chg">–</div></div>
        <div><div class="lbl">잔고 금액</div><div class="val" id="sb-val">–</div></div>
        <div><div class="lbl">출처</div><div class="val meta" id="sb-fresh">·</div></div>
      </div>
      <details class="inline" style="margin-top:8px"><summary>최근 20거래일 추이</summary>
        <div class="tbl-wrap"><table id="sb-hist" style="margin-top:6px"></table></div></details>
      <div class="meta" id="sb-note">대차잔고 = 공매도 등을 위해 빌려간 뒤 아직 갚지 않은 주식 수(T+1 공시).</div>
    </div>
  </details>
</div>

<div class="panel dp">
  <div class="dp-h"><h2>🎯 공매도 일별 체결</h2><span class="pill fixed" id="ss-pill">🕐 데이터 대기</span></div>
  <div class="dp-key"><span class="dp-num" id="ss-qty">–</span><span class="sig" id="ss-ratio-big"></span></div>
  <p class="dp-one">실제로 공매도로 쏜 물량. 비중 높으면 그날 매도 압력이 셌다는 뜻.</p>
  <div class="dp-foot"><span class="sparkwrap"><span class="sk-cap">공매도 20일</span><span class="sk-svg" id="ss-spark"></span></span></div>
  <details class="det"><summary class="a-more">ⓘ 자세히 ▾</summary>
    <div class="det-body">
      <div class="grid3">
        <div><div class="lbl">거래량 비중</div><div class="val" id="ss-ratio">–</div></div>
        <div><div class="lbl">대차잔고 대비</div><div class="val" id="ss-vs">–</div></div>
        <div><div class="lbl">출처</div><div class="val meta" id="ss-fresh">·</div></div>
      </div>
      <details class="inline" style="margin-top:8px"><summary>최근 20거래일 추이</summary>
        <div class="tbl-wrap"><table id="ss-hist" style="margin-top:6px"></table></div></details>
      <div class="meta">위 대차잔고가 '빌린 물량'이라면 이것은 '실제로 쏜 물량'(T+1 확정). 비중 = 그날 전체 거래량 중 공매도 비율.</div>
    </div>
  </details>
</div>

<div class="panel dp">
  <div class="dp-h"><h2>💳 신용융자 잔고</h2><span class="pill fixed" id="cr-pill">🕐 데이터 대기</span></div>
  <div class="dp-key"><span class="dp-num" id="cr-qty">–</span><span class="sig" id="cr-sig"></span></div>
  <p class="dp-one">빚내서 산 주식. 급락하면 다음 날 아침 반대매매(강제청산) 연료 — 클수록 하락 가속.</p>
  <div class="dp-foot"><span class="sparkwrap"><span class="sk-cap">신용 20일</span><span class="sk-svg" id="cr-spark"></span></span></div>
  <details class="det"><summary class="a-more">ⓘ 자세히 ▾</summary>
    <div class="det-body">
      <div class="grid3">
        <div><div class="lbl">전일 대비</div><div class="val" id="cr-chg">–</div></div>
        <div><div class="lbl">잔고 금액≈</div><div class="val" id="cr-val">–</div></div>
        <div><div class="lbl">출처</div><div class="val meta" id="cr-fresh">·</div></div>
      </div>
      <details class="inline" style="margin-top:8px"><summary>최근 20거래일 추이</summary>
        <div class="tbl-wrap"><table id="cr-hist" style="margin-top:6px"></table></div></details>
      <div class="meta" id="cr-note">신용융자 = 빚내서 산 주식. 급락하면 다음 날 아침 반대매매(강제청산)로 쏟아진다. 금액은 주수×종가 환산(≈).</div>
    </div>
  </details>
</div>
```

주의: 공매도 판정 자리는 `sig` id를 새로 `ss-ratio-big`으로 두되 JS에서 비중 강조 텍스트를 채운다(기존 판정 로직 없음).

- [ ] **Step 4: 카드 CSS 추가** — `<style>` 블록(Task2에서 추가한 `.whyfixed-body` 뒤)에:

```css
/* 지연 데이터 초보 카드 */
.dp .dp-h{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.dp .dp-h h2{font-size:16px}
.pill{font-family:var(--font-mono,ui-monospace,Menlo,monospace);font-size:11px;font-weight:700;
  white-space:nowrap;display:inline-flex;align-items:center;gap:5px;border-radius:var(--r-pill);padding:3px 9px}
.pill.fixed{background:var(--warn-bg);color:var(--warn)}
.dp-key{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:6px 0 4px}
.dp-num{font-size:26px;font-weight:900;letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.dp-one{font-size:13px;color:var(--text-2);font-weight:600;line-height:1.5;margin:0 0 10px}
.dp-foot{display:flex;align-items:center;justify-content:flex-end}
.det>summary.a-more{list-style:none;cursor:pointer;font-size:12px;font-weight:800;color:var(--primary);
  background:var(--info-bg);border-radius:var(--r-sm);padding:5px 11px;min-height:34px;
  display:inline-flex;align-items:center;-webkit-tap-highlight-color:transparent}
.det>summary::-webkit-details-marker{display:none}
.det>summary:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:8px}
.det[open]>summary.a-more{background:var(--primary);color:#fff}
.det-body{margin-top:10px;display:grid;gap:10px}
```

- [ ] **Step 5: render JS 수정** — `backend/report/live_page.py`

(a) `render` 함수 안 헬퍼 근처(예: `jo` 정의 아래, 1048행 뒤)에 날짜 포맷터 추가:

```javascript
  const _dow='일월화수목금토';
  const fmtD=iso=>{const p=(iso||'').split('-');if(p.length!==3)return iso||'';
    const dt=new Date(+p[0],+p[1]-1,+p[2]);return (+p[1])+'/'+(+p[2])+'('+_dow[dt.getDay()]+')';};
```

(b) 대차 블록(1055-1056행 sb-fresh 세팅)을 교체 — 알약은 타이밍, fresh는 출처만:

```javascript
    document.getElementById('sb-pill').textContent='🕐 '+fmtD(last.date)+' 기준 · T+1';
    document.getElementById('sb-fresh').textContent='출처 '+(srcKo[last.src]||last.src)
      +(mixed?' · ⚠ 기간 내 출처 혼합':'');
```

(c) 공매도 블록(1124행 ss-fresh)을 교체 + 비중 강조:

```javascript
    document.getElementById('ss-pill').textContent='🕐 '+fmtD(sl.date)+' 기준 · T+1';
    document.getElementById('ss-fresh').textContent='출처 KIS';
    document.getElementById('ss-ratio-big').textContent='비중 '+(sl.ratio||0).toFixed(1)+'%';
    document.getElementById('ss-ratio-big').className='sig sig-'+((sl.ratio||0)>=5?'warn':'flat');
```

(d) 신용 블록(1147행 cr-fresh)을 교체:

```javascript
    document.getElementById('cr-pill').textContent='🕐 '+fmtD(cl.date)+' 기준 · T+2';
    document.getElementById('cr-fresh').textContent='출처 KIS · 결제 반영';
```

(e) 빈 상태(else)에서 알약을 대기로 — 각 else 블록 첫 줄에 추가:
`document.getElementById('sb-pill').textContent='🕐 데이터 대기';`(공매도·신용도 각 id로 동일).

주의: 기존 `sb-fresh`/`ss-fresh`/`cr-fresh`에 timing/출처를 함께 넣던 줄은 위 (b)(c)(d)로 대체됨(중복 설정 제거).

- [ ] **Step 6: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -q`
Expected: passed (node 있으면 pill/초보1줄 단언 통과; 없으면 HTML 문자열 단언만 통과·스모크 skip)

- [ ] **Step 7: 커밋**

```bash
git add backend/report/live_page.py tests/test_live_page_js.py
git commit -m "feat(live): 지연 패널 초보 카드(L1+L2) — 타이밍 알약 T+1/T+2·큰 숫자+판정·초보 1줄

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AfTjj4WQcXs5qsfWaAgtCi"
```

---

### Task 4: L3 🔬 전문가 지표 (대차 순증·공매도 과열·신용 정밀판정)

**Files:**
- Modify: `backend/report/live_page.py`(3패널 L2 det-body 안에 L3 details 추가, render JS L3 채우기, `.pro` CSS)
- Test: `tests/test_live_page_js.py`(하네스 id + L3 단언 + 픽스처 contract/repay)

**Interfaces:**
- Consumes: `SB.rows[last].contract/repay`(Task1), `SS.rows[*].value/ratio`, `CR.rows[last].ratio/new/rdmp`, `CR.signal`.
- Produces: 새 id — 대차 `sb-pro-flow`·`sb-pro-rate`·`sb-pro-src`; 공매도 `ss-pro-value`·`ss-pro-ratio`·`ss-pro-avg`·`ss-pro-verdict`; 신용 `cr-pro-ratio`·`cr-pro-flow`·`cr-pro-rate`·`cr-pro-verdict`·`cr-pro-basis`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_live_page_js.py`

(a) 픽스처 `_full_snapshot`의 `s.set_short({"rows":[...]})` 마지막 행(2026-07-10)에 `"contract": 420000, "repay": 700048` 추가(순증 = 420000-700048 = -280048 = 그 행의 chg와 일치하도록).
(b) 하네스 `TXT:` id 목록에 `'sb-pro-flow','ss-pro-value','ss-pro-verdict','cr-pro-verdict','cr-pro-flow'` 추가.
(c) 단언 추가(node 스모크 함수 내):

```python
    # L3 전문가 지표(설계 2026-07-20) — 실데이터
    assert "🔬 전문가 지표" in html_p.read_text(encoding="utf-8")
    assert "순증" in texts["sb-pro-flow"]                     # 체결-상환
    assert "억" in texts["ss-pro-value"] or "–" != texts["ss-pro-value"]
    assert "평균" in texts["ss-pro-verdict"]                  # 20일 평균 대비 문구
    assert texts["cr-pro-verdict"] and texts["cr-pro-flow"]   # 정밀판정·신규/상환
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -k fills_all_panels -q`
Expected: FAIL — `🔬 전문가 지표` 마커·`sb-pro-flow` 등 없음.

- [ ] **Step 3: 마크업 — 각 패널 det-body 끝(추이 details와 note 사이 또는 note 뒤)에 L3 추가**

대차 det-body 안에:
```html
      <details class="pro"><summary>🔬 전문가 지표 ▾</summary>
        <div class="pro-body">
          <div class="pro-grid">
            <div class="pro-cell"><div class="pl">체결−상환(순증)</div><div class="pv" id="sb-pro-flow">–</div></div>
            <div class="pro-cell"><div class="pl">잔고 증감률</div><div class="pv" id="sb-pro-rate">–</div></div>
            <div class="pro-cell"><div class="pl">소스</div><div class="pv" id="sb-pro-src">–</div></div>
          </div>
        </div></details>
```
공매도 det-body 안에:
```html
      <details class="pro"><summary>🔬 전문가 지표 ▾</summary>
        <div class="pro-body">
          <div class="pro-grid">
            <div class="pro-cell"><div class="pl">거래대금</div><div class="pv" id="ss-pro-value">–</div></div>
            <div class="pro-cell"><div class="pl">비중</div><div class="pv" id="ss-pro-ratio">–</div></div>
            <div class="pro-cell"><div class="pl">20일 평균</div><div class="pv" id="ss-pro-avg">–</div></div>
          </div>
          <div class="pro-verdict" id="ss-pro-verdict"></div>
        </div></details>
```
신용 det-body 안에:
```html
      <details class="pro"><summary>🔬 전문가 지표 ▾</summary>
        <div class="pro-body">
          <div class="pro-grid">
            <div class="pro-cell"><div class="pl">잔고비율</div><div class="pv" id="cr-pro-ratio">–</div></div>
            <div class="pro-cell"><div class="pl">신규/상환</div><div class="pv" id="cr-pro-flow">–</div></div>
            <div class="pro-cell"><div class="pl">증감률</div><div class="pv" id="cr-pro-rate">–</div></div>
          </div>
          <div class="pro-verdict" id="cr-pro-verdict"></div>
          <div class="pro-basis" id="cr-pro-basis"></div>
        </div></details>
```

- [ ] **Step 4: `.pro` CSS 추가** — `<style>` 블록에:

```css
/* L3 전문가 지표 */
.pro{margin-top:2px;border:1px solid var(--border);border-radius:var(--r-sm);background:var(--info-bg)}
.pro>summary{list-style:none;cursor:pointer;padding:8px 11px;font-size:12px;font-weight:800;
  color:var(--primary-ink);display:flex;align-items:center;-webkit-tap-highlight-color:transparent}
.pro>summary::-webkit-details-marker{display:none}
.pro>summary:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:8px}
.pro-body{padding:0 11px 11px;display:grid;gap:9px}
.pro-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px}
.pro-cell{background:var(--surface);border-radius:var(--r-sm);padding:7px 9px;text-align:center}
.pro-cell .pl{font-size:9.5px;color:var(--text-3);font-weight:800}
.pro-cell .pv{font-size:13px;font-weight:900;margin-top:1px;font-variant-numeric:tabular-nums}
.pro-verdict{font-size:12px;font-weight:800;border-radius:var(--r-sm);padding:7px 10px;line-height:1.45;
  background:var(--warn-bg);color:var(--warn)}
.pro-basis{font-size:11px;color:var(--text-3);font-weight:700}
```

- [ ] **Step 5: render JS — L3 채우기**

대차(성공 블록, sb-note 세팅 뒤)에 추가:
```javascript
    const _net=(last.contract!=null&&last.repay!=null)?last.contract-last.repay:null;
    document.getElementById('sb-pro-flow').textContent=_net==null?'–':(_net>0?'순증 +':'순증 ')+shares(_net);
    const _prevq=SB.rows.length>1?SB.rows[SB.rows.length-2].qty:null;
    document.getElementById('sb-pro-rate').textContent=(_prevq?((last.qty-_prevq)/_prevq*100).toFixed(1)+'%':'–');
    document.getElementById('sb-pro-src').textContent=(srcKo[last.src]||last.src);
```
공매도(성공 블록 끝)에 추가:
```javascript
    document.getElementById('ss-pro-value').textContent=eok(sl.value).replace('+','');
    document.getElementById('ss-pro-ratio').textContent=(sl.ratio||0).toFixed(2)+'%';
    const _avg=SS.rows.reduce((a,r)=>a+(r.ratio||0),0)/SS.rows.length;
    document.getElementById('ss-pro-avg').textContent=_avg.toFixed(2)+'%';
    const _hot=(sl.ratio||0)>_avg;
    const pv=document.getElementById('ss-pro-verdict');
    pv.textContent=_hot?('비중이 20일 평균('+_avg.toFixed(1)+'%)을 웃돎 — 공매도 과열 구간')
      :('비중이 20일 평균('+_avg.toFixed(1)+'%) 이하 — 평시');
    pv.className='pro-verdict'+(_hot?'':' flat');
```
신용(성공 블록, cr-hist 세팅 뒤)에 추가:
```javascript
    document.getElementById('cr-pro-ratio').textContent=(cl.ratio||0).toFixed(2)+'%';
    document.getElementById('cr-pro-flow').textContent=(cl.new!=null?num(cl.new):'–')+' / '+(cl.rdmp!=null?num(cl.rdmp):'–');
    const _cpq=CR.rows.length>1?CR.rows[CR.rows.length-2].qty:null;
    document.getElementById('cr-pro-rate').textContent=(_cpq?((cl.qty-_cpq)/_cpq*100).toFixed(1)+'%':'–');
    document.getElementById('cr-pro-verdict').textContent=csig?csig.text:'판정 대기';
    document.getElementById('cr-pro-basis').textContent='deal_date 기준 · 결제 반영 T+2';
```

(빈 상태 else에서는 pro 값이 '–'로 남으면 되므로 별도 초기화 불필요 — 마크업 기본값 '–'.)

- [ ] **Step 6: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -q && .venv/bin/python -m pytest tests/ -q -p no:warnings`
Expected: 전부 passed

- [ ] **Step 7: 커밋**

```bash
git add backend/report/live_page.py tests/test_live_page_js.py
git commit -m "feat(live): L3 🔬 전문가 지표 — 대차 순증·공매도 과열(20일 평균)·신용 정밀판정(실데이터)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AfTjj4WQcXs5qsfWaAgtCi"
```

---

## Self-Review 결과 (계획 작성 후 점검)

- **스펙 커버리지**: A 태그시스템(T2)·B 확정밴드+왜늦어요(T2)·C 초보카드 L1/L2(T3)·C-2 L3 전문가(T4)·D 신용 T+2(T3 알약)·카피 verbatim(T3/T4)·parse_kofia 확장(T1)·테스트(각 태스크) — 전 항목 매핑 확인. "실시간 vs 확정"은 확정 밴드 + [왜 늦어요?]의 🟢/🕐 대비로 달성(스펙 '알려진 제약'대로 라벨링 방식).
- **자리표시자**: 없음. 기존 테스트 단언 변경(190·192행 이동)은 새 기대값을 명시했고, 삭제/완화 대상 행을 특정함.
- **타입 일관성**: `parse_kofia` 반환 키(contract/repay)가 T1 정의 → T4 JS(`last.contract/last.repay`)에서 사용 일치. pill/pro id 명명(sb-pill, sb-pro-flow…)이 마크업(T3/T4)·JS(T3/T4)·테스트에서 동일. `fmtD` 헬퍼는 T3에서 정의 후 T3에서만 사용. 공매도 판정 자리 id는 `ss-ratio-big`로 T3 마크업·JS 일치(기존 판정 로직 신설 금지 원칙 유지).
- **주의(구현자용)**: `live_page.py`는 큰 파일 — 마크업/JS 편집 시 실제 행 번호가 이동했을 수 있으니 id·문구로 앵커링해 Edit. render 블록의 기존 `sb-fresh`/`ss-fresh`/`cr-fresh` 세팅 줄을 T3에서 반드시 새 (b)(c)(d)로 대체(중복 설정이 남으면 알약/출처가 덮어써짐).
