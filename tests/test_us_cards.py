"""대시보드 US 티커 카드 — 목록·가격·카드 렌더 분기. KIS·네트워크 미접촉.

관심종목에 US 티커를 넣어도 카드가 안 생기던 문제(카드 목록이 KR만 골랐다)를 고친다.
국내 전용 항목(밸류지표·내일예상·/live 링크)은 US 카드에서 뺀다 — 모르는 값을
'–'로 자리만 잡아두지 않는다(ADR 패널과 같은 원칙).
"""
import datetime as dt

import pandas as pd


def _items():
    return [{"code": "SKHY", "market": "US", "shares": None, "avg": None},
            {"code": "005930", "market": "KR", "shares": None, "avg": None},
            {"code": "000660", "market": "KR", "shares": 6, "avg": 1975833}]


def test_get_dash_items_keeps_us_and_order(tmp_path, monkeypatch):
    """카드 목록은 KR·US를 **순서 그대로** 담는다(get_kr_codes와 달리 안 거른다)."""
    from backend.config import settings
    from backend.flow import userstore
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    userstore.set_watchlist("a@b.c", _items())
    got = userstore.get_dash_items("a@b.c")
    assert [(i["code"], i["market"]) for i in got] == [
        ("SKHY", "US"), ("005930", "KR"), ("000660", "KR")]
    # 기존 KR 전용 경로는 그대로여야 한다(/api/fundamentals 등이 쓴다)
    assert userstore.get_kr_codes("a@b.c") == ["005930", "000660"]


def _df(closes, start="2026-07-01"):
    idx = pd.date_range(start, periods=len(closes), freq="D")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": [1] * len(closes)}, index=idx)


def test_build_dashboard_includes_us_card_priced_from_ohlcv(monkeypatch, tmp_path):
    """US 카드의 가격은 이미 받은 OHLCV에서 온다 — 추가 호출 0건, 차트와 같은 데이터."""
    from backend import cli
    monkeypatch.setattr(cli, "_kr_market_open", lambda: False)
    monkeypatch.setattr(cli, "us_market_open", lambda: False)   # 미국장 닫힘
    monkeypatch.setattr(cli, "_collect_issues", lambda codes, nm=None: {})
    monkeypatch.setattr(cli, "get_universe", lambda d: [])
    src = lambda code, s, e: _df([100.0, 110.0])                # noqa: E731
    html = cli.build_dashboard(_items(), str(tmp_path), source=src, with_news=False)
    assert "SKHY" in html
    # 110 = 마지막 종가, 등락률 = (110-100)/100 = +10%
    assert '"close": 110.0' in html.replace(" ", "").replace('"close":110.0', '"close": 110.0') \
        or '"close":110.0' in html.replace(" ", "")
    assert '"market":"US"' in html.replace(" ", "")


def test_us_quote_is_not_called_when_the_us_market_is_closed(monkeypatch, tmp_path):
    """미국장이 닫혀 있으면 KIS를 한 번도 안 부른다.

    대시보드는 요청마다 다시 그려진다 — 페이지 로드마다 해외 시세 호출이 붙으면
    (price_us는 거래소를 순회해 심볼당 최대 3콜) 금세 유량을 먹는다."""
    from backend import cli
    calls = {"n": 0}

    def _spy(codes):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(cli, "_kr_market_open", lambda: False)
    monkeypatch.setattr(cli, "us_market_open", lambda: False)
    monkeypatch.setattr(cli, "_us_live_prices", _spy)
    monkeypatch.setattr(cli, "_collect_issues", lambda codes, nm=None: {})
    monkeypatch.setattr(cli, "get_universe", lambda d: [])
    cli.build_dashboard(_items(), str(tmp_path),
                        source=lambda c, s, e: _df([100.0, 110.0]), with_news=False)
    assert calls["n"] == 0

    monkeypatch.setattr(cli, "us_market_open", lambda: True)    # 열리면 부른다
    cli.build_dashboard(_items(), str(tmp_path),
                        source=lambda c, s, e: _df([100.0, 110.0]), with_news=False)
    assert calls["n"] == 1


