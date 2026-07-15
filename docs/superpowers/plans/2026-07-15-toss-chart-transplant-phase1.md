# 토스증권 차트 이식 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/live` 가격 차트를 토스증권 차트 룩으로 이식한다 — 이평선 5·10·20·60·120, 최고/최저 자동 주석, 현재가/등락 강조, 거래량 라벨.

**Architecture:** 기존 Lightweight Charts v4 차트(`live_page.py` 인라인 JS)와 `candles.py` MA 계산을 확장한다. 엔진/SSE/element ID는 불변. 시각 요소는 아이폰 폭 CDP 스크린샷으로 레퍼런스(IMG_3529)와 대조하며 수렴한다.

**Tech Stack:** FastAPI(자립형 HTML 템플릿), Lightweight Charts v4(인라인), Python 3.9, pytest, node(JS 실행 스모크), CDP(헤드리스 크롬 스크린샷).

## Global Constraints

- Lightweight Charts **v4** 유지. 엔진(FlowEngine/KIS/candles fetch)·SSE `render()` 계약·**element ID 불변**.
- 신규 차트 API는 **전부 node 하니스 가드**: `if(pchart.addLineSeries)`, `if(pseries.setMarkers)` 등. 하니스 stub(`tests/test_live_page_js.py:35-39`)엔 `addLineSeries`/`addHistogramSeries`/`setMarkers`가 없다.
- `setMarkers`의 `time`은 **반드시 `_mapped[i].time`을 재사용**(이미 `toTs()` KST-epoch 변환을 거친 값). 새로 시각을 만들지 말 것(날짜 어긋남 + 하니스는 통과시켜 CDP로만 잡힘).
- Python **3.9 호환**. 테스트/서버는 `.venv/bin/python`.
- 색: 상승=적/하락=청(한국 관례). 기존 301 테스트 유지.
- 검증 서버는 **8001을 `SM_FLOW_MODE=demo SM_AUTH_ENABLED=false`로** 기동(라이브로 띄우면 KIS 1키1세션을 훔쳐 8000 실시간이 죽음).

---

### Task 0: CDP 스크린샷 검증 서버(8001 데모·무인증) 기동

**Files:** (코드 변경 없음 — 검증 환경 준비)

- [ ] **Step 1: 8001에 다른 인스턴스가 없는지 확인**

Run: `lsof -nP -iTCP:8001 -sTCP:LISTEN 2>/dev/null || echo free`
Expected: `free` (없으면 진행). 있으면 그 PID가 데모인지 확인 후 사용.

- [ ] **Step 2: 데모·무인증 서버 기동(라이브 모드 금지 — KIS 세션 보호)**

```bash
cd /Users/toyunity/dev/stock_master
SM_FLOW_MODE=demo SM_AUTH_ENABLED=false nohup .venv/bin/python -m backend.cli serve --port 8001 >> data/serve_demo.log 2>&1 </dev/null & disown
```

- [ ] **Step 3: 무인증으로 페이지가 열리는지 확인(302 아님)**

Run: `sleep 2; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/live/000660`
Expected: `200` (인증 게이트 off 확인). 302면 `SM_AUTH_ENABLED=false`가 안 먹은 것 — 로그 확인.

- [ ] **Step 4: 헤드리스 크롬(9222)이 떠 있는지 확인, 없으면 기동**

Run: `curl -s http://127.0.0.1:9222/json/version >/dev/null 2>&1 && echo up || echo down`
down이면: `/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless --remote-debugging-port=9222 --disable-gpu >/dev/null 2>&1 & disown`

---

### Task 1: candles.py — ma5·ma10 추가

**Files:**
- Modify: `backend/flow/candles.py:35-46` (`_attach_ma`)
- Test: `tests/test_candles.py` (없으면 생성)

