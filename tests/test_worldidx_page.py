"""대시보드 '글로벌' 섹션 렌더 — 단위와 기준일이 화면까지 살아 오는지.

이 섹션은 살아 있는 코스피·선물 칩 바로 아래에 붙는다. 값만 옮겨 그리면 직전
영업일 숫자가 지금 값처럼 읽힌다 — **칩마다 기준일을 찍는** 이유이자, 이 파일이
지키는 첫 번째 계약이다.

두 번째 계약은 단위다. 서버가 실은 `unit`을 그대로 쓰고 프런트는 아무것도 지어내지
않는다. 설계 문서가 기각한 ETF 프록시 사고("금 402")는 프런트가 단위를 추측해서
생긴 사고였다 — 화면에서 그대로 재발할 수 있다.

문자열 존재 검사만으로는 부족하다("mchip"이 소스에 있어도 칩이 하나도 안 그려질 수
있다). node가 있으면 렌더 JS를 실제로 실행해 결과 HTML을 본다(test_options_panel_js.py
하니스와 같은 관행). node가 없으면 실행 스모크만 skip.
"""
import json
import shutil
import subprocess

import pytest

from backend.report.dashboard import render_dashboard

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 미설치 — JS 실행 스모크 생략")

_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const payload = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const fail = process.argv[4] === 'fail';        // /api/worldidx 자체가 실패하는 경우
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const code = scripts.find(s => s.indexOf('loadWorldidx') >= 0);
if (!code) { console.log(JSON.stringify({error: 'loadWorldidx 스크립트 없음'})); process.exit(0); }
// 실제 페이지에 있는 id만 인정한다 — 없는 id를 유령 엘리먼트로 만들어주면 오타난
// 참조를 이 테스트가 못 잡는다(/live 하니스와 같은 규칙).
const validIds = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));
const els = {};
const mk = id => ({id, textContent:'', innerHTML:'', className:'', style:{},
                   clientWidth: 326, open:false, addEventListener: () => {}});
global.document = {
  getElementById: id => validIds.has(id) ? (els[id] || (els[id] = mk(id))) : null,
  querySelectorAll: () => [],
  documentElement: {},
};
global.window = {devicePixelRatio: 1, addEventListener: () => {}};
global.getComputedStyle = () => ({getPropertyValue: () => ''});
global.setInterval = () => 0;
// **/api/worldidx에만** 이 페이로드를 준다 — 같은 스크립트의 다른 로더(가격·시장·
// 반도체·옵션)까지 같은 응답을 받으면 무엇을 검증했는지 알 수 없다.
global.fetch = async (u) => {
  const mine = String(u).indexOf('/api/worldidx') >= 0;
  return {ok: mine && !fail, json: async () => (mine ? payload : {})};
};

