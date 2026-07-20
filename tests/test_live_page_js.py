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


@pytest.fixture(autouse=True)
def _isolate_watch_cache(tmp_path, monkeypatch):
    # render_live_page가 data/cache/watch_lines.json(사용자 편집분)을 읽어 WATCH를 주입하므로,
    # 실제 캐시 상태에 의존하지 않도록 격리한다(파일 없음 → config 기본값 절대선+예약매도).
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))

_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const snap = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(function(s){return s.indexOf('loadCandles')>=0;}) || scripts[1];  // [0]=차트 라이브러리, [1]=페이지 로직
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
                  'adr-usd','ss-hist','cr-hist','sz-bars','xv-ses','mb-tbl','tm-reasons'])
  console.log('LEN:' + id + '=' + String((els[id]||{}).textContent || (els[id]||{}).innerHTML).length);
for (const id of ['est-fresh','sb-fresh','sb-note','sb-sig','mstate','pgm-fresh',
                  'sb-pill','ss-pill','cr-pill',
                  'adr-sig','adr-fresh','ss-fresh','cr-fresh','cr-sig','walert','pstall','cstall',
                  'sz-sig','sz-fresh','xv-sig','xv-fresh','mb-sig','mb-fresh',
                  'tm-headline','tm-comment','tm-fresh'])
  console.log('TXT:' + id + '=' + String((els[id]||{}).textContent));
console.log('TXT:mb-tbl-html=' + String((els['mb-tbl']||{}).innerHTML));
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
    # 세 세션 모두 규모 분포 표본을 넣는다(체결 규모 패널이 어느 세션에서도 그려지게).
    # 마지막 tick이 market.price가 되므로 13:00 tick을 마지막에 둔다.
    s.apply_tick({"t": "08:30:00", "price": 2250000, "sign": "up", "change": 1,
                  "rate": 0.1, "vol": 5, "acml_vol": 1000, "acml_value": 1,
                  "strength": 100.0, "side": "buy"})
    s.apply_tick({"t": "16:10:00", "price": 2250000, "sign": "up", "change": 1,
                  "rate": 0.1, "vol": 300, "acml_vol": 2000, "acml_value": 2,
                  "strength": 100.0, "side": "sell"})
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
    s.set_exvol({"krx": {"price": 1845000, "vol": 7951404, "pbmn": 1},
                 "nxt": {"price": 1843000, "vol": 5195600, "pbmn": 1},
                 "nxt_share_pct": 39.5,
                 "sessions": {"pre": 863404, "main": 3300000, "after": 1032196},
                 "warn": {"move_pct": -0.11, "after_share_pct": 7.85,
                          "text": "시간외 변동 미미", "tone": "flat"},
                 "asof": "16:31:13"})
    s.set_member({"sell": [
        {"name": "삼성증권", "qty": 915123, "rlim": 11.51, "foreign": False},
        {"name": "모간서울", "qty": 479029, "rlim": 6.02, "foreign": True}],
        "buy": [
        {"name": "키움증권", "qty": 825492, "rlim": 10.38, "foreign": False},
        {"name": "JP모간", "qty": 739909, "rlim": 9.31, "foreign": True}],
        "glob": {"seln": 831835, "shnu": 739909, "ntby": -91926,
                 "seln_rlim": 10.46, "shnu_rlim": 9.31},
        "asof": "16:31:13"})
    s.set_timing({"stance": "buy", "tone": "good", "headline": "🟢 매수 우호",
                  "comment": "상승추세+수급 유입 — 매수 우호, 20일선 눌림목 분할 접근",
                  "reasons": ["정배열(현재가>20일>60일>120일)", "외인·기관 3일 연속 순매수"],
                  "entry_hint": "20일선 2,180,000원 눌림목 지지 확인 시 분할",
                  "overheated": False, "confidence": 2, "asof": "13:20"})
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
                "sb-qty", "sb-hist", "sb-sig", "adr-usd", "ss-hist", "cr-hist",
                "sz-bars"):
        assert int(filled[key]) > 0, f"{key} 패널이 비어 있음"
    # 체결 규모 분포(주체 추정): 표본 부족 시 판정 보류 + 추정 라벨
    assert "보류" in texts["sz-sig"] or "판정:" in texts["sz-sig"]
    assert "추정" in texts["sz-fresh"] or "표본" in texts["sz-fresh"]
    # 거래소별 거래량: 세션 표 + 판정 문구
    assert "판정:" in texts["xv-sig"] and "16:31:13" in texts["xv-fresh"]
    # 거래원: 외국계 표시 + 정규장 기준 순매도 요약
    assert "fgn" in texts["mb-tbl-html"] and "모간서울" in texts["mb-tbl-html"]
    assert "순매도 우위(추정)" in texts["mb-sig"] and "정규장 기준" in texts["mb-sig"]
    assert "추정" in texts["mb-fresh"]
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
    # 신용잔고(P1-5): 출처 문구 존재 + 판정(타이밍은 이제 cr-pill)
    assert texts["cr-fresh"]
    assert texts["cr-sig"].startswith("판정:")
    # 타이밍 알약(설계 2026-07-20) — 지연이 알약으로 명시
    assert "T+1" in texts["sb-pill"] and "7/10" in texts["sb-pill"]
    assert "T+1" in texts["ss-pill"] and "7/10" in texts["ss-pill"]
    assert "T+2" in texts["cr-pill"] and "7/10" in texts["cr-pill"]
    # 초보 1줄이 페이지에 존재
    page = html_p.read_text(encoding="utf-8")
    assert "빌려간 주식(공매도 준비 물량)" in page
    assert "빚내서 산 주식" in page and "반대매매" in page
    # 감시선(P1-8): 설정 기본값 2개가 라벨 달린 수평선으로 렌더
    # (현재가 이동 라인도 createPriceLine으로 추가되므로 부분집합으로 검사)
    assert "절대선" in texts["watch-lines"] and "예약매도" in texts["watch-lines"]
    # 매매 타이밍 패널: 판정 헤드라인·코멘트·근거가 채워짐(참고용 라벨)
    assert "매수" in texts["tm-headline"] and "확신도" in texts["tm-headline"]
    assert "수급 유입" in texts["tm-comment"]
    assert int(filled["tm-reasons"]) > 0            # 근거 목록 렌더
    assert "참고용" in texts["tm-fresh"]
    # 확정 밴드 · 태그(설계 2026-07-20)
    page = html_p.read_text(encoding="utf-8")
    assert "tag-fixed" in page and "tag-live" in page
    assert "왜 늦어요" in page
    assert "실시간 아님" in page


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