**Interfaces:**
- Produces: `_attach_ma(bars)` 가 각 봉에 `ma5,ma10,ma20,ma60,ma120` 부착(표본 부족 시 `None`). 프런트(Task 2)가 `c.ma5` 등을 읽는다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_candles.py` 에 추가(파일 없으면 생성, 상단 `from backend.flow.candles import _attach_ma`):

```python
def test_attach_ma_includes_5_and_10():
    bars = [{"close": float(i)} for i in range(1, 13)]  # 1..12
    out = _attach_ma(bars)
    # ma5: 앞 4개 None, 5번째부터 값. 5~9번째 종가 평균 = (5+6+7+8+9)/5 = 7.0
    assert out[0]["ma5"] is None and out[3]["ma5"] is None
    assert out[4]["ma5"] == 7.0
    # ma10: 10번째부터. 1..10 평균 = 5.5
    assert out[8]["ma10"] is None
    assert out[9]["ma10"] == 5.5
    # 기존 키 유지
    assert "ma20" in out[0] and "ma60" in out[0] and "ma120" in out[0]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_candles.py::test_attach_ma_includes_5_and_10 -v`
Expected: FAIL (`KeyError: 'ma5'`)

- [ ] **Step 3: 최소 구현**

`backend/flow/candles.py` 의 `_attach_ma` 를 수정:

```python
def _attach_ma(bars: list) -> list:
    """각 봉에 5/10/20/60/120봉 단순이동평균(ma5..ma120)을 부착.
    앞 구간이 부족하면 None(프런트가 그 지점부터 선을 그림). 종가 기준."""
    closes = [b["close"] for b in bars]
    csum = [0.0]
    for c in closes:
        csum.append(csum[-1] + c)          # 누적합으로 O(n) 이동평균
    for n in (5, 10, 20, 60, 120):
        key = "ma" + str(n)
        for i, b in enumerate(bars):
            b[key] = round((csum[i + 1] - csum[i + 1 - n]) / n, 2) if i + 1 >= n else None
    return bars
```

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `.venv/bin/python -m pytest tests/test_candles.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: PASS · `30x passed`

- [ ] **Step 5: 커밋**

```bash
git add backend/flow/candles.py tests/test_candles.py
git commit -m "feat(candles): 이동평균 5·10봉 추가(토스 5MA 세트 대비)"
```

---

### Task 2: 이평선 5개 시리즈 + 토스 색 + 범례 칩 토글

**Files:**
- Modify: `backend/report/live_page.py:434-440` (MA_COLORS/maOn/maSeries), `:522` (_na 루프), `:169-177` (marow 버튼 HTML), `:48-` (CSS ma-btn 칩)
- Test: `tests/test_live_page_js.py` (템플릿 존재 + 실행 스모크)

**Interfaces:**
- Consumes: Task 1의 `c.ma5,c.ma10`.
- Produces: `MA_COLORS`(5키), `maOn`(5키, 전부 true), `.ma-btn[data-ma=5|10]` 버튼.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_live_page_js.py` 하단에 추가:

```python
def test_template_has_5ma_buttons():
    from backend.report.live_page import render_live_page
    html = render_live_page("000660", "SK하이닉스", "live")
    assert 'data-ma="5"' in html and 'data-ma="10"' in html
    assert 'data-ma="20"' in html and 'data-ma="120"' in html
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py::test_template_has_5ma_buttons -v`
Expected: FAIL (`data-ma="5"` 없음)

- [ ] **Step 3: HTML 버튼 교체** — `live_page.py:170-174` 의 `.marow` 안 버튼들을 교체:

```html
    <span class="ma-lb">이평선</span>
    <button class="ma-btn on" data-ma="5">5</button>
    <button class="ma-btn on" data-ma="10">10</button>
    <button class="ma-btn on" data-ma="20">20</button>
    <button class="ma-btn on" data-ma="60">60</button>
    <button class="ma-btn on" data-ma="120">120</button>
    <span class="ma-hint">봉 이동평균 · 켜고 끄기</span>
```

- [ ] **Step 4: JS 시리즈/색/기본값 교체** — `live_page.py:434-437`:

```javascript
const MA_COLORS={5:'#9aa0a6',10:'#ec4899',20:'#f59e0b',60:'#22c55e',120:'#3b82f6'};
let maOn={5:true,10:true,20:true,60:true,120:true};
let maSeries={};
if(pchart.addLineSeries){[5,10,20,60,120].forEach(function(n){
  maSeries[n]=pchart.addLineSeries({color:MA_COLORS[n],lineWidth:1.5,
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,visible:maOn[n]});
});}
```

- [ ] **Step 5: loadCandles _na 루프 확장** — `live_page.py:522` 의 `[20,60,120].forEach` 를 `[5,10,20,60,120].forEach` 로 교체(그 블록 내부는 그대로).

- [ ] **Step 6: 범례 칩 색 점 CSS + JS** — `live_page.py:48` 근처 `/* 이평선(이동평균) 토글 줄 */` 아래 CSS에 추가:

```css
.ma-btn{position:relative}
.ma-btn::before{content:'';display:inline-block;width:8px;height:8px;border-radius:2px;
  background:var(--dot,transparent);margin-right:5px;vertical-align:middle}