(async () => {
  try {
    eval(code);
    await new Promise(r => setTimeout(r, 30));   // loadWorldidx()가 await를 끝내도록
    console.log(JSON.stringify({
      ok: true,
      body: (els['gsec-body'] || {}).innerHTML || '',
      dig: (els['gsec-dig'] || {}).textContent || '',
      foot: (els['gsec-foot'] || {}).textContent || '',
      display: ((els['gsec'] || {}).style || {}).display,
    }));
  } catch (e) { console.log(JSON.stringify({error: String(e && e.stack || e)})); }
})();
"""


def _it(key, label, value, unit, rate, sign, basis, src):
    """worldidx.Item 계약 그대로 — 키가 늘거나 줄면 프런트가 먼저 깨져야 한다."""
    return {"key": key, "label": label, "value": value, "unit": unit,
            "rate": rate, "sign": sign, "basis": basis, "src": src}


def _payload(**over):
    """2026-08-11 실측값(설계 문서의 원천 표)을 그대로 쓴다."""
    d = {"asof": "2026-08-11T21:40:00+09:00",
         "groups": [
             {"label": "미국 금리", "items": [
                 _it("ust2y", "2년", 4.25, "%", 1.43, "up", "08-10", "treasury"),
                 _it("ust10y", "10년", 4.72, "%", 1.51, "up", "08-10", "treasury"),
                 _it("ust30y", "30년", 5.25, "%", 0.0, "flat", "08-10", "treasury")]},
             {"label": "원자재", "items": [
                 _it("wti", "WTI", 82.13, "$/bbl", 0.77, "up", "08-10", "fdr"),
                 _it("gold", "금", 4361.80, "$/oz", 1.67, "up", "08-10", "fdr")]},
             {"label": "해외지수", "items": [
                 _it("spx", "S&P500", 7753.11, "idx", -0.06, "down", "08-11", "kis"),
                 _it("comp", "나스닥", 26605.36, "idx", 0.31, "up", "08-11", "kis"),
                 _it("vix", "VIX", 15.54, "idx", 0.52, "up", "08-11", "kis")]}]}
    d.update(over)
    return d


def _run(tmp_path, payload, fail=False):
    html = tmp_path / "dash.html"
    html.write_text(render_dashboard([], [], "2026-08-11"), encoding="utf-8")
    data = tmp_path / "world.json"
    data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    js = tmp_path / "h.js"
    js.write_text(_HARNESS, encoding="utf-8")
    argv = ["node", str(js), str(html), str(data)] + (["fail"] if fail else [])
    out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert "error" not in res, res["error"]
    return res


# ── 마크업(문자열) ────────────────────────────────────────────────────────

def test_section_is_collapsed_and_hidden_until_data_arrives():
    """접힌 채로, 데이터가 오기 전엔 숨어 있어야 한다 — 빈 껍데기 금지."""
    html = render_dashboard([], [], "2026-08-11")
    assert 'id="gsec"' in html
    head = html.split('id="gsec"')[0][-90:]
    assert "<details" in head and 'class="sec"' in head
    assert 'style="display:none"' in html.split('id="gsec"')[1][:120]
    assert "open" not in html.split('id="gsec"')[1].split(">")[0]   # 기본 접힘
    for marker in ("/api/worldidx", "loadWorldidx", 'id="gsec-body"',
                   'id="gsec-dig"'):
        assert marker in html, marker + " 누락"


def _js_function(script, name):
    """중괄호 깊이를 세어 함수 소스만 잘라낸다(정규식만으론 중첩 {}에서 깨짐)."""
    start = script.index("function " + name + "(")
    depth, i = 0, script.index("{", start)
    for i in range(i, len(script)):
        if script[i] == "{":
            depth += 1
        elif script[i] == "}":
            depth -= 1
            if depth == 0:
                break
    return script[start:i + 1]


def test_chip_renderer_reuses_the_market_chip_classes():
    """칩은 기존 시장 스트립(.mchip/.ml/.mv/.mr)을 그대로 쓴다 — 새 디자인 언어 금지.

    theme.py 단일 출처 원칙. 여기서 자기만의 칩 클래스를 만들면 같은 화면에 두 벌의
    칩 문법이 생긴다."""
    html = render_dashboard([], [], "2026-08-11")
    fn = _js_function(html, "gchip")
    for cls in ("mchip", "ml", "mv", "mr"):
        assert 'class="' + cls in fn or "'" + cls + " " in fn, cls + " 재사용 안 함"
    assert "$" not in fn, "칩 렌더가 통화기호를 직접 만든다 — 단위는 서버 unit 그대로"


# ── 실행 스모크(node) ─────────────────────────────────────────────────────

@needs_node
def test_every_chip_prints_its_own_basis(tmp_path):
    """**항목마다** 기준일. 그룹 하나에 한 번이 아니다 — 원천이 달라 날짜가 섞인다
    (재무부·FDR은 직전 영업일, KIS 지수는 당일). 살아 있는 코스피 칩 아래에서
    기준일 없는 숫자는 지금 값으로 읽힌다."""
    res = _run(tmp_path, _payload())
    assert res["display"] == ""                     # 데이터가 오면 섹션이 뜬다
    body = res["body"]
    assert body.count('class="mchip"') == 8         # 3 + 2 + 3
    assert body.count("기준 ") == 8                 # 칩 하나에 하나씩
    assert body.count("08-10") == 5                 # 미국채 3 + 원자재 2
    assert body.count("08-11") == 3                 # 해외지수 3
    for label in ("미국 금리", "원자재", "해외지수"):
        assert label in body, label + " 소제목 누락"


@needs_node
def test_units_are_printed_verbatim_from_the_server(tmp_path):
    """단위는 서버가 준 unit 그대로. 프런트가 '$'를 지어내지 않는다.

    설계 문서가 기각한 ETF 프록시(GLD $402)는 단위를 잘못 읽어 생긴 사고였다.
    '$82.13'처럼 앞에 붙이는 순간 배럴당인지 온스당인지가 화면에서 사라진다.
    'idx'는 표시 단위가 아니라 '단위 없음' 표식이므로 화면엔 안 나온다."""
    res = _run(tmp_path, _payload())
    body = res["body"]
    assert "4.72%" in body                          # %만 숫자에 붙는다
    assert "82.13" in body and "$/bbl" in body
    assert "4,361.80" in body and "$/oz" in body
    assert "$82.13" not in body and "$4,361.80" not in body   # 지어낸 통화기호 금지
    assert "7,753.11" in body and "idx" not in body


@needs_node
def test_collapsed_summary_carries_the_three_core_values(tmp_path):
    """접힌 상태에서 미국채 10Y·WTI·금이 한 줄에 보여야 한다 — 안 펼치고 훑는 용도.

    390px 헤드리스 실렌더 실측: 이 세 값은 306px, 제목·아이콘·셰브런을 뺀 한 줄
    가용폭은 ~218px다. 그래서 요약 안에서 **자기 줄로 접어**(324px) 셋을 다 남긴다 —
    한 줄에 욱여넣고 잘라내면 하필 마지막(금)이 사라진다(옵션 접힌 줄에서 겪은 함정).
    기준일은 이 줄에 넣지 않는다(폭이 없다) — 펼치면 칩마다 찍혀 있다."""
    dig = _run(tmp_path, _payload())["dig"]
    assert "미국채" in dig and "4.72%" in dig
    assert "WTI 82.13 $/bbl" in dig
    assert "금 4,361.80 $/oz" in dig
    assert "S&P500" not in dig and "VIX" not in dig   # 핵심 3개만


@needs_node
def test_section_hides_itself_when_the_api_fails(tmp_path):
    """API가 죽으면 섹션을 통째로 감춘다 — 빈 껍데기가 '데이터 없음'처럼 자리를
    차지하지 않게. groups가 비어 와도 같다."""
    res = _run(tmp_path, _payload(), fail=True)
    assert res["display"] == "none" and res["body"] == ""
    res2 = _run(tmp_path, _payload(groups=[]))
    assert res2["display"] == "none" and res2["body"] == ""


@needs_node
def test_one_dead_source_does_not_take_the_others_down(tmp_path):
    """한 원천이 죽어 그룹이 빠져도 나머지는 뜬다(칩 스트립의 기존 원칙).
    핵심 3개가 통째로 없으면 요약 줄은 비운다 — 없는 값을 지어내지 않는다."""
    only_idx = _payload()["groups"][2:]
    res = _run(tmp_path, _payload(groups=only_idx))
    assert res["display"] == ""
    assert res["body"].count('class="mchip"') == 3 and "해외지수" in res["body"]
    assert res["dig"] == ""


@needs_node
def test_unknown_rate_and_basis_render_a_dash_not_a_fake_zero(tmp_path):
    """모르는 값을 0.00%(보합)나 오늘 날짜로 꾸미지 않는다.

    등락률 None은 fxchip·loadSemi와 같은 관행으로 대시. 기준일 None(KIS output2가
    비어 오는 종목)도 대시다 — 날짜를 추측해 찍으면 기준일을 실은 이유가 무너진다."""
    one = [{"label": "원자재", "items": [
        _it("wti", "WTI", 82.13, "$/bbl", None, "flat", None, "fdr")]}]
    res = _run(tmp_path, _payload(groups=one))
    assert "–" in res["body"] and "0.00%" not in res["body"]
    assert "기준 –" in res["body"]


@needs_node
def test_footer_names_the_sources_and_the_query_time(tmp_path):
    """각주는 원천과 조회 시각을 숨기지 않는다 — 이 값들이 실시간이 아님을 말한다."""
    foot = _run(tmp_path, _payload())["foot"]
    assert "재무부" in foot and "KIS" in foot
    assert "21:40" in foot                          # asof(KST)에서 시:분
    assert "실시간" in foot
