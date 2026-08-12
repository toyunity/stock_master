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
// 폴링 주기를 **로더 이름과 함께** 기록한다. 주기만 모으면 이 페이지의 다른 로더
// (loadSemi·marketPulse가 60초, loadOptions·loadFundamentals·loadOutlook이 5분)와
// 구별되지 않아, worldidx 주기를 검사하려던 단언이 남의 타이머를 보게 된다.
const timers = [];
global.setInterval = (fn, ms) => {
  timers.push({fn: (fn && fn.name) || '?', ms: ms});
  return timers.length;
};
global.clearInterval = () => {};
// **/api/worldidx에만** 이 페이로드를 준다 — 같은 스크립트의 다른 로더(가격·시장·
// 반도체·옵션)까지 같은 응답을 받으면 무엇을 검증했는지 알 수 없다.
const mkt = process.argv[5] ? JSON.parse(process.argv[5]) : null;
global.fetch = async (u) => {
  const s = String(u);
  if (s.indexOf('/api/worldidx') >= 0) return {ok: !fail, json: async () => payload};
  if (mkt && s.indexOf('/api/market') >= 0) return {ok: true, json: async () => mkt.market};
  if (mkt && s.indexOf('/api/futures') >= 0) return {ok: true, json: async () => mkt.futures};
  if (mkt && s.indexOf('/api/kospi-temp') >= 0) return {ok: true, json: async () => mkt.temp};
  return {ok: false, json: async () => ({})};
};

