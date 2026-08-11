"""차트 로딩 표시 — 첫 페인트부터 '불러오는 중'을 덮고, 다 그리면 걷는다.

배경(2026-08-11 실측): /api/candles는 웜 3.8초·콜드 8.2초가 걸린다(KRX 전용 종목은
통합 조회가 빈 값이라 J로 되묻느라 두 배). 그동안 차트 영역은 라이브러리 워터마크만
있는 빈 상자라, 마스터가 '차트가 안 나온다'고 두 번 제보했다 — 실제로는 로딩 중이었다.
헤더의 작은 글씨(`pc-fresh`) 하나로는 신호가 안 된다.

`pstall`(수신 정지)을 재사용하면 안 된다 — render()가 SSE 1초마다
`el.className='stall'+(halted?' on':'')`로 덮어써 로딩 표시가 즉시 지워진다.
"""
import json
import re
import shutil
import subprocess

import pytest

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 미설치 — JS 실행 스모크 생략")


@pytest.fixture(autouse=True)
def _isolate_watch_cache(tmp_path, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))


def _page() -> str:
    from backend.report.live_page import render_live_page
    return render_live_page("000660", "SK하이닉스", "live")


def _chart_area(html: str) -> str:
    """가격 차트 래퍼 구간만 — 거래량/다른 패널의 동명 요소에 속지 않게."""
    i = html.index('<div class="chartwrap">')
    return html[i:html.index('<div class="volwrap">', i)]


def test_로딩_오버레이가_차트_영역에_처음부터_보인다():
    m = re.search(r'<div class="([^"]*)" id="pcload">([^<]*)</div>', _chart_area(_page()))
    assert m, "차트 영역에 로딩 오버레이(#pcload)가 없다"
    assert "on" in m.group(1).split(), "첫 페인트부터 보여야 한다(JS 실행 전에도)"
    assert m.group(2).strip(), "안내 문구가 비어 있다"


# 가짜 DOM은 실제 HTML의 class를 심어 준다 — 초기 표시 상태를 그대로 관찰하려면
# getElementById가 만들어 주는 빈 엘리먼트로는 안 된다.
_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const CANDLES = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(function(s){return s.indexOf('loadCandles')>=0;});
const validIds = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));
const seed = {};
for (const m of html.matchAll(/<div class="([^"]*)" id="([^"]+)">/g)) seed[m[2]] = m[1];
const els = {};
const el = id => els[id] || (els[id] =
  {textContent:'', innerHTML:'', className:seed[id]||'', style:{}, disabled:false,
   classList:{add(){}, remove(){}, toggle(){}}, getAttribute(){return null;},
   setAttribute(){}, dataset:{}});
global.document = {
  getElementById: id => validIds.has(id) ? el(id) : null,
  querySelectorAll: () => [],
};
global.LightweightCharts = { createChart: () => ({
  addBaselineSeries: () => ({setData(){}}),
  addHistogramSeries: () => ({setData(){}, applyOptions(){}}),
  addLineSeries: () => ({setData(){}}),
  addCandlestickSeries: () => ({setData(){}, createPriceLine(){}, update(){},
                                priceToCoordinate(){return 10;}}),
  timeScale: () => ({fitContent(){}, getVisibleLogicalRange(){return null;},
                     setVisibleLogicalRange(){}, subscribeVisibleTimeRangeChange(){},
                     subscribeVisibleLogicalRangeChange(){},
                     timeToCoordinate(){return 10;}}),   // placeExt(최고/최저 라벨)가 쓴다
  applyOptions(){}, priceScale: () => ({applyOptions(){}}),
})};
global.EventSource = function(){ return {addEventListener(){}}; };
global.setInterval = () => {};
global.fetch = async (u) => (('' + u).indexOf('/api/candles/') >= 0)
  ? {ok:true, json: async () => CANDLES}
  : {ok:false, json: async () => ({})};
eval(code);
console.log('INIT:' + el('pcload').className);       // eval 직후(요청 진행 중)
(async () => {
  for (let i = 0; i < 50; i++) await new Promise(r => setImmediate(r));
  console.log('DONE:' + el('pcload').className);     // 응답 처리 후
  console.log('FRESH:' + el('pc-fresh').textContent);
  await loadCandles(false);                          // 60초 자동 갱신(조용해야 한다)
  console.log('REFRESH:' + el('pcload').className);
})();
"""


def _run_node(tmp_path, candles):
    p = tmp_path / "page.html"
    p.write_text(_page(), encoding="utf-8")
    c = tmp_path / "candles.json"
    c.write_text(json.dumps(candles), encoding="utf-8")
    h = tmp_path / "harness.js"
    h.write_text(_HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(h), str(p), str(c)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return dict(line.split(":", 1) for line in r.stdout.splitlines() if ":" in line)


_CANDLES = {"tf": "5m", "date": "2026-08-11", "candles": [
    {"t": "09:00:00", "open": 100, "high": 110, "low": 90, "close": 105, "vol": 10},
    {"t": "09:05:00", "open": 105, "high": 115, "low": 95, "close": 110, "vol": 20},
]}


@needs_node
def test_응답이_오면_오버레이를_걷는다(tmp_path):
    out = _run_node(tmp_path, _CANDLES)
    assert "on" in out["INIT"].split(), "요청 중엔 덮고 있어야 한다"
    assert "on" not in out["DONE"].split(), "다 그렸으면 걷어야 한다"
    assert "5분봉" in out["FRESH"], "정상 경로를 탔는지 확인(라벨이 갱신됐나)"


@needs_node
def test_60초_자동갱신은_차트를_덮지_않는다(tmp_path):
    # fit=false(주기 갱신)에서 오버레이가 뜨면 1분마다 화면이 깜빡인다.
    # 오버레이가 아예 없으면 이 단언은 공허하게 통과하므로 존재부터 확인한다.
    assert 'id="pcload"' in _chart_area(_page()), "차트 영역에 로딩 오버레이가 없다"
    out = _run_node(tmp_path, _CANDLES)
    assert "on" not in out["REFRESH"].split()
