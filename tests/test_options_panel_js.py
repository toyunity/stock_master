"""옵션 섹션 JS 실행 스모크 — 문자열 검사가 아니라 node로 실제 실행한다.

/live에서 확립한 패턴 그대로다. 문자열 존재 검사로는 ReferenceError(렌더가 중간에
죽어 이후가 전부 미표시)를 못 잡는다. 캔버스는 없는 환경이라 2D 컨텍스트를 기록용
스텁으로 대신하고, 어떤 도형이 어디에 그려졌는지를 단언한다.
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
const payload = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(s => s.indexOf('loadOptions') >= 0);
if (!code) { console.log(JSON.stringify({error: 'loadOptions 스크립트 없음'})); process.exit(0); }

const ops = [];                       // 캔버스에 그려진 것 전부를 기록한다
function ctx(){
  const o = {ops};
  const rec = name => function(){ ops.push([name].concat([...arguments])); };
  ['clearRect','fillRect','beginPath','moveTo','lineTo','stroke','fill','arc',
   'fillText','setTransform','closePath','save','restore'].forEach(n => o[n] = rec(n));
  Object.defineProperty(o, 'fillStyle', {set(v){ ops.push(['fillStyle', v]); }, get(){ return ''; }});
  Object.defineProperty(o, 'strokeStyle', {set(v){ ops.push(['strokeStyle', v]); }, get(){ return ''; }});
  Object.defineProperty(o, 'lineWidth', {set(){}, get(){ return 1; }});
  Object.defineProperty(o, 'globalAlpha', {set(){}, get(){ return 1; }});
  Object.defineProperty(o, 'font', {set(){}, get(){ return ''; }});
  Object.defineProperty(o, 'textAlign', {set(){}, get(){ return ''; }});
  Object.defineProperty(o, 'textBaseline', {set(){}, get(){ return ''; }});
  return o;
}
const validIds = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));
const els = {};
// 실제 캔버스처럼 width/height 대입이 **속성을 덮어쓴다**. 그리기 코드가 의도한
// CSS 높이를 live 속성에서 다시 읽으면 매 렌더마다 dpr배로 부풀어 오른다.
const attrs = {};
// 한글은 전각이라 라틴의 약 1.8배 폭을 먹는다(11px 모노 기준 CDP 실측 근사).
// 이 근사가 있어야 optFit의 '뒤에서부터 빼기'가 node에서도 실제로 돌아간다.
function textPx(s){
  let w = 0;
  for(const ch of String(s||'')) w += (ch.charCodeAt(0) > 0x1100 ? 11 : 6.2);
  return Math.round(w);
}
function mk(id){
  const e = {id, textContent:'', innerHTML:'', className:'', style:{},
             clientWidth: 340};
  if (id === 'opt-dig') {           // 접힌 줄 — 390px 화면의 실측 가용폭
    let t = '';
    Object.defineProperty(e, 'textContent', {set(v){ t = v; }, get(){ return t; }});
    Object.defineProperty(e, 'scrollWidth', {get(){ return textPx(t); }});
    Object.defineProperty(e, 'clientWidth', {get(){ return 200; }});
    return e;
  }
  if (id === 'opt-chg' || id === 'opt-oi') {
    attrs[id] = {height: '190', 'data-h': '190'};
    e.getAttribute = k => (k in attrs[id] ? attrs[id][k] : null);
    Object.defineProperty(e, 'height', {
      set(v){ attrs[id].height = String(v); }, get(){ return +attrs[id].height; }});
    Object.defineProperty(e, 'width', {
      set(v){ attrs[id].width = String(v); }, get(){ return +(attrs[id].width || 0); }});
    e.getContext = () => ctx();
  }
  return e;
}
global.document = {
  getElementById: id => validIds.has(id) ? (els[id] || (els[id] = mk(id))) : null,
  querySelectorAll: () => [],
  documentElement: {},
};
global.window = {devicePixelRatio: 2, addEventListener: () => {}, __optLast: null};
global.getComputedStyle = () => ({getPropertyValue: k =>
  ({'--up':'#e5342f','--down':'#1f66e0','--border':'#dcdfe6','--text-3':'#8b93a4'}[k] || '')});
global.setInterval = () => 0;
global.fetch = async () => ({ok: true, json: async () => payload});

(async () => {
  try {
    eval(code);
    await new Promise(r => setTimeout(r, 30));    // loadOptions()가 await를 끝내도록
    const firstPass = ops.slice();      // 재렌더 전까지가 loadOptions()의 결과다
    const h1 = attrs['opt-chg'] ? attrs['opt-chg'].height : null;
    if (typeof optDraw === 'function' && els['opt-chg'] && window.__optLast) {
      optDraw(els['opt-chg'], window.__optLast, 2, true);   // 리사이즈 재렌더 흉내
    }
    const h2 = attrs['opt-chg'] ? attrs['opt-chg'].height : null;
    console.log(JSON.stringify({
      ok: true,
      dig: (els['opt-dig'] || {}).textContent || '',
      digFits: els['opt-dig'] ? els['opt-dig'].scrollWidth <= els['opt-dig'].clientWidth : null,
      nums: (els['opt-nums'] || {}).innerHTML || '',
      foot: (els['opt-foot'] || {}).textContent || '',
      display: ((els['optsec'] || {}).style || {}).display,
      h1, h2,
      ops: firstPass,
    }));
  } catch (e) {
    console.log(JSON.stringify({error: String(e && e.stack || e)}));
  }
})();
"""