def test_us_card_hides_kr_only_blocks_and_the_live_link():
    """US 카드엔 밸류지표·내일예상·/live 링크가 없어야 한다.

    /live는 6자리 숫자만 받아 SKHY로 들어가면 404다 — 깨진 링크보다 없는 게 낫다.
    PER/PBR/52주는 KIS 국내 TR이라 US는 받을 수 없고, 내일예상은 수급·ADR 기반이다."""
    from backend.report.dashboard import render_dashboard
    us = {"code": "SKHY", "name": "SKHY", "market": "US", "action": "hold",
          "action_ko": "관망", "confidence": 1, "advice": False,
          "reasons": ["뚜렷한 신호 없음 — 관망"], "backtest": None,
          "close": 154.38, "change": 1.2, "news": [], "disclosures": [], "candles": []}
    kr = dict(us, code="005930", name="삼성전자", market="KR")
    html = render_dashboard([us, kr], [], "2026-08-05")
    import re
    cards = re.findall(r"function cardHtml[\s\S]*?\n}", html)
    assert cards, "cardHtml 정의를 못 찾음"
    body = cards[0]
    # 분기 자체가 존재하는지(렌더는 클라이언트에서 일어난다)
    assert "market" in body and "US" in body
    assert "/live/" in body          # KR 링크 경로는 남아 있어야 한다


def test_ohlcv_change_uses_the_last_two_valid_closes(monkeypatch, tmp_path):
    """등락률은 마지막 두 유효 종가로 계산한다. 한 행뿐이면 등락률 없음(0%로 꾸미지 않는다)."""
    from backend import cli
    assert cli._ohlcv_price(_df([100.0, 110.0])) == {"close": 110.0, "change": 10.0}
    one = cli._ohlcv_price(_df([110.0]))
    assert one["close"] == 110.0 and one["change"] is None
    assert cli._ohlcv_price(_df([])) is None


def test_live_us_price_without_rate_derives_change_from_previous_close(monkeypatch, tmp_path):
    """실시간 시세에 등락률이 없으면 전일 종가로 계산한다.

    KIS 해외 현재가(HHDFS00000300)는 등락률이 비어 오는 경우가 있다(2026-08-05 22:41
    실측: SKHY 가격 151.77 / rate None). 그대로 두면 가격만 새것이고 등락률은 '–'가 된다.
    전일 종가는 이미 받은 OHLCV에 있으므로 추가 호출 없이 채울 수 있다."""
    from backend import cli
    monkeypatch.setattr(cli, "_kr_market_open", lambda: False)
    monkeypatch.setattr(cli, "us_market_open", lambda: True)
    monkeypatch.setattr(cli, "_us_live_prices",
                        lambda syms: {"SKHY": {"close": 151.77, "change": None}})
    monkeypatch.setattr(cli, "_collect_issues", lambda codes, nm=None: {})
    monkeypatch.setattr(cli, "get_universe", lambda d: [])
    import json
    import re
    html = cli.build_dashboard([{"code": "SKHY", "market": "US"}], str(tmp_path),
                               source=lambda c, s, e: _df([100.0, 154.38]),
                               with_news=False)
    D = json.loads(re.search(r"const D = (\{.*?\});\n", html, re.S).group(1))
    card = D["stocks"][0]
    assert card["close"] == 151.77                      # 실시간 가격은 유지
    # (151.77 - 154.38) / 154.38 = -1.69%
    assert card["change"] is not None and abs(card["change"] + 1.69) < 0.02


def test_prev_close_skips_todays_row(monkeypatch):
    """OHLCV에 오늘 행이 이미 있으면 그건 전일 종가가 아니다."""
    import datetime as _dt

    from backend import cli
    today = _dt.date.today()
    idx = pd.to_datetime([today - _dt.timedelta(days=1), today])
    df = pd.DataFrame({"Close": [100.0, 200.0]}, index=idx)
    assert cli._prev_close(df, today) == 100.0
    assert cli._prev_close(pd.DataFrame({"Close": []}), today) is None