```

그리고 시리즈 생성 직후(Step 4 블록 다음 줄)에 각 버튼 점 색 주입:

```javascript
document.querySelectorAll('.ma-btn[data-ma]').forEach(function(b){
  b.style.setProperty('--dot', MA_COLORS[+b.getAttribute('data-ma')]||'transparent');});
```

- [ ] **Step 7: 통과 + 실행 스모크 + 전체 회귀**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: PASS(실행 스모크 `RENDER OK` 포함) · 전체 passed

- [ ] **Step 8: CDP 스크린샷 확인(범례 5칩·5선)**

Run: `.venv/bin/python /private/tmp/claude-501/-Users-toyunity-dev-stock-master/9abbdd3c-9847-4c60-9f73-e171dda5dbc6/scratchpad/cdp_enh.py /tmp/toss_ma.png light`
확인: 상단 범례에 5·10·20·60·120 색점, 일봉에서 5개 선. (레퍼런스와 색 대조)

- [ ] **Step 9: 커밋**

```bash
git add backend/report/live_page.py tests/test_live_page_js.py
git commit -m "feat(live): 이평선 5·10·20·60·120 + 토스 색 범례 칩"
```

---

### Task 3: 최고/최저 자동 주석(전체 기간 고정 · 현재가 대비 %)

**Files:**
- Modify: `backend/report/live_page.py` (loadCandles 내부, `pseries.setData(_mapped)` 직후 ~ `:512` 아래에 마커 계산 추가)
- Test: `tests/test_live_page_js.py` (템플릿 존재 + 스모크)

**Interfaces:**
- Consumes: `_mapped`(time 필드=toTs 결과), `d.candles`(원본 `t`), 마지막 종가.
- Produces: 차트 위 최고/최저 마커(`pseries.setMarkers`, 가드됨).

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_live_page_js.py` 하단:

```python
def test_template_has_extreme_markers_code():
    from backend.report.live_page import render_live_page
    html = render_live_page("000660", "SK하이닉스", "live")
    assert "setMarkers" in html and "aboveBar" in html and "belowBar" in html
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py::test_template_has_extreme_markers_code -v`
Expected: FAIL

- [ ] **Step 3: 마커 계산 함수 + 호출 추가** — `live_page.py` 의 `pseries.setData(_mapped);`(현 :512) 바로 다음 줄에 삽입:

```javascript
    // 최고/최저 자동 주석(전체 로드 기간 고정 · 현재가=마지막 종가 대비 %). 하니스 가드.
    if(pseries.setMarkers){
      var _hi=-Infinity,_lo=Infinity,_hiI=0,_loI=0;
      for(var _i=0;_i<_mapped.length;_i++){
        if(_mapped[_i].high>_hi){_hi=_mapped[_i].high;_hiI=_i;}
        if(_mapped[_i].low<_lo){_lo=_mapped[_i].low;_loI=_i;}
      }
      var _cur=_mapped.length?_mapped[_mapped.length-1].close:0;
      var _pct=function(v){var p=_cur?((v-_cur)/_cur*100):0;return (p>=0?'+':'')+p.toFixed(1)+'%';};
      var _dt=function(idx){var t=(d.candles[idx]||{}).t||'';return t.length>=10?t.slice(5).replace('-','.'):t;};
      try{pseries.setMarkers([
        {time:_mapped[_hiI].time,position:'aboveBar',color:'#e0322c',shape:'arrowDown',
         text:won(_hi)+' ('+_dt(_hiI)+') '+_pct(_hi)},
        {time:_mapped[_loI].time,position:'belowBar',color:'#1565c0',shape:'arrowUp',
         text:won(_lo)+' ('+_dt(_loI)+') '+_pct(_lo)}
      ].sort(function(a,b){return a.time<b.time?-1:1}));}catch(e){}
    }
```

(주의: `setMarkers`는 time 오름차순 정렬 필요 → `.sort` 포함. `won`은 기존 헬퍼.)

- [ ] **Step 4: 통과 + 실행 스모크(가드로 죽지 않음) + 회귀**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: PASS(`RENDER OK`) · 전체 passed

