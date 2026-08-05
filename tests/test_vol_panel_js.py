"""VKOSPI 섹션 JS 실행 스모크 — node로 실제 실행한다.

캔버스가 없는 환경이라 2D 컨텍스트를 기록용 스텁으로 대신하고, 어떤 도형이 어디에
그려졌는지를 단언한다. 옵션 차트에서 스크린샷으로만 잡혔던 결함 3개(라벨 잘림·
라벨 겹침·캔버스 부풀기)를 여기선 처음부터 테스트로 막는다.
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
const openIt = process.argv[4] === 'open';
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(s => s.indexOf('loadVkospi') >= 0);
if (!code) { console.log(JSON.stringify({error: 'loadVkospi 스크립트 없음'})); process.exit(0); }

const ops = [];
let fetches = 0;
function ctx(){
  const o = {};
  const rec = name => function(){ ops.push([name].concat([...arguments])); };
  ['clearRect','fillRect','beginPath','moveTo','lineTo','stroke','fill','arc',
   'fillText','setTransform','closePath','save','restore'].forEach(n => o[n] = rec(n));
  ['fillStyle','strokeStyle','lineWidth','globalAlpha','font','textAlign','textBaseline']
    .forEach(k => Object.defineProperty(o, k, {set(){}, get(){ return ''; }}));
  return o;
}
const attrs = {};
const validIds = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));
const els = {};
let toggleFn = null;
function mk(id){
  const e = {id, textContent:'', innerHTML:'', className:'', style:{}, clientWidth: 340,
             open: false, addEventListener: (t, f) => { if (t === 'toggle') toggleFn = f; }};
  if (id === 'vk-chart') {
    attrs[id] = {height: '180', 'data-h': '180'};
    e.getAttribute = k => (k in attrs[id] ? attrs[id][k] : null);
    Object.defineProperty(e, 'height', {
      set(v){ attrs[id].height = String(v); }, get(){ return +attrs[id].height; }});
    Object.defineProperty(e, 'width', {
      set(v){ attrs[id].width = String(v); }, get(){ return +(attrs[id].width||0); }});
    e.getContext = () => ctx();
  }
  return e;
}
global.document = {
  getElementById: id => validIds.has(id) ? (els[id] || (els[id] = mk(id))) : null,
  querySelectorAll: () => [],
  documentElement: {},
};
global.window = {devicePixelRatio: 2, addEventListener: () => {}, __vkLast: null};
global.getComputedStyle = () => ({getPropertyValue: k =>
  ({'--up':'#e5342f','--down':'#1f66e0','--border':'#dcdfe6','--text-3':'#8b93a4',
    '--text':'#1a1d24'}[k] || '')});
global.setInterval = () => 0;
// **/api/vkospi만 센다.** 페이지엔 즉시 로드되는 다른 로더가 여럿이라(가격·시장·
// 반도체·옵션…) 전역 fetch를 그냥 세면 7건쯤이 섞여 지연 로딩 검증이 무의미해진다.
global.fetch = async (u) => {
  if (String(u).indexOf('/api/vkospi') >= 0) fetches++;
  return {ok: true, json: async () => (String(u).indexOf('/api/vkospi') >= 0 ? payload : {})};
};

(async () => {
  try {
    eval(code);
    await new Promise(r => setTimeout(r, 20));
    const before = fetches;                    // 펼치기 전 호출 수
    if (openIt && toggleFn) { els['volsec'].open = true; toggleFn();
                              await new Promise(r => setTimeout(r, 30));
                              els['volsec'].open = false; toggleFn();
                              els['volsec'].open = true; toggleFn();
                              await new Promise(r => setTimeout(r, 20)); }
    const firstPass = ops.slice();   // 재렌더 전까지가 loadVkospi()의 결과다
    const h1 = attrs['vk-chart'] ? attrs['vk-chart'].height : null;
    if (typeof vkDraw === 'function' && els['vk-chart'] && window.__vkLast)
      vkDraw(els['vk-chart'], window.__vkLast);
    const h2 = attrs['vk-chart'] ? attrs['vk-chart'].height : null;
    console.log(JSON.stringify({
      ok: true, fetchesBeforeOpen: before, fetchesTotal: fetches,
      now: (els['vk-now']||{}).innerHTML || '',
      cap: (els['vk-cap']||{}).textContent || '',
      foot: (els['vk-foot']||{}).textContent || '',
      display: ((els['volsec']||{}).style||{}).display,
      h1, h2, ops: firstPass,
    }));
  } catch (e) { console.log(JSON.stringify({error: String(e && e.stack || e)})); }
})();
"""


