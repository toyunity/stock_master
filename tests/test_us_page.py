"""US 티커 상세 화면 — 라우트 확장·렌더·국내 전용 관문 유지. 설계 2026-08-06.

핵심 불변식 두 가지:
  · 넓히는 라우트는 **3곳뿐**이다(/live · /api/candles · /api/watch).
    국내 전용 TR을 쓰는 라우트가 US 코드를 받으면 KIS 호출이 실패하므로 404가 맞다.
  · US 화면엔 국내 전용 패널이 **아예 안 그려진다**(빈 채로 두지 않는다).
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cli(tmp_path, monkeypatch):
    from backend.api.app import create_app
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_enabled", False)
    with TestClient(create_app()) as c:
        yield c


# ── 라우트 판정 ───────────────────────────────────────────────────

def test_us_ticker_opens_a_page(cli):
    r = cli.get("/live/SKHY")
    assert r.status_code == 200 and "SKHY" in r.text


def test_kr_code_still_opens_the_domestic_page(cli):
    """기존 화면이 그대로여야 한다 — 수급 섹션이 살아 있는지로 확인."""
    r = cli.get("/live/005930")
    assert r.status_code == 200 and "수급" in r.text


def test_garbage_symbol_is_404(cli):
    assert cli.get("/live/ZZZZZZZZ").status_code == 404      # 6자 초과 티커 형식 아님
    assert cli.get("/live/00566").status_code == 404         # 5자리 숫자


# ── 넓힌 라우트 ───────────────────────────────────────────────────

def test_us_daily_candles_route_is_open(cli, monkeypatch):
    """일봉은 FDR 경로라 US로도 된다 — 네트워크는 안 탄다(주입)."""
    from backend.flow import candles
    monkeypatch.setattr(candles, "_daily_candles",
                        lambda code: [{"t": 1, "open": 1, "high": 2, "low": 1,
                                       "close": 2, "vol": 10}])
    r = cli.get("/api/candles/SKHY?tf=1d")
    assert r.status_code == 200 and len(r.json()["candles"]) == 1


def test_us_weekly_monthly_candles_route_is_open(cli, monkeypatch):
    """주·월봉도 FDR 집계 경로(KIS 무관)라 US로 열린다 — 네트워크는 안 탄다(주입)."""
    from backend.flow import candles
    monkeypatch.setattr(candles, "_long_daily_bars",
                        lambda code: [{"t": "2026-08-03", "open": 1, "high": 2,
                                       "low": 1, "close": 2, "vol": 10},
                                      {"t": "2026-08-04", "open": 2, "high": 3,
                                       "low": 2, "close": 3, "vol": 20}])
    for tf in ("1w", "1mo"):
        r = cli.get(f"/api/candles/SKHY?tf={tf}")
        assert r.status_code == 200, tf
        assert len(r.json()["candles"]) == 1          # 같은 주·같은 달 → 한 봉으로 합침
        assert r.json()["candles"][0]["vol"] == 30


def test_us_minute_candles_are_refused_not_faked(cli):
    """분봉은 KIS 국내 전용이다. 빈 배열로 얼버무리지 않고 400으로 거절한다 —
    '차트가 비었다'와 '이 시장엔 없다'는 화면에서 구분돼야 한다."""
    r = cli.get("/api/candles/SKHY?tf=5m")
    assert r.status_code == 400
    assert "미국" in r.json()["error"]


def test_lowercase_ticker_is_normalized_by_the_route(cli):
    """소문자 티커로 부르면 저장 키가 갈린다 — market_of는 내부에서 대문자로 재봐서
    통과시키는데, 저장은 원문 그대로라 감시선이 "aapl" 키에 들어간다. 화면은 항상
    대문자로 조회하므로 그 값은 영영 안 보이고, 일봉 캐시도 aapl.parquet /
    AAPL.parquet 두 벌로 갈린다. 정규화는 진입점(라우트)에서 한 번에 한다."""
    p = cli.post("/api/watch/skhy", json={"lines": [{"price": 100.5, "label": "저점"}]})
    assert p.status_code == 200
    assert cli.get("/api/watch/SKHY").json()["lines"] == [{"price": 100.5, "label": "저점"}]


def test_us_watch_lines_roundtrip_keeps_cents(cli):
    p = cli.post("/api/watch/SKHY", json={"lines": [{"price": 153.16, "label": "절대선"}]})
    assert p.status_code == 200 and p.json()["lines"][0]["price"] == 153.16
    g = cli.get("/api/watch/SKHY")
    assert g.json()["lines"] == [{"price": 153.16, "label": "절대선"}]


# ── 국내 전용 관문은 그대로 ────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/asking/SKHY", "/api/financials/SKHY",
                                  "/api/live/SKHY/stream"])
def test_domestic_only_routes_still_reject_us(cli, path):
    """넓힌 게 3곳뿐임을 못박는다. 여기가 열리면 KIS 국내 TR에 US 코드가 들어가
    조용히 실패하거나(빈 화면) 엉뚱한 종목을 물어온다."""
    assert cli.get(path).status_code == 404


# ── 렌더 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("wiring", [
    "/api/asking/",        # 호가 폴링
    "/api/financials/",    # 기업 체력
    "/api/live/",          # SSE 수급 스트림
    'id="finsec"',         # 기업 체력 패널
    'id="ob"',             # 호가 패널
])
def test_us_page_wires_up_no_domestic_source(cli, wiring):
    """없는 데이터를 자리만 잡아두지 않는다(ADR 패널·US 카드와 같은 원칙).

    **단어가 아니라 배선을 본다.** 화면 하단의 '이 화면에 없는 것' 안내문이
    그 단어들을 일부러 쓰기 때문에 단어 검사는 통과할 수 없다 — 실제로 확인할 것은
    국내 전용 엔드포인트를 부르거나 그 패널을 그리지 않는다는 사실이다."""
    assert wiring not in cli.get("/live/SKHY").text


def test_us_page_keeps_chart_and_watch_lines(cli):
    html = cli.get("/live/SKHY").text
    assert "감시선" in html and "pchart" in html


def test_us_page_says_why_things_are_missing(cli):
    """빈 섹션을 지우기만 하면 '왜 없지?'가 남는다 — 한 줄로 답해준다."""
    assert "국내 종목에만" in cli.get("/live/SKHY").text


def test_us_page_has_no_minute_timeframe_buttons(cli):
    """분봉이 없으므로 탭도 없다 — 눌렀는데 빈 차트보다 버튼이 없는 게 낫다."""
    html = cli.get("/live/SKHY").text
    assert "tf=5m" not in html and ">5분<" not in html


def test_us_page_has_daily_weekly_monthly_tabs(cli):
    """일·주·월봉 탭은 있다(분봉만 없다) — 기본 선택은 일봉."""
    html = cli.get("/live/SKHY").text
    assert 'data-tf="1w"' in html and 'data-tf="1mo"' in html
    assert ">주봉<" in html and ">월봉<" in html
    assert 'class="tf-btn on" type="button" data-tf="1d"' in html


def test_dashboard_us_card_links_to_the_detail_page(cli):
    """카드에서 상세로 갈 수 있어야 한다 — 화면을 만들어 놓고 문을 안 달면 소용없다.
    (예전엔 US가 404라 일부러 링크를 뺐다. 그 결정을 여기서 되돌린다.)"""
    from backend.report.dashboard import render_dashboard
    us = {"code": "SKHY", "name": "SKHY", "market": "US", "action": "hold",
          "action_ko": "관망", "confidence": 1, "advice": False,
          "reasons": ["관망"], "backtest": None, "close": 154.38, "change": 1.2,
          "news": [], "disclosures": [], "candles": []}
    html = render_dashboard([us], [], "2026-08-06")
    assert "'<a class=\"name\" href=\"/live/'" in html or "/live/" in html


def test_no_placeholder_survives_the_render():
    """치환 안 된 __PLACEHOLDER__가 남아 있으면 안 된다.

    실제로 났던 사고(2026-08-06): `lib`을 읽어놓고 `.replace("__LIB__", lib)`를
    빠뜨려 차트 라이브러리가 통째로 안 실렸다. 브라우저에선
    `ReferenceError: __LIB__ is not defined`로 스크립트가 즉사해 화면이 '불러오는 중'에
    멈췄는데, **node 실행 테스트는 LightweightCharts를 가짜로 주입하기 때문에 통과했다.**
    가짜가 채워주는 자리는 가짜 테스트로 지킬 수 없다 — 렌더 결과를 직접 본다.

    여기선 '자리표시자가 남았나'까지만 본다. 채워진 게 **진짜 라이브러리인지**는
    test_chart_lib.py가 node로 실행해 확인한다(빈 파일·잘린 파일은 자리표시자를
    남기지 않아 이 테스트를 그냥 통과한다)."""
    import re
    from backend.report.dashboard import render_dashboard
    from backend.report.live_page import render_live_page
    from backend.report.scanner_page import render_scanner_page
    from backend.report.us_page import render_us_page
    from backend.report.widget_setup import render_widget_setup
    # 대시보드도 __LIB__를 심는다 — 처음엔 빠져 있어 같은 사고를 다시 맞을 자리였다
    for html in (render_us_page("SKHY", "SKHY"),
                 render_live_page("005930", "삼성전자", "demo"),
                 render_scanner_page(),
                 render_widget_setup("t" * 32, "https://x"),
                 render_dashboard([], [], "2026-08-10", pwa=True)):
        left = set(re.findall(r"__[A-Z][A-Z0-9_]*__", html))
        assert not left, left


@pytest.mark.parametrize("render", ["live", "us"])
def test_watch_label_cannot_inject_a_placeholder(tmp_path, monkeypatch, render):
    """감시선 라벨이 자리표시자 문자열이어도 치환되면 안 된다.

    `.replace()` 체인은 앞 단계가 넣은 문자열을 뒤 단계가 **다시 스캔**한다. 사용자
    데이터를 자산(__LIB__ = 400KB 차트 라이브러리)보다 먼저 넣으면, 라벨이
    "__LIB__"일 때 라이브러리 본문이 JSON 안으로 주입돼 페이지 JS가 통째로 죽는다.
    그러면 감시선 편집기가 **그 죽은 페이지 안에만** 있어 자력 복구가 불가능하다
    (data/cache/users/<hash>.json을 손으로 고쳐야 한다).

    라벨은 자유 문자열이다(watch.py:106 검증 통과, 최대 20자) — 막을 곳은 렌더 쪽뿐.
    줄 길이 assert는 쓰지 말 것: 주입본이 첫 줄에서 개행돼 오히려 짧아진다(실측)."""
    import re
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node 미설치 — JS 문법 게이트 생략")
    from backend.config import settings
    from backend.flow import userstore
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    code = "000660" if render == "live" else "SKHY"
    userstore.set_lines("x@y.com", code, [{"price": 200000, "label": "__LIB__"}])
    if render == "live":
        from backend.report.live_page import render_live_page
        html = render_live_page(code, "SK하이닉스", "live", "x@y.com")
    else:
        from backend.report.us_page import render_us_page
        html = render_us_page(code, code, "x@y.com")
    src = next(s for s in re.findall(r"<script>([\s\S]*?)</script>", html)
               if "loadCandles" in s)
    js = tmp_path / "page.js"
    js.write_text(src, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, "라벨이 자산 자리표시자를 주입했다:\n" + r.stderr[:400]