- [ ] **Step 5: CDP 스크린샷(일봉에서 최고/최저 라벨)**

Run: `.venv/bin/python /private/tmp/claude-501/-Users-toyunity-dev-stock-master/9abbdd3c-9847-4c60-9f73-e171dda5dbc6/scratchpad/cdp_enh.py /tmp/toss_ext.png light` (일봉 전환 필요 시 스크립트에 `data-tf=1d` 클릭 추가). 확인: 최고=적/최저=청 라벨, `가격(MM.DD) ±%`.

- [ ] **Step 6: 커밋**

```bash
git add backend/report/live_page.py tests/test_live_page_js.py
git commit -m "feat(live): 최고/최저 자동 주석(현재가 대비 %, toTs time 재사용)"
```

---

### Task 4: 현재가 축 태그 + 헤더 등락(금액·%) 강조

**Files:**
- Modify: `backend/report/live_page.py:150-152`(hero HTML), `:465-466`(nowLine), `:742-744`(render price), CSS(`:113` 근처)
- Test: `tests/test_live_page_js.py`

**Interfaces:**
- Consumes: `M.price,M.change,M.rate,M.sign`(스냅샷 market).
- Produces: `#chg` 요소(등락), nowLine `axisLabelVisible:true`.

- [ ] **Step 1: 실패 테스트** — 하단에 추가:

```python
def test_hero_has_change_element():
    from backend.report.live_page import render_live_page
    html = render_live_page("000660", "SK하이닉스", "live")
    assert 'id="chg"' in html
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py::test_hero_has_change_element -v`
Expected: FAIL

- [ ] **Step 3: hero에 등락 요소 추가** — `live_page.py:150` `<div class="price" id="price">–</div>` 다음 줄에 삽입:

```html
  <div class="chg flat" id="chg"></div>
```

- [ ] **Step 4: CSS 추가** — `:113` `.glance{...}` 근처에:

```css
.price{font-size:30px;font-weight:800;letter-spacing:-.5px}
.chg{font-size:14px;font-weight:700;margin:1px 0 2px}
.chg.up{color:var(--up)}.chg.down{color:var(--down)}.chg.flat{color:var(--text-2)}
```

- [ ] **Step 5: render() price/등락 분리** — `live_page.py:743` 한 줄을 아래로 교체:

```javascript
    p.textContent=won(M.price);
    p.className='price '+M.sign;
    var cg=document.getElementById('chg');
    cg.textContent=(M.change!=null?sgn[M.sign]+' '+won(Math.abs(M.change)):'')
      +(M.rate!=null?'  '+(M.rate>0?'+':(M.rate<0?'-':''))+Math.abs(M.rate).toFixed(2)+'%':'');
    cg.className='chg '+M.sign;
```

(주의: 기존 `#price` 에 있던 rate 표기를 `#chg` 로 이동. 만약 `#price` 텍스트에 `%` 를 기대하는 테스트가 있으면 `#chg` 검사로 갱신.)

- [ ] **Step 6: nowLine 축 라벨 on** — `live_page.py:465` 의 `axisLabelVisible:false` → `axisLabelVisible:true` (색은 기존 updateLiveCandle에서 틱마다 갱신).

- [ ] **Step 7: 통과 + 회귀**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -q && .venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: PASS · 전체 passed (실패 시 Step 5 주의사항대로 기존 테스트 갱신)

- [ ] **Step 8: CDP 스크린샷(헤더 등락 + 우측 축 현재가 태그)**

Run: `.venv/bin/python /private/tmp/claude-501/-Users-toyunity-dev-stock-master/9abbdd3c-9847-4c60-9f73-e171dda5dbc6/scratchpad/cdp_enh.py /tmp/toss_price.png light`
확인: 큰 현재가 + 아래 컬러 등락(▲금액 %), 우측 축에 현재가 태그.

- [ ] **Step 9: 커밋**

```bash
git add backend/report/live_page.py tests/test_live_page_js.py
git commit -m "feat(live): 현재가 축 태그 + 헤더 등락(금액·%) 강조"
```

---

### Task 5: 거래량 라벨/현재값 + 팔레트·기본값 정리 + 스크린샷 수렴

**Files:**
- Modify: `backend/report/live_page.py`(chartwrap에 vol 라벨, loadCandles에서 값 세팅, 필요 시 캔들 색 톤)
- Test: `tests/test_live_page_js.py`