# ── SSE 재연결 복원력 하니스 ────────────────────────────────────────────
# 네이티브 EventSource 자동 재접속에만 기대면 iOS PWA 백그라운드 복귀·서버 재시작·
# half-open 정지에서 CLOSED로 죽어 복구가 안 된다(실사고: "연결 끊어지고 복구 안됨").
# 제어 가능한 EventSource 목/타이머/이벤트 리스너를 주입해 세 가지 복구 모드가
# 실제로 '새 연결'을 만드는지 계측한다. render()가 아니라 페이지 로드 경로만 구동.
_RECONNECT_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(function(s){return s.indexOf('loadCandles')>=0;}) || scripts[1];  // [0]=차트 라이브러리, [1]=페이지 로직

let now = 1000000;
Date.now = () => now;     // 제어 가능한 시계(백오프·하트비트 판정용)

const els = {};
const listeners = {};
const addL = (ev, fn) => (listeners[ev] = listeners[ev] || []).push(fn);
const fire = ev => (listeners[ev] || []).slice().forEach(fn => fn());
global.document = {
  hidden: false,
  getElementById: id => els[id] || (els[id] = {textContent:'', innerHTML:'', className:'', style:{}}),
  querySelectorAll: () => [],
  addEventListener: (ev, fn) => addL(ev, fn),
};
global.window = { addEventListener: (ev, fn) => addL(ev, fn) };

let timers = [];
global.setTimeout = (fn, ms) => { const t = {fn, at: now + (ms||0)}; timers.push(t); return t; };
global.clearTimeout = t => { timers = timers.filter(x => x !== t); };
const flushDue = () => { const due = timers.filter(t => t.at <= now);
  timers = timers.filter(t => t.at > now); due.forEach(t => t.fn()); };

