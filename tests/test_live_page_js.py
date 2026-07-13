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
global.__lines = [];  // createPriceLine 기록 — 감시선 렌더 검증(P1-8)
global.LightweightCharts = { createChart: () => ({
  addBaselineSeries: () => ({setData(){}}),
  addCandlestickSeries: () => ({setData(){}, createPriceLine(o){global.__lines.push(o);}}),
  timeScale: () => ({fitContent(){}}), applyOptions(){},
})};
global.EventSource = function(){ return {}; };
global.fetch = async () => ({ok:false, json:async()=>({})});
global.setInterval = () => {};
eval(code);
render(snap);
console.log('RENDER OK');
for (const id of ['pgm-qty','daily','detail','tape','est-frgn','est-hist','sb-qty','sb-hist','sb-sig',
                  'adr-usd','ss-hist','cr-hist'])
  console.log('LEN:' + id + '=' + String((els[id]||{}).textContent || (els[id]||{}).innerHTML).length);
for (const id of ['est-fresh','sb-fresh','sb-note','sb-sig','mstate','pgm-fresh',
                  'adr-sig','adr-fresh','ss-fresh','cr-fresh','cr-sig','walert','pstall','cstall'])
  console.log('TXT:' + id + '=' + String((els[id]||{}).textContent));
console.log('TXT:pstall-class=' + String((els['pstall']||{}).className));
console.log('TXT:watch-lines=' + global.__lines.map(l=>l.title).join(','));
console.log('TXT:daily-html=' + String((els['daily']||{}).innerHTML));
console.log('TXT:sb-hist-html=' + String((els['sb-hist']||{}).innerHTML));
// 차트 시간축: 라이브러리는 epoch을 UTC로 포맷 → toTs 결과의 UTC 시:분이
// 원본 문자열과 같아야 라벨이 KST로 보인다(2026-07-13 실사고: 09:32→00:32).
// toTs는 이제 서버 KST 기준일(KDATE, render가 설정)만 쓴다 — 로컬 시계 불개입.
const tzd = new Date(toTs('09:32:00')*1000);
console.log('TXT:tots-utc=' + tzd.getUTCHours() + ':' + tzd.getUTCMinutes());
if (process.argv[4]) {  // 두 번째 스냅샷 — 연속 렌더 동작(감시선 교차 등) 검증
  render(JSON.parse(fs.readFileSync(process.argv[4], 'utf8')));
  console.log('TXT:walert2=' + String((els['walert']||{}).textContent));
  console.log('TXT:pgm-fresh2=' + String((els['pgm-fresh']||{}).textContent));
}
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
    s.set_adr({"sym": "SKHYV", "usd": 168.01, "base_usd": 149.0, "fx": 1505.2,
               "ratio": 10.0, "us_open": False, "src": "kis",
               "fetched": "13:00:05"})
    s.set_credit({"rows": [
        {"date": "2026-07-09", "qty": 3246469, "ratio": 0.45, "new": 0,
         "rdmp": 0, "close": 2140000, "value": 3246469 * 2140000, "chg": None},
        {"date": "2026-07-10", "qty": 3296400, "ratio": 0.45, "new": 635725,
         "rdmp": 585894, "close": 2076000, "value": 3296400 * 2076000,
         "chg": 49931}], "asof": "2026-07-10"})
    s.set_shortsale({"rows": [
        {"date": "2026-07-09", "qty": 63290, "vol": 6261504, "ratio": 1.01,
         "value": 1, "close": 2186000},
        {"date": "2026-07-10", "qty": 254632, "vol": 4827239, "ratio": 5.27,
         "value": 564882324000, "close": 2180000}], "asof": "2026-07-10"})
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
    # 마지막 패널들(프로그램·일별·세부·체결·대차·ADR·공매도·신용)까지 실제로 채워졌는지
    for key in ("pgm-qty", "daily", "detail", "tape", "est-hist",
                "sb-qty", "sb-hist", "sb-sig", "adr-usd", "ss-hist", "cr-hist"):
        assert int(filled[key]) > 0, f"{key} 패널이 비어 있음"
    # 주가 ▲3.11% × 대차 −280,048주 → '건강한 상승 (숏 이탈)' 4분면
    assert "건강한 상승" in texts["sb-sig"]
    assert "금융투자협회" in texts["sb-fresh"]  # 출처 표기
    # 일별 확정 테이블에 대차잔고 컬럼이 날짜 조인으로 들어갔는지(07-09 행)
    assert "대차잔고" in texts["daily-html"]
    assert "14,420,269" in texts["daily-html"] or "14420269" in texts["daily-html"]
    # 시간축 라벨이 서버(KST) 시각 그대로 보이는지 — UTC 렌더 사고 재발 방지
    assert texts["tots-utc"] == "9:32"
    # 시장 상태 배지(P1-7) — 라벨 존재(내용은 실행 시각에 따라 다름)
    assert texts["mstate"] and texts["mstate"] != "상태 확인 중"
    # 프로그램 패널 기준시각(P0-3) — 마지막 포인트의 거래소 타임스탬프
    assert "기준 13:00" in texts["pgm-fresh"]
    # 수신 정지 아님 → 오버레이 꺼짐(P0-2)
    assert texts["pstall-class"] == "stall"
    # ADR 괴리율(P1-4): 168.01×10×1505.2=2,528,887 vs 2,254,000 → +12.20%
    assert "+12.20%" in texts["adr-sig"] and "프리미엄" in texts["adr-sig"]
    assert "전일 종가 기준" in texts["adr-fresh"]  # 미국 장마감 라벨
    # 공매도(P1-6): T+1 기준일 라벨 + 대차잔고 옆 비교
    assert "기준일: 2026-07-10" in texts["ss-fresh"]
    # 신용잔고(P1-5): T+2 라벨 + 판정
    assert "기준일: 2026-07-10" in texts["cr-fresh"] and "T+2" in texts["cr-fresh"]
    assert texts["cr-sig"].startswith("판정:")
    # 감시선(P1-8): 설정 기본값 2개가 라벨 달린 수평선으로 렌더
    assert texts["watch-lines"] == "절대선,예약매도"


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