(async () => {
  try {
    eval(code);
    await new Promise(r => setTimeout(r, 60));   // loadMarket + loadWorldidx 둘 다
    console.log(JSON.stringify({
      ok: true,
      body: (els['gsec-body'] || {}).innerHTML || '',
      dig: (els['gsec-dig'] || {}).textContent || '',
      foot: (els['gsec-foot'] || {}).textContent || '',
      display: ((els['gsec'] || {}).style || {}).display,
      timers: timers,
    }));
  } catch (e) { console.log(JSON.stringify({error: String(e && e.stack || e)})); }
})();
"""


def _it(key, label, value, unit, rate, sign, basis, src, basis_kind="date",
        rate_unit="%"):
    """worldidx.Item 계약 그대로 — 키가 늘거나 줄면 프런트가 먼저 깨져야 한다."""
    return {"key": key, "label": label, "value": value, "unit": unit,
            "rate": rate, "sign": sign, "basis": basis, "src": src,
            "rate_unit": rate_unit, "basis_kind": basis_kind}


def _payload(**over):
    """2026-08-11 실측값(설계 문서의 원천 표)을 그대로 쓴다."""
    d = {"asof": "2026-08-11T21:40:00+09:00",
         "groups": [
             {"label": "미국 금리", "items": [
                 _it("ust2y", "2년", 4.25, "%", 1.43, "up", "08-10", "treasury",
                     rate_unit="bp"),
                 _it("ust10y", "10년", 4.72, "%", 1.51, "up", "08-10", "treasury",
                     rate_unit="bp"),
                 _it("ust30y", "30년", 5.25, "%", 0.0, "flat", "08-10", "treasury",
                     rate_unit="bp")]},
             {"label": "원자재", "items": [
                 _it("wti", "WTI", 82.13, "$/bbl", 0.77, "up", "08-10", "fdr"),
                 _it("gold", "금", 4361.80, "$/oz", 1.67, "up", "08-10", "fdr")]},
             {"label": "해외지수", "items": [
                 _it("spx", "S&P500", 7753.11, "idx", -0.06, "down", "08-11", "kis"),
                 _it("comp", "나스닥 종합", 26605.36, "idx", 0.31, "up", "08-11", "kis"),
                 _it("vix", "VIX", 15.54, "idx", 0.52, "up", "08-11", "kis")]}]}
    d.update(over)
    return d


def _run(tmp_path, payload, fail=False, mkt=None):
    html = tmp_path / "dash.html"
    html.write_text(render_dashboard([], [], "2026-08-11"), encoding="utf-8")
    data = tmp_path / "world.json"
    data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    js = tmp_path / "h.js"
    js.write_text(_HARNESS, encoding="utf-8")
    argv = ["node", str(js), str(html), str(data), "fail" if fail else "-"]
    if mkt is not None:
        argv.append(json.dumps(mkt, ensure_ascii=False))
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
def test_every_chip_prints_its_own_freshness(tmp_path):
    """**항목마다** 신선도 줄. 그룹 하나에 한 번이 아니다 — 원천이 달라 상태가 섞인다.

    살아 있는 코스피 칩 아래에서 상태 없는 숫자는 지금 값으로 읽힌다. 재무부는
    일 1회 '확정'이고 나머지 date는 '마감'이다 — 문구를 가르는 건 src다."""
    res = _run(tmp_path, _payload())
    assert res["display"] == ""                     # 데이터가 오면 섹션이 뜬다
    body = res["body"]
    assert body.count('class="gb"') == 8            # 3 + 2 + 3, 칩 하나에 하나씩
    assert body.count("08-10 확정") == 3            # 미국채(treasury)
    assert body.count("08-10 마감") == 2            # 원자재(fdr)
    assert body.count("08-11 마감") == 3            # 해외지수(kis)
    assert "기준 " not in body                      # 옛 문구는 사라져야 한다
    for label in ("미국 금리", "원자재", "해외지수"):
        assert label in body, label + " 소제목 누락"


@needs_node
def test_live_items_say_so_instead_of_printing_a_date(tmp_path):
    """basis_kind=live면 날짜가 아니라 상태를 찍는다.

    FDR 마지막 봉은 진행 중 세션이라 값은 실시간인데 야후가 하루 전 날짜를 찍는다 —
    그 날짜를 그대로 보여주면 살아 있는 값이 어제 종가로 읽힌다(정반대 착시)."""
    live = [{"label": "원자재", "items": [
        _it("wti", "WTI", 83.51, "$/bbl", 0.37, "up", "08-11", "fdr",
            basis_kind="live")]},
        {"label": "미국 금리", "items": [
            _it("ust10y", "10년", 4.69, "%", 0.6, "up", "08-11", "cnbc",
                basis_kind="live", rate_unit="bp")]}]
    body = _run(tmp_path, _payload(groups=live))["body"]
    assert body.count("실시간(지연)") == 2
    assert "08-11" not in body                      # live면 날짜를 안 찍는다
    assert "4.69%" in body and "0.6bp" in body


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
    assert "– 마감" in res["body"]                  # 기준일을 모르면 대시


@needs_node
def test_footer_names_the_sources_and_the_query_time(tmp_path):
    """각주는 원천과 조회 시각을 숨기지 않는다 — 이 값들이 무지연이 아님을 말한다."""
    foot = _run(tmp_path, _payload())["foot"]
    assert "재무부" in foot and "KIS" in foot
    assert "21:40" in foot                          # asof(KST)에서 시:분
    assert "지연" in foot


@needs_node
def test_footer_names_tradeweb_when_the_yields_are_live(tmp_path):
    """CNBC로 승격된 동안은 각주도 그렇게 말한다 — 원천을 숨기지 않는다."""
    live = [{"label": "미국 금리", "items": [
        _it("ust10y", "10년", 4.69, "%", 0.6, "up", "08-11", "cnbc",
            basis_kind="live", rate_unit="bp")]}]
    foot = _run(tmp_path, _payload(groups=live))["foot"]
    assert "Tradeweb" in foot and "재무부" not in foot


# ── 국내 두 그룹 미러링 ───────────────────────────────────────────────────

def _mkt():
    """/api/market + /api/futures + /api/kospi-temp 실응답 모양(장중)."""
    return {"market": {"kospi": {"price": 6525.01, "rate": 3.0},
                       "kosdaq": {"price": 856.4, "rate": -0.17}},
            "futures": {"k200": {"label": "K200선물", "price": 880.25,
                                 "rate": 2.8, "closed": False},
                        "nq": {"label": "나스닥 선물", "price": 29641.0,
                               "rate": -0.34}},
            "temp": {"asof": "2026-08-12T12:50:00+09:00", "items": [
                {"key": "ma_gap", "label": "100일 평균", "value": -6.34,
                 "unit": "%", "verdict": "눌림"},
                {"key": "ema_gap", "label": "12일 평균", "value": 2.63,
                 "unit": "%", "verdict": "위"},
                {"key": "down_avg", "label": "하락폭(20일)", "value": 4.99,
                 "unit": "%p", "verdict": "거침"}]}}


@needs_node
def test_domestic_chips_are_mirrored_into_the_section(tmp_path):
    """상단 스트립의 칩이 섹션 안에도 뜬다 — 이동이 아니라 미러링이다.

    새 API 호출은 없다. loadMarket이 이미 받아온 마지막 응답을 섹션이 읽어 쓰므로
    두 곳이 같은 순간의 같은 값을 그린다."""
    res = _run(tmp_path, _payload(), mkt=_mkt())
    body = res["body"]
    assert "국내 지수" in body and "지수 선물" in body
    # 국내 2 + 코스피 온도 3 + 선물 2 + 미국 금리 3 + 원자재 2 + 해외지수 3
    assert body.count('class="mchip"') == 15
    for txt in ("코스피", "코스닥", "K200선물", "나스닥 선물"):
        assert txt in body, txt + " 미러링 누락"
    # 국내 그룹이 맨 앞이다
    assert body.index("국내 지수") < body.index("지수 선물") < body.index("미국 금리")


@needs_node
def test_futures_chip_freshness_comes_from_the_server_flags(tmp_path):
    """마감·지연은 서버가 주는 closed·stale 플래그가 정한다 — 프런트가 안 지어낸다."""
    m = _mkt()
    m["futures"]["k200"]["closed"] = True
    m["futures"]["nq"]["stale"] = True
    body = _run(tmp_path, _payload(), mkt=m)["body"]
    assert "마감" in body and "지연" in body


@needs_node
def test_section_shows_up_on_domestic_alone_when_every_remote_source_dies(tmp_path):
    """해외 원천이 다 죽어도 코스피는 보여야 한다 — 그룹이 하나라도 있으면 뜬다.

    코스피 온도도 함께 남는다: /api/kospi-temp는 worldidx와 다른 원천이라 저쪽이
    통째로 죽어도 살아 있다."""
    res = _run(tmp_path, _payload(groups=[]), mkt=_mkt())
    assert res["display"] == ""
    assert res["body"].count('class="mchip"') == 7      # 국내 2 + 온도 3 + 선물 2
    assert "미국 금리" not in res["body"]


@needs_node
def test_section_still_hides_when_absolutely_nothing_is_available(tmp_path):
    """전부 비면 종전대로 감춘다 — 빈 껍데기가 '데이터 없음'처럼 자리 차지 금지."""
    res = _run(tmp_path, _payload(groups=[]))
    assert res["display"] == "none" and res["body"] == ""


@needs_node
def test_worldidx_poll_does_not_erase_the_domestic_groups(tmp_path):
    """두 로더가 주기가 달라도 한 렌더 함수를 쓴다.

    합치지 않으면 worldidx 폴링(느림)이 국내 그룹(빠름)을 덮어써서 지운다."""
    res = _run(tmp_path, _payload(), mkt=_mkt())
    assert "코스피" in res["body"] and "미국 금리" in res["body"]


# ── 폴링 주기 ─────────────────────────────────────────────────────────────

@needs_node
def test_polling_is_slow_while_the_section_is_collapsed(tmp_path):
    """접히면 5분, 펼치면 60초.

    접힌 줄의 세 값은 분 단위로 안 변한다. 아무도 안 보는 값에 CNBC를 분당 3콜씩
    때릴 이유가 없다. (서버 캐시가 실제 원격 호출량을 정하므로 60초 폴링이 CNBC
    호출을 늘리지는 않지만, 굳이 두드릴 이유도 없다.)"""
    res = _run(tmp_path, _payload(), mkt=_mkt())    # 하니스 mock은 open:false
    # **worldidx 타이머만** 본다. 이 페이지엔 loadSemi·marketPulse가 이미 60초로
    # 돌고 있어, 주기 목록 전체에서 60000을 찾으면 남의 타이머를 보게 된다.
    widx = [t["ms"] for t in res["timers"] if t["fn"] == "loadWorldidx"]
    assert widx == [300000], res["timers"]          # 접힘 = 5분, 타이머는 하나뿐
    assert 60000 not in widx, "접힌 채로 60초 폴링 — 접힘 분기 없음"


def test_section_registers_a_toggle_listener():
    """펼침/접힘 전환에 주기를 다시 잡으려면 toggle을 들어야 한다."""
    html = render_dashboard([], [], "2026-08-11")
    assert "'toggle'" in html or '"toggle"' in html
    assert "widxSchedule" in html


@needs_node
def test_kospi_temperature_group_sits_right_after_the_domestic_index(tmp_path):
    """읽는 순서 — '코스피 6,525' 다음에 '그게 최근 대비 어디쯤인가'."""
    body = _run(tmp_path, _payload(), mkt=_mkt())["body"]
    assert "코스피 온도" in body
    assert body.index("국내 지수") < body.index("코스피 온도") < body.index("지수 선물")
    assert body.count('class="mchip"') == 15        # 2 + 3 + 2 + 3 + 2 + 3


@needs_node
def test_verdict_sits_next_to_the_value_not_on_the_freshness_line(tmp_path):
    """판정은 값 옆에, 세 번째 줄은 다른 칩과 똑같이 신선도.

    .gb를 판정에 내주면 한 섹션 안에서 같은 줄이 두 가지를 뜻하게 된다 — 이 저장소가
    반복해서 잡아온 '라벨이 조용히 틀리는' 결함과 같은 부류다."""
    body = _run(tmp_path, _payload(), mkt=_mkt())["body"]
    for w in ("눌림", "위", "거침"):
        assert w in body, w + " 판정 누락"
    # 판정 단어가 신선도 줄에 들어가지 않았는지 — .gb 안엔 실시간/마감/기준일만 온다.
    import re
    for gb in re.findall(r'<div class="gb">([^<]*)</div>', body):
        assert "눌림" not in gb and "거침" not in gb, gb
    assert body.count('class="gb"') == 15           # 칩마다 하나씩, 높이 균일


@needs_node
def test_verdict_is_colourless(tmp_path):
    """판정에 up/down 색을 쓰지 않는다 — 이격도가 음수라고 '나쁨'이 아니다."""
    body = _run(tmp_path, _payload(), mkt=_mkt())["body"]
    i = body.index("눌림")
    seg = body[max(0, i - 120):i]
    assert 'class="mr up"' not in seg and 'class="mr down"' not in seg


@needs_node
def test_temperature_group_vanishes_when_its_source_dies(tmp_path):
    """items=[]면 그 그룹만 빠지고 나머지는 그대로 뜬다."""
    m = _mkt()
    m["temp"] = {"asof": "2026-08-12T12:50:00+09:00", "items": []}
    body = _run(tmp_path, _payload(), mkt=m)["body"]
    assert "코스피 온도" not in body
    assert "국내 지수" in body and "지수 선물" in body
    assert body.count('class="mchip"') == 12
