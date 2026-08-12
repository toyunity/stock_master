"""US 상세 화면 JS 실행 스모크 — 문자열 검사로는 못 잡는 것을 잡는다.

같은 종류의 사고가 이 저장소에서 두 번 났다: `prsn is not defined`(2026-07-10)로
렌더가 중간에 죽어 이후 패널이 통째로 안 나왔고, 가짜 엘리먼트에 `addEventListener`가
없어 다른 패널이 스크립트 전체를 죽였다(2026-08-05, 옵션 테스트 10건 동시 실패).
그래서 하니스는 **실제 페이지에 있는 id만** 인정하고(없는 id는 null → TypeError),
브라우저 API를 최소한만 흉내 낸다.
"""
import json
import shutil
import subprocess

import pytest

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 미설치 — JS 실행 스모크 생략")


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))


_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const candles = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(s => s.indexOf('loadCandles') >= 0);
if (!code) { console.log('NO CODE'); process.exit(1); }

// 실제 페이지에 있는 id만 인정 — 없는 id에 접근하면 브라우저처럼 null이 돌아와
// 그 뒤 .textContent= 에서 TypeError로 죽어야 한다(유령 엘리먼트 금지).
const validIds = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));
const els = {};
const mkEl = () => ({textContent:'', innerHTML:'', className:'', style:{}, open:false,
                     disabled:false, classList:{add(){}, remove(){}, toggle(){}},
                     addEventListener(){}, getAttribute(){return null;},
                     querySelectorAll(){return [];}});
global.document = {
  getElementById: id => validIds.has(id) ? (els[id] || (els[id] = mkEl())) : null,
  querySelectorAll: () => [],
};
global.__lines = [];
global.__series = null;
global.chartTheme = () => ({layout:{}, grid:{}, rightPriceScale:{}});
global.LightweightCharts = { createChart: () => ({
  addCandlestickSeries: () => (global.__series = {
    setData(d){ global.__series._data = d; },
    createPriceLine(o){ global.__lines.push(o); return o; },
    removePriceLine(){}, coordinateToPrice(){ return 100; },
  }),
  addLineSeries: () => ({setData(d){ }}),
  timeScale: () => ({fitContent(){}}),
  applyOptions(){}, subscribeClick(){},
})};
global.fetch = async (url) => {
  if (String(url).indexOf('/api/candles/') >= 0)
    return {ok:true, status:200, json: async () => candles};
  return {ok:false, status:204, json: async () => ({})};   // usprice: 장외
};
global.setTimeout = () => {};      // pollLive 재예약이 무한루프가 되지 않게

