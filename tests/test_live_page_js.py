"""라이브 페이지 렌더 JS 실행 스모크 — 실제 스냅샷으로 render()를 구동한다.

문자열 존재 검사로는 JS ReferenceError(렌더가 중간에 죽어 이후 패널 전부 미표시 —
2026-07-10 'prsn is not defined' 실사고)를 못 잡는다. node가 있으면 실행까지 검증.
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
const snap = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts[1];  // [0]=차트 라이브러리, [1]=페이지 로직
const els = {};
global.document = {
  getElementById: id => els[id] || (els[id] = {textContent:'', innerHTML:'', className:'', style:{}}),
  querySelectorAll: () => [],
};
global.LightweightCharts = { createChart: () => ({
  addBaselineSeries: () => ({setData(){}}), addCandlestickSeries: () => ({setData(){}}),
  timeScale: () => ({fitContent(){}}), applyOptions(){},
})};
global.EventSource = function(){ return {}; };
global.fetch = async () => ({ok:false, json:async()=>({})});
global.setInterval = () => {};
eval(code);
render(snap);
console.log('RENDER OK');
for (const id of ['pgm-qty','daily','detail','tape','est-frgn','est-hist'])
  console.log(id + '=' + String((els[id]||{}).textContent || (els[id]||{}).innerHTML).length);
"""


def _full_snapshot():
    from backend.flow.models import FlowState
    s = FlowState("000660", "SK하이닉스", "live")
    s.apply_tick({"t": "13:00:00", "price": 2254000, "sign": "up",
                  "change": 68000, "rate": 3.11, "vol": 10, "acml_vol": 4000000,
                  "acml_value": 9000000000000, "strength": 88.5, "side": "buy"})
    s.apply_program({"t": "13:00:00", "sell_qty": 1, "sell_value": 1,
                     "buy_qty": 1, "buy_value": 1,
                     "net_qty": -534000, "net_value": -1200000000000})
    s.set_estimate([{"asof": "09:30", "frgn": -98000, "orgn": 0, "sum": -98000},
                    {"asof": "11:20", "frgn": -812000, "orgn": 135000,
                     "sum": -677000}])
    s.set_estimate_detail({"asof": "13:00", "etc_qty": 43000, "etc_value": 1,
                           "rows": [{"name": "투신", "qty": 82000, "value": 2}]})
    s.set_daily([{"date": "2026-07-09", "prsn": -179724, "frgn": -209485,
                  "orgn": 404365, "close": 2186000}])
    s.set_detail({"date": "2026-07-09",
                  "rows": [{"name": "연기금", "qty": 48907, "value": 113357000000}]})
    s.set_status(connected=True, note="")
    return s.snapshot()


@needs_node
def test_render_js_executes_and_fills_all_panels(tmp_path):
    from backend.report.live_page import render_live_page
    html_p = tmp_path / "live.html"
    snap_p = tmp_path / "snap.json"
    js_p = tmp_path / "smoke.js"
    html_p.write_text(render_live_page("000660", "SK하이닉스", "live"),
                      encoding="utf-8")
    snap_p.write_text(json.dumps(_full_snapshot()), encoding="utf-8")
    js_p.write_text(_HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(js_p), str(html_p), str(snap_p)],
                       capture_output=True, text=True, timeout=30)
    assert "RENDER OK" in r.stdout, f"렌더 JS 예외: {r.stdout}\n{r.stderr}"
    # 마지막 패널들(프로그램·일별·세부·체결)까지 실제로 채워졌는지
    filled = dict(line.split("=") for line in r.stdout.strip().splitlines()[1:])
    for key in ("pgm-qty", "daily", "detail", "tape", "est-hist"):
        assert int(filled[key]) > 0, f"{key} 패널이 비어 있음"