**Interfaces:**
- Consumes: `d.candles[*].vol`.
- Produces: `#vol-lb` 요소(거래량 라벨/값).

- [ ] **Step 1: 실패 테스트**

```python
def test_chart_has_volume_label():
    from backend.report.live_page import render_live_page
    html = render_live_page("000660", "SK하이닉스", "live")
    assert 'id="vol-lb"' in html
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py::test_chart_has_volume_label -v`
Expected: FAIL

- [ ] **Step 3: 거래량 라벨 요소 + CSS** — `live_page.py:179` `.chartwrap` 을 아래로 교체:

```html
  <div class="chartwrap"><div id="pchart"></div>
    <div class="vol-lb" id="vol-lb"></div>
    <div class="stall" id="pstall"></div></div>
```

CSS(`.chartwrap` 규칙 근처, `.chartwrap`에 `position:relative` 없으면 추가):

```css
.chartwrap{position:relative}
.vol-lb{position:absolute;left:8px;bottom:26px;font-size:11px;font-weight:700;
  color:var(--text-3);pointer-events:none}
```

- [ ] **Step 4: loadCandles에서 거래량 값 세팅** — `live_page.py:518`(volSeries.setData 블록) 다음에 추가:

```javascript
    var _lv=d.candles.length?(d.candles[d.candles.length-1].vol||0):0;
    var _vlb=document.getElementById('vol-lb');
    if(_vlb)_vlb.textContent='거래량 '+(tf==='1d'?'—':num(_lv)+'주');
```

(일봉은 vol이 0이라 `—`; 분봉에서 최근 봉 거래량 표시. `num`은 기존 헬퍼.)

- [ ] **Step 5: 통과 + 실행 스모크 + 회귀**

Run: `.venv/bin/python -m pytest tests/test_live_page_js.py -q && .venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: PASS(`RENDER OK`) · 전체 passed

- [ ] **Step 6: 라이트/다크 스크린샷 수렴** — 레퍼런스(IMG_3529)와 대조하며 색/간격 미세조정:

```bash
CDP=/private/tmp/claude-501/-Users-toyunity-dev-stock-master/9abbdd3c-9847-4c60-9f73-e171dda5dbc6/scratchpad/cdp_enh.py
.venv/bin/python "$CDP" /tmp/toss_final_light.png light
.venv/bin/python "$CDP" /tmp/toss_final_dark.png dark
```
확인: 헤더·5MA 범례·최고/최저·현재가 태그·거래량 라벨이 아이폰 폭(390)에서 안 깨지고 토스 룩에 근접. 어긋난 부분은 이 태스크에서 CSS로 조정 후 재캡처.

- [ ] **Step 7: 커밋**

```bash
git add backend/report/live_page.py tests/test_live_page_js.py
git commit -m "feat(live): 거래량 라벨 + 토스 룩 스크린샷 수렴(Phase 1 완료)"
```

---

## 어드바이저 오버레이(기본 off) 메모

Phase 1에서 별도 작업 불필요 — 대부분 이미 클린 기본값이다: 공매도=토글 off(`ssOn=false`), 크로스헤어 OHLC=호버 전용, 카운트다운=소형 텍스트, 절대선/감시선=사용자 설정분, 실시간봉=투명 갱신. 토스 시각 요소를 얹으면 기본 화면은 자동으로 깔끔해진다. 명시적 "지표 묶음 토글" UI는 Phase 2(⚙/🔧 메뉴)에서.

## Self-Review

- **Spec 커버리지:** 헤더(T4)·5MA(T1·T2)·최고/최저(T3)·현재가 태그(T4)·거래량(T5)·오버레이 기본off(메모) 모두 태스크로 매핑. 틱/배당락/멀티페인/일·분 드롭다운은 스펙상 Phase 2 — 의도적 제외.
- **플레이스홀더:** 없음(모든 코드 단계에 실제 코드). CDP 스크립트 경로는 세션 scratchpad 실경로 사용.
- **타입 일관성:** `_attach_ma` ma5/ma10(T1) → `maSeries`/`_na` 5키(T2) → `_mapped.time`/`d.candles.t`(T3) → `#chg`/`sgn`/`won`(T4) → `#vol-lb`/`num`(T5). 명칭 일치 확인.