eval(code);
// loadCandles는 async — 마이크로태스크가 끝난 뒤 결과를 찍는다
setImmediate(() => {
  console.log('RENDER OK');
  console.log('TXT:price=' + String((els['price']||{}).textContent));
  console.log('TXT:chg=' + String((els['chg']||{}).textContent));
  console.log('TXT:chgcls=' + String((els['chg']||{}).className));
  console.log('TXT:basis=' + String((els['pbasis']||{}).textContent));
  console.log('TXT:mahint=' + String((els['ma-hint']||{}).textContent));
  console.log('TXT:mylines=' + String((els['mylines']||{}).innerHTML));
  console.log('TXT:rows=' + String((els['wl-rows']||{}).innerHTML));
  console.log('TXT:lines=' + global.__lines.map(l => l.title + '@' + l.price).join(','));
  console.log('TXT:walert=' + String((els['walert']||{}).textContent));
});
"""


def _render(tmp_path, watch=None):
    from backend.flow import userstore
    from backend.report.us_page import render_us_page
    if watch:
        userstore.set_lines(userstore.default_account(), "SKHY", watch)
    p = tmp_path / "us.html"
    p.write_text(render_us_page("SKHY", "SKHY"), encoding="utf-8")
    return p


def _run(tmp_path, cs, watch=None):
    html = _render(tmp_path, watch)
    cj = tmp_path / "c.json"
    cj.write_text(json.dumps({"tf": "1d", "candles": cs}), encoding="utf-8")
    hp = tmp_path / "h.js"
    hp.write_text(_HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(hp), str(html), str(cj)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    out = dict(l.split("=", 1) for l in r.stdout.splitlines() if l.startswith("TXT:"))
    assert "RENDER OK" in r.stdout, r.stdout
    return {k[4:]: v for k, v in out.items()}


def _cs(closes):
    return [{"t": "2026-08-%02d" % (i + 1), "open": c, "high": c, "low": c,
             "close": c, "vol": 0} for i, c in enumerate(closes)]


@needs_node
def test_price_and_change_come_from_the_daily_candles(tmp_path):
    """가격은 차트와 같은 데이터에서 뽑는다 — 따로 조회하면 둘이 어긋난다."""
    o = _run(tmp_path, _cs([150.0, 153.16]))
    assert o["price"] == "$153.16"
    assert o["chg"] == "+2.11%"          # (153.16-150)/150


@needs_node
def test_up_is_red_and_down_is_blue(tmp_path):
    """국내 관례를 미국 종목에도 그대로 — 앱 안에서 색이 뒤집히면 안 된다."""
    assert "up" in _run(tmp_path, _cs([100.0, 110.0]))["chgcls"]
    assert "down" in _run(tmp_path, _cs([110.0, 100.0]))["chgcls"]


@needs_node
def test_cents_are_shown_not_rounded_away(tmp_path):
    """$153.16이 $153으로 보이면 감시선을 걸 수가 없다."""
    assert _run(tmp_path, _cs([153.16]))["price"] == "$153.16"


@needs_node
def test_watch_lines_are_drawn_on_the_chart_with_cents(tmp_path):
    o = _run(tmp_path, _cs([150.0, 153.16]),
             watch=[{"price": 160.25, "label": "절대선"}])
    assert o["lines"] == "절대선@160.25"
    assert "$160.25" in o["mylines"]


@needs_node
def test_watch_editor_input_accepts_decimals(tmp_path):
    """입력칸이 정수만 받으면 $153.16을 아예 넣을 수 없다(국내와 다른 지점)."""
    o = _run(tmp_path, _cs([150.0]), watch=[{"price": 160.25, "label": "절대선"}])
    assert 'step="0.01"' in o["rows"] and "160.25" in o["rows"]


@needs_node
def test_missing_moving_averages_say_why(tmp_path):
    """신규 상장이라 표본이 없으면 '없다'가 아니라 '왜 없는지'를 적는다.
    SKHY(2026-07-10 상장)가 실제로 이 상태다 — 꾸며내지 않는다."""
    assert "거래일이 모자라" in _run(tmp_path, _cs([150.0, 153.16]))["mahint"]


@needs_node
def test_watch_alert_fires_when_price_is_near_the_line(tmp_path):
    o = _run(tmp_path, _cs([150.0, 153.16]),
             watch=[{"price": 153.20, "label": "손절"}])
    assert "손절" in o["walert"]


@needs_node
def test_empty_candles_degrade_to_a_message_not_a_crash(tmp_path):
    """일봉을 못 받아도 화면이 죽지 않는다 — 감시선 섹션은 살아야 한다."""
    o = _run(tmp_path, [])
    assert "못 불러왔" in o["basis"]


def test_poll_live_relabels_plabel_from_close_to_current():
    """정규장 중엔 pollLive()가 실시간 가격을 준다 — 그런데 #plabel이 초기값
    "종가"에 머물면 실시간 값에 "종가" 라벨이 붙는다(2026-08-13 리뷰).
    #pbasis를 '정규장 · 60초 갱신'으로 세팅하는 바로 그 성공 분기에서
    #plabel도 '현재가'로 바꾼다 — 세션 판정은 #pbasis가 이미 하니 새로 안 만든다."""
    from backend.report.us_page import render_us_page
    html = render_us_page("NVDA", "NVIDIA")
    body = html.split("async function pollLive(){", 1)[1].split("setTimeout(pollLive,60000);", 1)[0]
    assert "정규장" in body       # 픽스처 전제: pbasis 세팅 분기가 실제로 있다
    assert "getElementById('plabel')" in body and "현재가" in body


def test_us_hero_matches_live_structure():
    """미국 상세도 같은 히어로 문법을 쓴다 — 두 화면이 다른 문법을 쓰면
    theme.py 단일 출처의 의미가 없다."""
    from backend.report.us_page import render_us_page
    html = render_us_page("NVDA", "NVIDIA")
    assert 'class="plabel"' in html
    assert 'class="pill' in html          # 등락이 텍스트가 아니라 필
    assert 'class="hstate"' in html