let intervals = [];
global.setInterval = (fn, ms) => { const iv = {fn, ms}; intervals.push(iv); return iv; };
// 워치독 발화 — 서브10초 인터벌을 모두 실행(SSE 워치독 + REST 폴러 공존 대응).
// 폴러(pollOB 등)는 하니스에서 fetch 실패로 즉시 return하므로 무해, 워치독만 재접속시킨다.
const runWatchdog = () => { intervals.filter(i => i.ms < 10000).forEach(iv => iv.fn()); };

let esInstances = [];
function MockES(url){ this.url = url; this.readyState = 0;
  this.onopen = null; this.onmessage = null; this.onerror = null; esInstances.push(this); }
MockES.CONNECTING = 0; MockES.OPEN = 1; MockES.CLOSED = 2;
MockES.prototype.close = function(){ this.readyState = 2; };
global.EventSource = MockES;

global.LightweightCharts = { createChart: () => ({
  addBaselineSeries: () => ({setData(){}}),
  addCandlestickSeries: () => ({setData(){}, createPriceLine(){}}),
  timeScale: () => ({fitContent(){}}), applyOptions(){},
})};
global.location = { href: '' };
// 재접속 전 auth-check는 200(세션 유효) — 재접속이 정상 진행되어야. 그 외 fetch는 실패 응답.
global.fetch = async (u) => (String(u).indexOf('/api/auth/check') >= 0)
  ? {status: 200, ok: true, json: async () => ({})}
  : {ok: false, status: 500, json: async () => ({})};

eval(code);

const last = () => esInstances[esInstances.length - 1];
const open = es => { es.readyState = MockES.OPEN; if (es.onopen) es.onopen(); };
const flush = () => new Promise(r => setImmediate(r));  // authGuard fetch 마이크로태스크 배수