def _run(tmp_path, payload, open_it=True):
    from backend.report.dashboard import render_dashboard
    html = tmp_path / "dash.html"
    html.write_text(render_dashboard([], [], "2026-08-05"), encoding="utf-8")
    data = tmp_path / "vk.json"
    data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    js = tmp_path / "h.js"
    js.write_text(_HARNESS, encoding="utf-8")
    out = subprocess.run(["node", str(js), str(html), str(data),
                          "open" if open_it else "closed"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert "error" not in res, res["error"]
    return res


def _payload():
    """실측 모양 — 100거래일, 월 경계 6개(3·4·5·6·7·8월), 마지막 월이 끝 근처."""
    dates = (["202603%02d" % d for d in range(12, 26)]
             + ["202604%02d" % d for d in range(1, 23)]
             + ["202605%02d" % d for d in range(4, 22)]
             + ["202606%02d" % d for d in range(1, 22)]
             + ["202607%02d" % d for d in range(1, 23)]
             + ["202608%02d" % d for d in (3, 4, 5)])[:100]
    days = []
    for i, d in enumerate(dates):
        v = 48.51 + (96.94 - 48.51) * (0.5 + 0.45 * ((i % 17) / 17.0 - 0.5) * 2)
        days.append({"d": d, "v": round(v, 2)})
    days[-1]["v"] = 78.55
    return {"now": {"price": 78.55, "change": -3.5, "rate": -4.27, "sign": "down"},
            "days": days, "ts": 1786000000.0}


@needs_node
def test_does_not_fetch_before_the_section_is_opened(tmp_path):
    """**이 설계의 핵심 약속** — 안 펼치면 KIS 호출 0건이다."""
    res = _run(tmp_path, _payload(), open_it=False)
    assert res["fetchesBeforeOpen"] == 0 and res["fetchesTotal"] == 0


@needs_node
def test_fetches_once_no_matter_how_many_times_it_is_toggled(tmp_path):
    """토글은 연타할 수 있다 — 펼칠 때마다 부르면 안 된다."""
    res = _run(tmp_path, _payload())
    assert res["fetchesTotal"] == 1


@needs_node
def test_renders_value_and_line_chart(tmp_path):
    res = _run(tmp_path, _payload())
    assert "78.55" in res["now"] and "4.27%" in res["now"]
    assert "100거래일" in res["cap"]
    assert "지수와 반대로 움직입니다" in res["foot"]
    assert len([o for o in res["ops"] if o[0] == "lineTo"]) >= 99   # 100점 라인
    assert len([o for o in res["ops"] if o[0] == "arc"]) == 1       # 오늘 마커 1개


@needs_node
def test_x_axis_has_month_labels(tmp_path):
    """양 끝 날짜만 찍으면 '언제 튀었나'를 못 읽는다 — 월 눈금이 있어야 한다."""
    res = _run(tmp_path, _payload())
    texts = [o[1] for o in res["ops"] if o[0] == "fillText"]
    months = [t for t in texts if str(t).endswith("월")]
    assert len(months) >= 4, texts


@needs_node
def test_month_label_does_not_collide_with_the_today_marker(tmp_path):
    """마지막 월 경계는 항상 오른쪽 끝 근처다(월초는 늘 최근이다) — 예외가 아니라 기본이다."""
    res = _run(tmp_path, _payload())
    texts = [o for o in res["ops"] if o[0] == "fillText"]
    months = [o for o in texts if str(o[1]).endswith("월")]
    marker = [o for o in texts if "78.5" in str(o[1])]
    assert months and marker
    for m in months:
        for k in marker:
            close_x = abs(m[2] - k[2]) < 34      # 라벨 폭만큼 가까운데
            same_y = abs(m[3] - k[3]) < 12       # 같은 높이면 겹친다
            assert not (close_x and same_y), "월 라벨과 마커 라벨이 겹친다 %s %s" % (m, k)


@needs_node
def test_all_text_stays_inside_the_canvas(tmp_path):
    """앵커만이 아니라 글리프 박스까지 — 10px 폰트라 상하 12px 여백을 요구한다."""
    res = _run(tmp_path, _payload())
    ys = [o[3] for o in res["ops"] if o[0] == "fillText"]
    xs = [o[2] for o in res["ops"] if o[0] == "fillText"]
    assert ys and min(ys) >= 12 and max(ys) <= 180 - 12 + 3, ys
    assert min(xs) >= 0 and max(xs) <= 340, xs


@needs_node
def test_redraw_does_not_inflate_the_canvas(tmp_path):
    """cv.height 대입이 height 속성을 덮어쓴다 — 의도한 높이는 data-h에서 읽어야 한다.
    옵션 차트에서 190→570→1710으로 부푼 적 있다."""
    res = _run(tmp_path, _payload())
    assert res["h1"] == res["h2"], "재렌더에 캔버스가 부풀었다 %s → %s" % (res["h1"], res["h2"])
    assert int(res["h1"]) == 180 * 2


@needs_node
def test_section_hides_itself_when_there_is_no_data(tmp_path):
    res = _run(tmp_path, {"now": None, "days": []})
    assert res["display"] == "none"