def _run_harness(tmp_path, snap, snap2=None):
    import json as _json
    from backend.report.live_page import render_live_page
    html_p, snap_p, js_p = (tmp_path / "live.html", tmp_path / "snap.json",
                            tmp_path / "smoke.js")
    html_p.write_text(render_live_page("000660", "SK하이닉스", "live"),
                      encoding="utf-8")
    snap_p.write_text(_json.dumps(snap), encoding="utf-8")
    js_p.write_text(_HARNESS, encoding="utf-8")
    args = ["node", str(js_p), str(html_p), str(snap_p)]
    if snap2 is not None:
        snap2_p = tmp_path / "snap2.json"
        snap2_p.write_text(_json.dumps(snap2), encoding="utf-8")
        args.append(str(snap2_p))
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    assert "RENDER OK" in r.stdout, f"렌더 JS 예외: {r.stdout}\n{r.stderr}"
    return _parse_harness(r.stdout)


@needs_node
def test_render_js_stall_overlay_on_halt(tmp_path):
    # 정규장 수신 정지(서버 판정) → 두 차트에 오버레이 + 마지막 수신 시각(P0-2)
    snap = _full_snapshot()
    snap["market_state"] = {"state": "halt", "label": "수신 정지 — VI/CB 의심",
                            "tone": "warn"}
    snap["stall"] = {"stalled": True, "since": "13:00:00", "sec": 120}
    _, texts = _run_harness(tmp_path, snap)
    assert texts["pstall-class"] == "stall on"
    for k in ("pstall", "cstall"):
        assert "수신 정지 (13:00:00 이후)" in texts[k]
    assert "수신 정지" in texts["mstate"]


@needs_node
def test_render_js_watch_line_alert_fires_once(tmp_path):
    # 감시선 1,853,000 ±0.5% 진입 → 인페이지 알림 문구(브라우저 알림·사운드는
    # node 환경에 없어 가드로 무시됨) — 렌더가 죽지 않아야 한다(P1-8)
    snap = _full_snapshot()
    snap["market"]["price"] = 1_858_000  # |1858000-1853000|/1853000 = 0.27%
    _, texts = _run_harness(tmp_path, snap)
    assert "절대선" in texts["walert"] and "1,853,000" in texts["walert"]


@needs_node
def test_render_js_watch_alert_on_gap_through_crossing(tmp_path):
    # 스냅샷(1초) 사이 급변으로 밴드를 건너뛴 경우에도 부호 교차로 알림(리뷰 확정)
    snap1 = _full_snapshot()
    snap1["market"]["price"] = 1_880_000   # 감시선 위 1.46% — 밴드 밖
    snap2 = dict(snap1, market=dict(snap1["market"], price=1_830_000))  # 아래로 점프
    _, texts = _run_harness(tmp_path, snap1, snap2)
    assert "절대선" not in texts["walert"]        # 첫 스냅샷은 미발동
    assert "절대선" in texts["walert2"]           # 교차 감지 → 발동


@needs_node
def test_render_js_program_chart_cleared_on_empty_points(tmp_path):
    # 자정 리셋 후(포인트 비움) 열려 있는 탭에서 전일 곡선·기준시각이 남지 않는다
    snap1 = _full_snapshot()
    snap2 = dict(snap1, program={"net_qty": 0, "net_value": 0, "day_min": None,
                                 "day_max": None, "points": []})
    _, texts = _run_harness(tmp_path, snap1, snap2)
    assert "기준 13:00" in texts["pgm-fresh"]      # 첫 렌더: 곡선 표시
    assert "데이터 대기" in texts["pgm-fresh2"]    # 리셋 후: 대기 표시로 교체


@needs_node
def test_render_js_mixed_sources_labeled(tmp_path):
    # 협회·예탁원 혼합 시(집계 범위가 달라 절대치가 다름) 행별 출처를 표기하고
    # 헤더에 혼합 경고를 띄운다 — 리뷰 확정 결함의 회귀 방지
    import json as _json
    from backend.flow.models import FlowState
    from backend.report.live_page import render_live_page
    s = FlowState("000660", "SK하이닉스", "live")
    s.set_short({"rows": [
        {"date": "2026-07-09", "qty": 14420269, "value": 1, "chg": None,
         "src": "kofia"},
        {"date": "2026-07-10", "qty": 11121198, "value": 1, "chg": None,
         "src": "seibro"}],
        "asof": "2026-07-10", "source": "seibro", "updated": "t"})
    snap = s.snapshot()
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
    assert "혼합" in texts["sb-fresh"]           # 헤더 경고
    assert "출처" in texts["sb-hist-html"]       # 출처 열
    assert "협회" in texts["sb-hist-html"] and "예탁원" in texts["sb-hist-html"]