(async () => {
  console.log('N_init=' + esInstances.length);            // 로드 직후 최초 연결

  // (1) CLOSED 후 onerror(네이티브가 포기) → (auth 200) → 백오프 타이머 → 새 연결
  open(esInstances[0]);
  const e0 = last(); e0.readyState = MockES.CLOSED; if (e0.onerror) e0.onerror();
  await flush(); await flush();
  now += 60000; flushDue();
  await flush();
  console.log('N_after_closed=' + esInstances.length);

  // (2) 화면 복귀(visibilitychange) — 죽어 있으면 즉시 재연결(iOS PWA 잠금 복귀)
  const e1 = last(); open(e1); e1.readyState = MockES.CLOSED;
  document.hidden = false; fire('visibilitychange');
  await flush(); await flush();
  console.log('N_after_visible=' + esInstances.length);

  // (3) half-open 정지(오류 이벤트 없음, OPEN 유지) — 하트비트 공백을 워치독이 감지해
  //     (auth 200 후) 강제 재연결
  const e2 = last(); open(e2); e2.readyState = MockES.OPEN;
  if (e2.onmessage) e2.onmessage({data: '{}'});   // 정상 수신 → lastMsg 갱신
  now += 60000; runWatchdog();
  await flush(); await flush();
  console.log('N_after_stall=' + esInstances.length);

  // (4) CONNECTING 상태의 onerror(네이티브가 스스로 재시도 중)는 새 연결을 만들지 않는다
  const e3 = last(); open(e3); e3.readyState = MockES.CONNECTING; if (e3.onerror) e3.onerror();
  await flush(); await flush();
  now += 60000; flushDue();
  console.log('N_after_connecting_err=' + esInstances.length);
})();
"""


def _reconnect_counts(tmp_path):
    from backend.report.live_page import render_live_page
    html_p = tmp_path / "live.html"
    js_p = tmp_path / "reconnect.js"
    html_p.write_text(render_live_page("000660", "SK하이닉스", "live"),
                      encoding="utf-8")
    js_p.write_text(_RECONNECT_HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(js_p), str(html_p)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"재연결 하니스 예외:\n{r.stdout}\n{r.stderr}"
    out = {}
    for line in r.stdout.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = int(v)
    return out


@needs_node
def test_sse_reconnects_when_closed_stalled_or_resumed(tmp_path):
    # 실사고: 실시간 SSE가 끊긴 뒤 복구되지 않는다. 네이티브 자동 재접속은
    # CLOSED 상태에서 멈추고, 오류 없는 half-open 정지·백그라운드 복귀도 못 잡는다.
    c = _reconnect_counts(tmp_path)
    assert c["N_init"] == 1                    # 로드 직후 정확히 1개 연결
    assert c["N_after_closed"] == 2            # (1) CLOSED → 수동 재연결
    assert c["N_after_visible"] == 3           # (2) 화면 복귀 → 즉시 재연결
    assert c["N_after_stall"] == 4             # (3) 하트비트 공백 → 워치독 재연결
    assert c["N_after_connecting_err"] == 4    # (4) CONNECTING 오류는 재연결 안 함(중복 방지)


# ── 세션 만료 시 로그인 리다이렉트(인증 게이트 배포) ──────────────────────
# 세션 만료 시 SSE가 401 → EventSource는 상태코드를 못 읽어 CLOSED → 무한 재접속
# (방금 고친 버그처럼 보임). 재접속 직전 auth-check 프로브가 401이면 로그인으로 보낸다.
_AUTH_EXPIRY_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(function(s){return s.indexOf('loadCandles')>=0;}) || scripts[1];

let now = 1000000; Date.now = () => now;
const els = {}, listeners = {};
global.document = { hidden:false,
  getElementById: id => els[id] || (els[id]={textContent:'',innerHTML:'',className:'',style:{}}),
  querySelectorAll: () => [], addEventListener: (e,f)=>{(listeners[e]=listeners[e]||[]).push(f);} };
global.window = { addEventListener:(e,f)=>{(listeners[e]=listeners[e]||[]).push(f);} };
global.location = { href: '' };
let timers=[];
global.setTimeout=(fn,ms)=>{const t={fn,at:now+(ms||0)};timers.push(t);return t;};
global.clearTimeout=t=>{timers=timers.filter(x=>x!==t);};
const flushDue=()=>{const d=timers.filter(t=>t.at<=now);timers=timers.filter(t=>t.at>now);d.forEach(t=>t.fn());};
global.setInterval=()=>{};
let esI=[];
function MockES(u){this.url=u;this.readyState=0;this.onopen=this.onmessage=this.onerror=null;esI.push(this);}
MockES.CONNECTING=0;MockES.OPEN=1;MockES.CLOSED=2;
MockES.prototype.close=function(){this.readyState=2;};
global.EventSource=MockES;
global.LightweightCharts={createChart:()=>({addBaselineSeries:()=>({setData(){}}),
  addCandlestickSeries:()=>({setData(){},createPriceLine(){}}),timeScale:()=>({fitContent(){}}),applyOptions(){}})};
// auth-check 401(세션 만료). 그 외 fetch는 실패 응답.
global.fetch = async (u) => (String(u).indexOf('/api/auth/check')>=0)
  ? {status:401, ok:false, json:async()=>({})}
  : {ok:false, status:500, json:async()=>({})};

eval(code);
const flush=()=>new Promise(r=>setImmediate(r));
(async()=>{
  const e0=esI[0]; e0.readyState=MockES.OPEN; if(e0.onopen)e0.onopen();
  e0.readyState=MockES.CLOSED; if(e0.onerror)e0.onerror();  // 세션 만료로 CLOSED
  await flush(); await flush();
  now+=60000; flushDue();
  await flush();
  console.log('LOC='+location.href);
  console.log('N='+esI.length);
})();
"""