def _run(tmp_path, payload):
    from backend.report.dashboard import render_dashboard
    html = tmp_path / "dash.html"
    html.write_text(render_dashboard([], [], "2026-08-05"), encoding="utf-8")
    data = tmp_path / "opt.json"
    data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    js = tmp_path / "h.js"
    js.write_text(_HARNESS, encoding="utf-8")
    out = subprocess.run(["node", str(js), str(html), str(data)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert "error" not in res, res["error"]
    return res


def _payload(**over):
    d = {"expiry": "202608", "label": "8월물", "remain_days": 9, "spot": 1039.35,
         "cols": ["strike", "oi", "oi_chg"],
         "calls": [[1000.0, 5000, 100], [1050.0, 9000, 300], [1300.0, 8000, 2214],
                   [1597.5, 26000, -224]],
         "puts": [[625.0, 22000, 10], [1000.0, 7000, 1189], [1050.0, 3000, -50]],
         "summary": {"pcr": 0.75, "put_wall": 1000.0, "wall_pct": 20.0,
                     "atm_iv": 87.0, "atm_strike": 1050.0,
                     "call_chg_sum": 6963, "put_chg_sum": 5616,
                     "top_call": {"strike": 1300.0, "oi_chg": 2214},
                     "top_put": {"strike": 1000.0, "oi_chg": 1189}},
         "failed": 0, "ts": 1786000000.0, "collecting": False, "stale": False}
    d.update(over)
    return d


@needs_node
def test_collapsed_digest_keeps_todays_change_and_fits_a_phone(tmp_path):
    """접힌 줄에서 **오늘의 증감**이 살아남아야 한다.

    390px에 다 안 들어가면 CSS가 뒤쪽부터 잘라낸다 — 항목을 다 욱여넣으면
    하필 이 설계의 주인공('오늘 콜 +6,963')이 먼저 사라진다. IV는 펼치면 숫자
    카드에 있지만 오늘의 증감은 거기에도 없다."""
    res = _run(tmp_path, _payload())
    assert "콜 +6,963" in res["dig"], res["dig"]
    assert res["digFits"], "접힌 줄이 넘쳤다: %s" % res["dig"]


@needs_node
def test_collapsed_digest_drops_an_item_rather_than_truncating(tmp_path):
    """증감이 여섯 자리가 되면 항목을 **빼서** 맞춘다 — 잘라내지 않는다.

    1,012 종목 합계는 쉽게 십만 단위가 되고, 그날 '콜 +48.6만 · 풋 -39.3만'은
    390px를 13px 넘긴다(CDP 실측). 잘린 값은 무슨 값인지 알 수 없으므로,
    덜 중요한 뒤쪽(풋)을 통째로 빼고 앞쪽(콜)은 온전히 남긴다."""
    s = dict(_payload()["summary"])
    s["call_chg_sum"] = 486213
    s["put_chg_sum"] = -392884
    res = _run(tmp_path, _payload(summary=s))
    assert res["digFits"], "접힌 줄이 넘쳤다: %s" % res["dig"]
    assert "콜 +48.6만" in res["dig"], res["dig"]      # 큰 수는 만 단위로 줄인다
    assert "풋" not in res["dig"], "덜 중요한 항목이 남고 줄이 넘쳤다: %s" % res["dig"]


@needs_node
def test_section_renders_digest_numbers_and_both_charts(tmp_path):
    res = _run(tmp_path, _payload())
    assert "8월물" in res["dig"] and "D-9" in res["dig"]
    assert "풋콜" not in res["dig"]                  # 접힌 줄이 아니라 숫자 카드에 있다
    assert "풋콜 비율" in res["nums"] and "0.75" in res["nums"]
    assert "풋 벽" in res["nums"] and "1,000.0" in res["nums"]
    assert "지수 ±20% 안에서" in res["nums"]        # 범위 병기 — 정직성 규칙
    assert "콜 벽" not in res["nums"]                # 콜 벽은 숫자로 내지 않는다
    rects = [o for o in res["ops"] if o[0] == "fillRect"]
    assert len(rects) >= 14                          # 두 차트 × (막대 7개 + 밴드)


@needs_node
def test_negative_change_bars_extend_opposite_side(tmp_path):
    """증감이 음수면 중앙선 반대쪽으로 뻗어야 한다 — '줄었음'을 그대로 보여준다.
    콜(위쪽)의 −224는 아래로, 풋(아래쪽)의 −50은 위로 간다."""
    res = _run(tmp_path, _payload())
    # fillRect(x, y, w, h) — 음수 막대는 h의 부호가 같은 편 막대와 반대다
    rects = [o for o in res["ops"] if o[0] == "fillRect" and abs(o[4]) > 0.5]
    assert any(o[4] > 0 for o in rects) and any(o[4] < 0 for o in rects)


@needs_node
def test_markers_only_on_change_chart(tmp_path):
    """누적 차트의 최댓값은 사다리 끝(1,597.5)이다 — 거기에 마커를 찍으면
    '숫자로 내지 말라'고 한 값을 차트가 강조하게 된다. 마커는 증감에만."""
    res = _run(tmp_path, _payload())
    arcs = [o for o in res["ops"] if o[0] == "arc"]
    assert len(arcs) == 2                            # 증감 차트의 콜·풋 최대 증가 2개


@needs_node
def test_section_hides_itself_when_board_is_empty(tmp_path):
    res = _run(tmp_path, _payload(calls=[], puts=[], summary={}))
    assert res["display"] == "none"
    assert [o for o in res["ops"] if o[0] == "fillRect"] == []


@needs_node
def test_footer_states_failures_and_collecting(tmp_path):
    res = _run(tmp_path, _payload(failed=30, collecting=True))
    assert "30건" in res["foot"] and "집계 중" in res["foot"]


@needs_node
def test_all_text_stays_inside_the_canvas(tmp_path):
    """마커 글자가 캔버스 밖으로 나가면 안 된다.

    막대가 천장까지 닿으면 라벨이 그 위(y<0)에 놓여 통째로 잘린다 —
    2026-08-05 스크린샷에서 '1,303 +2,220'이 실제로 잘렸다. 값이 클수록 잘리므로
    하필 **가장 중요한 마커**가 안 보인다."""
    res = _run(tmp_path, _payload())
    texts = [o for o in res["ops"] if o[0] == "fillText"]
    assert texts, "라벨이 하나도 안 그려졌다"
    # 앵커만 캔버스 안이면 부족하다 — 글자는 baseline 기준으로 위아래로 뻗는다.
    # 10px 폰트라 상하 12px 여백을 요구한다(그래야 글리프 박스가 다 들어온다).
    pad = 12
    ys = [o[3] for o in texts]
    assert min(ys) >= pad and max(ys) <= 190 - pad + 3, "캔버스 밖 라벨 y=%s" % ys
    xs = [o[2] for o in texts]
    assert min(xs) >= 0 and max(xs) <= 340, "캔버스 밖 라벨 x=%s" % xs


@needs_node
def test_redraw_does_not_inflate_the_canvas(tmp_path):
    """캔버스는 몇 번을 다시 그려도 같은 크기여야 한다.

    cv.height 대입은 height **속성 자체**를 덮어쓴다 — 의도한 CSS 높이를 그
    속성에서 다시 읽으면 렌더할 때마다 dpr배로 부푼다(190 → 570 → 1710,
    2026-08-05 스크린샷에서 실제로 잡힌 버그). 리사이즈 때마다 섹션이
    화면 밖으로 늘어난다."""
    res = _run(tmp_path, _payload())
    assert res["h1"] == res["h2"], "재렌더에 캔버스가 부풀었다 %s → %s" % (
        res["h1"], res["h2"])
    assert int(res["h1"]) == 190 * 2            # dpr 2 — 의도한 백킹스토어 크기


@needs_node
def test_missing_values_render_dash_not_zero(tmp_path):
    """모르는 값을 0으로 꾸미지 않는다."""
    res = _run(tmp_path, _payload(summary={"pcr": None, "put_wall": None,
                                           "wall_pct": 20.0, "atm_iv": None,
                                           "atm_strike": None, "call_chg_sum": 0,
                                           "put_chg_sum": 0, "top_call": None,
                                           "top_put": None}))
    assert "–" in res["nums"] and "0.00" not in res["nums"]
