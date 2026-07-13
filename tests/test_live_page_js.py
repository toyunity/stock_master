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
for (const id of ['pgm-qty','daily','detail','tape','est-frgn','est-hist','sb-qty','sb-hist','sb-sig'])
  console.log('LEN:' + id + '=' + String((els[id]||{}).textContent || (els[id]||{}).innerHTML).length);
for (const id of ['est-fresh','sb-fresh','sb-note','sb-sig'])
  console.log('TXT:' + id + '=' + String((els[id]||{}).textContent));
console.log('TXT:daily-html=' + String((els['daily']||{}).innerHTML));
// 차트 시간축: 라이브러리는 epoch을 UTC로 포맷 → toTs 결과의 UTC 시:분이
// 원본 문자열과 같아야 라벨이 KST로 보인다(2026-07-13 실사고: 09:32→00:32)
const tzd = new Date(toTs('09:32:00')*1000);
console.log('TXT:tots-utc=' + tzd.getUTCHours() + ':' + tzd.getUTCMinutes());
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
    s.set_short({"rows": [
        {"date": "2026-07-09", "qty": 14420269, "value": 31522708034000,
         "chg": None, "src": "kofia"},
        {"date": "2026-07-10", "qty": 14140221, "value": 30825681780000,
         "chg": -280048, "src": "kofia"}],
        "asof": "2026-07-10", "source": "kofia",
        "updated": "2026-07-13T09:00:00"})
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
    filled, texts = _parse_harness(r.stdout)
    # 마지막 패널들(프로그램·일별·세부·체결·대차)까지 실제로 채워졌는지
    for key in ("pgm-qty", "daily", "detail", "tape", "est-hist",
                "sb-qty", "sb-hist", "sb-sig"):
        assert int(filled[key]) > 0, f"{key} 패널이 비어 있음"
    # 주가 ▲3.11% × 대차 −280,048주 → '건강한 상승 (숏 이탈)' 4분면
    assert "건강한 상승" in texts["sb-sig"]
    assert "금융투자협회" in texts["sb-fresh"]  # 출처 표기
    # 일별 확정 테이블에 대차잔고 컬럼이 날짜 조인으로 들어갔는지(07-09 행)
    assert "대차잔고" in texts["daily-html"]
    assert "14,420,269" in texts["daily-html"] or "14420269" in texts["daily-html"]
    # 시간축 라벨이 서버(KST) 시각 그대로 보이는지 — UTC 렌더 사고 재발 방지
    assert texts["tots-utc"] == "9:32"


def _parse_harness(stdout: str):
    filled, texts = {}, {}
    for line in stdout.strip().splitlines():
        if line.startswith("LEN:"):
            k, v = line[4:].split("=", 1)
            filled[k] = v
        elif line.startswith("TXT:"):
            k, v = line[4:].split("=", 1)
            texts[k] = v
    return filled, texts


@needs_node
def test_render_js_empty_day_shows_waiting_not_stale(tmp_path):
    # 실사고(2026-07-13): 날짜가 바뀌어 서버가 당일 상태를 비웠는데도 브라우저가
    # 이전 DOM을 유지하면 전일 잠정이 계속 보인다 — 빈 rows에서 명시적 대기 표시.
    import json as _json
    from backend.flow.models import FlowState
    from backend.report.live_page import render_live_page
    snap = FlowState("000660", "SK하이닉스", "live").snapshot()
    html_p, snap_p, js_p = (tmp_path / "live.html", tmp_path / "snap.json",
                            tmp_path / "smoke.js")
    html_p.write_text(render_live_page("000660", "SK하이닉스", "live"),
                      encoding="utf-8")
    snap_p.write_text(_json.dumps(snap), encoding="utf-8")
    js_p.write_text(_HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(js_p), str(html_p), str(snap_p)],
                       capture_output=True, text=True, timeout=30)
    assert "RENDER OK" in r.stdout, f"렌더 JS 예외: {r.stdout}\n{r.stderr}"
    _, texts = _parse_harness(r.stdout)
    assert "발표 전" in texts["est-fresh"]      # 전일 잠정 잔존 대신 대기 문구
    assert "데이터 없음" in texts["sb-note"]    # 대차잔고 실패 시에도 화면 유지