def _auth_expiry(tmp_path):
    from backend.report.live_page import render_live_page
    html_p, js_p = tmp_path / "live.html", tmp_path / "authexp.js"
    html_p.write_text(render_live_page("000660", "SK하이닉스", "live"), encoding="utf-8")
    js_p.write_text(_AUTH_EXPIRY_HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(js_p), str(html_p)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"하니스 예외:\n{r.stdout}\n{r.stderr}"
    out = {}
    for line in r.stdout.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


@needs_node
def test_sse_redirects_to_login_when_session_expired(tmp_path):
    out = _auth_expiry(tmp_path)
    assert out["LOC"] == "/login"   # 무한 재접속 대신 로그인으로
    assert out["N"] == "1"          # 재접속(새 EventSource) 안 함


# ── 가격 차트: 자동 갱신 시 뷰(확대/이동) 보존 ────────────────────────────
# 실사고: loadCandles가 매 60초 갱신마다 fitContent()를 불러 사용자의 확대/이동이
# 초기화됨. 자동 갱신은 뷰 보존, 타임프레임 전환/최초 로드에만 fit해야 한다.
_TF_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(function(s){return s.indexOf('loadCandles')>=0;}) || scripts[1];

let now = 1000000; Date.now = () => now;
const els = {}, listeners = {};
global.document = { hidden:false,
  getElementById: id => els[id] || (els[id]={__id:id,textContent:'',innerHTML:'',className:'',style:{}}),
  querySelectorAll: () => [], addEventListener: (e,f)=>{(listeners[e]=listeners[e]||[]).push(f);} };
global.window = { addEventListener:()=>{} };
global.location = { href:'' };
global.setTimeout = ()=>0; global.clearTimeout = ()=>{};
let intervals=[]; global.setInterval=(fn,ms)=>{intervals.push({fn,ms});return intervals.length;};
function MockES(){this.readyState=0;this.onopen=this.onmessage=this.onerror=null;}
MockES.CONNECTING=0;MockES.OPEN=1;MockES.CLOSED=2;MockES.prototype.close=function(){};
global.EventSource = MockES;

let fitCount = 0;   // pchart.timeScale().fitContent() 호출 수(가격 차트만)
global.LightweightCharts = { createChart: (el) => ({
  addBaselineSeries: () => ({setData(){}}),
  addCandlestickSeries: () => ({setData(){}, createPriceLine(){}}),
  timeScale: () => ({ fitContent(){ if (el && el.__id === 'pchart') fitCount++; } }),
  applyOptions(){},
})};
// 봉 데이터를 정상 반환(loadCandles가 setData·fit까지 도달하도록)
global.fetch = async (u) => (String(u).indexOf('/api/candles/') >= 0)
  ? {ok:true, json: async () => ({candles:[{t:'09:00:00',open:1,high:2,low:0.5,close:1.5}], date:'2026-07-14'})}
  : {ok:false, status:200, json: async () => ({})};

eval(code);   // sloppy eval → loadCandles/TF 등이 이 스코프에 노출됨(기존 하니스와 동일)
const flush = () => new Promise(r => setImmediate(r));
(async () => {
  await flush(); await flush();      // 최초 loadCandles(fit) 완료
  console.log('FIT_after_init=' + fitCount);
  await loadCandles(false);          // 자동 갱신(60초) — 뷰 보존이어야
  await flush();
  console.log('FIT_after_refresh=' + fitCount);
  TF = '15m'; await loadCandles(true);   // 타임프레임 전환 — fit 해야
  await flush();
  console.log('FIT_after_switch=' + fitCount);
})();
"""


def _tf_fit_counts(tmp_path):
    from backend.report.live_page import render_live_page
    html_p, js_p = tmp_path / "live.html", tmp_path / "tf.js"
    html_p.write_text(render_live_page("000660", "SK하이닉스", "live"), encoding="utf-8")
    js_p.write_text(_TF_HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(js_p), str(html_p)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"하니스 예외:\n{r.stdout}\n{r.stderr}"
    out = {}
    for line in r.stdout.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = int(v)
    return out


@needs_node
def test_candle_chart_preserves_view_on_autorefresh(tmp_path):
    c = _tf_fit_counts(tmp_path)
    assert c["FIT_after_init"] == 1       # 최초 로드는 fit(전체 보기)
    assert c["FIT_after_refresh"] == 1     # 60초 자동 갱신은 뷰 보존(fit 안 함)
    assert c["FIT_after_switch"] == 2      # 타임프레임 전환은 fit


# ── 감시선 편집기: 저장 경로(POST payload 구성·무효 줄 필터·응답 반영) ──────
# render() 스모크는 이 경로를 안 건드린다 — saveLines가 wlDraft에서 유효 줄만 모아
# 올바른 POST 본문을 만들고, 응답 lines로 WATCH를 갱신하는지 계측한다.
_SAVE_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(function(s){return s.indexOf('loadCandles')>=0;}) || scripts[1];
const els = {};
global.document = {
  getElementById: id => els[id] || (els[id] = {textContent:'', innerHTML:'', className:'', style:{}}),
  querySelectorAll: () => [],
};
global.window = {}; global.location = { href:'' };
global.setTimeout = () => 0; global.setInterval = () => {};
function MockES(){ this.readyState = 0; this.close = function(){}; }
MockES.CONNECTING=0; MockES.OPEN=1; MockES.CLOSED=2; global.EventSource = MockES;
global.LightweightCharts = { createChart: () => ({
  addBaselineSeries: () => ({setData(){}}),
  addCandlestickSeries: () => ({setData(){}, createPriceLine(){return {};}, removePriceLine(){}}),
  timeScale: () => ({fitContent(){}}), applyOptions(){}, subscribeClick(){},
})};
let captured = null;
global.fetch = async (u, opt) => {
  if (String(u).indexOf('/api/watch/') >= 0) {
    captured = {url:String(u), method:opt&&opt.method, body:opt&&opt.body};
    return {ok:true, json: async () => ({lines:[
      {price:1853000,label:'절대선'},{price:2600000,label:'예약매도'},{price:1700000,label:'손절'}]})};
  }
  return {ok:false, status:200, json: async () => ({})};
};
eval(code);   // sloppy eval → saveLines/wlAddRow/WATCH가 이 스코프에 노출
const flush = () => new Promise(r => setImmediate(r));
(async () => {
  wlAddRow('빈줄');     // 가격 없는 줄 — 저장에서 제외되어야(클라 사전검증)
  saveLines();
  await flush(); await flush(); await flush();
  console.log('URL=' + (captured && captured.url));
  console.log('METHOD=' + (captured && captured.method));
  console.log('BODY=' + (captured && captured.body));
  console.log('STATUS=' + (els['wl-status'] ? els['wl-status'].textContent : ''));
})();
"""


def _save_harness(tmp_path):
    from backend.report.live_page import render_live_page
    html_p, js_p = tmp_path / "live.html", tmp_path / "save.js"
    html_p.write_text(render_live_page("000660", "SK하이닉스", "live"), encoding="utf-8")
    js_p.write_text(_SAVE_HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(js_p), str(html_p)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"하니스 예외:\n{r.stdout}\n{r.stderr}"
    out = {}
    for line in r.stdout.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


@needs_node
def test_watch_editor_save_builds_payload_and_applies_response(tmp_path):
    out = _save_harness(tmp_path)
    assert out["URL"].endswith("/api/watch/000660")   # 종목별 저장 엔드포인트
    assert out["METHOD"] == "POST"
    body = json.loads(out["BODY"])
    labels = [x["label"] for x in body["lines"]]
    # config 기본 2줄은 유효 → 전송, 가격 없는 '빈줄'은 클라 검증에서 제외
    assert "절대선" in labels and "예약매도" in labels
    assert "빈줄" not in labels
    assert all(isinstance(x["price"], int) and x["price"] > 0 for x in body["lines"])
    assert "저장됨" in out["STATUS"]                   # 성공 상태 표시
    # 상태 문구의 개수(WATCH.length)는 응답 lines(손절 포함 3줄)로 갱신됨을 증명
    # → WATCH=res.d.lines 적용 + renderWatchLines/rearm 경로가 돎
    assert "3개" in out["STATUS"]


# ── 토스 차트 이식 Phase 1 ──
def test_template_has_5ma_buttons():
    from backend.report.live_page import render_live_page
    html = render_live_page("000660", "SK하이닉스", "live")
    assert 'data-ma="5"' in html and 'data-ma="10"' in html
    assert 'data-ma="20"' in html and 'data-ma="120"' in html


def test_page_logic_has_extreme_labels():
    # 마커는 플롯 가장자리에서 잘려(극값=가격 극단) 토스식 떠있는 라벨로 대체.
    # 오버레이 요소 + 좌표변환(placeExt) + 구현 주석 토큰을 페이지 로직에서 검증.
    import re
    from backend.report.live_page import render_live_page
    html = render_live_page("000660", "SK하이닉스", "live")
    assert 'id="hi-lbl"' in html and 'id="lo-lbl"' in html   # 최고/최저 오버레이 라벨
    page = next(s for s in re.findall(r"<script>([\s\S]*?)</script>", html)
                if "loadCandles" in s)
    assert "priceToCoordinate" in page and "placeExt" in page
    assert "최고/최저" in page                                # 내 구현 주석 토큰


def test_hero_has_change_element():
    from backend.report.live_page import render_live_page
    html = render_live_page("000660", "SK하이닉스", "live")
    assert 'id="chg"' in html


def test_chart_has_volume_label():
    from backend.report.live_page import render_live_page
    html = render_live_page("000660", "SK하이닉스", "live")
    assert 'id="vol-lb"' in html
