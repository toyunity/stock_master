"""미국 시세 거래소 순회(NAS→NYS→AMS)·이름·캐시 — 설계 2026-07-17 §3.
⚠ 실제 KIS 호출 금지 — 모킹된 client(_C)로 거래소 순회·유효판정만 검증."""
import asyncio


class _C:
    def __init__(self, ok):
        self.ok = ok
        self.calls = []

    async def _get(self, path, tr, params):
        self.calls.append(params["EXCD"])
        if params["EXCD"] == self.ok:
            return {"rt_cd": "0", "output": {"last": "189.70", "rate": " -0.85",
                                             "sign": "5", "tvol": "1"}}
        return {"rt_cd": "0", "output": {"last": "0"}}


def test_price_us_walks_exchanges():
    from backend.flow.usquote import price_us
    c = _C("NYS")
    q = asyncio.run(price_us(c, "XYZ"))
    assert q and q["exch"] == "NYS" and c.calls[:2] == ["NAS", "NYS"]


def test_price_us_all_fail():
    from backend.flow.usquote import price_us
    assert asyncio.run(price_us(_C("NONE"), "ZZZZ")) is None


class _Stale:
    """모든 거래소가 last>0이나 거래량0·기준가없음 — 스테일 배제 검증(설계 §test)."""
    def __init__(self):
        self.calls = []

    async def _get(self, path, tr, params):
        self.calls.append(params["EXCD"])
        return {"rt_cd": "0", "output": {"last": "200", "sign": "3", "tvol": "0"}}


def test_price_us_rejects_stale_zero_volume():
    from backend.flow.usquote import price_us
    c = _Stale()
    assert asyncio.run(price_us(c, "STALE")) is None     # 유효 응답 없음
    assert c.calls == ["NAS", "NYS", "AMS"]              # 전 거래소 순회 후 배제


def test_us_name():
    from backend.flow.usquote import us_name
    assert us_name("NVDA") == "엔비디아" and us_name("ZZZZ") == "ZZZZ"


# ── 토스 실시간 우선(2026-09-03) ──────────────────────────────────────────

class _FakeTossUS:
    """TossClient 대역 — stock_candles만 쓴다."""

    def __init__(self, rows=None, boom=False):
        self.rows, self.boom, self.asked = rows, boom, []

    async def stock_candles(self, symbol, interval="1d", count=2):
        self.asked.append((symbol, interval, count))
        if self.boom:
            raise RuntimeError("토스 실패 스텁")
        return self.rows if self.rows is not None else []


def _aapl(prev=324.96, last=324.56):
    """2026-09-03 15:47 실측 모양 — [-1]이 진행 중 오늘, [-2]가 전일 확정."""
    return [{"date": "2026-09-02", "close": prev, "open": 326.865,
             "high": 328.4, "low": 323.53},
            {"date": "2026-09-03", "close": last, "open": 324.78,
             "high": 324.98, "low": 324.0}]


def test_toss_is_preferred_and_costs_one_call(monkeypatch):
    """토스가 있으면 KIS 거래소 순회(최대 3콜)를 건너뛰고 1콜로 끝난다.

    일봉 최신 봉의 종가가 곧 실시간 현재가다(2026-09-03 실측: 캔들 09-03 봉 close
    324.56 = /prices lastPrice 324.56, 같은 초). 그래서 현재가와 등락률이 한 콜에
    같이 나온다 — /prices는 lastPrice뿐이라 등락률이 없다."""
    from backend.flow import usquote
    fake = _FakeTossUS(_aapl())
    monkeypatch.setattr(usquote.toss, "get_client", lambda: fake)
    c = _C("NAS")
    q = asyncio.run(usquote.price_us(c, "AAPL"))
    assert q["price"] == 324.56
    assert q["change"] == -0.12          # (324.56/324.96-1)*100 = -0.1231…
    assert q["src"] == "toss" and q["currency"] == "USD"
    assert fake.asked == [("AAPL", "1d", 2)]
    assert c.calls == [], "토스가 성공했는데 KIS를 불렀다"


def test_toss_failure_falls_back_to_kis_walk(monkeypatch):
    from backend.flow import usquote
    monkeypatch.setattr(usquote.toss, "get_client", lambda: _FakeTossUS(boom=True))
    c = _C("NYS")
    # 심볼을 위 테스트들과 다르게 둔다 — _exch_cache가 모듈 전역이라 'XYZ'를 재사용하면
    # 앞 테스트가 확정한 거래소가 순회 순서를 바꿔 이 검증이 실행 순서에 매인다.
    q = asyncio.run(usquote.price_us(c, "QQQZ"))
    assert q and q["exch"] == "NYS" and q["src"] == "kis"
    assert c.calls[:2] == ["NAS", "NYS"]


def test_toss_with_one_bar_falls_back(monkeypatch):
    """봉이 하나뿐이면 전일 종가가 없어 등락률을 만들 수 없다 — KIS로 내려간다.

    한 봉으로 change=0을 지어내면 '보합'이라는 틀린 판정이 화면에 나간다."""
    from backend.flow import usquote
    monkeypatch.setattr(usquote.toss, "get_client",
                        lambda: _FakeTossUS([_aapl()[-1]]))
    c = _C("NAS")
    q = asyncio.run(usquote.price_us(c, "AAPL"))
    assert q["src"] == "kis" and c.calls == ["NAS"]


def test_toss_only_works_without_a_kis_client(monkeypatch):
    """KIS 클라이언트가 없어도(client=None) 토스만으로 시세가 나온다.

    라우트가 'KIS 없으면 204'로 막고 있었는데, 이제 토스만 있어도 값이 있다."""
    from backend.flow import usquote
    monkeypatch.setattr(usquote.toss, "get_client", lambda: _FakeTossUS(_aapl()))
    q = asyncio.run(usquote.price_us(None, "AAPL"))
    assert q["price"] == 324.56 and q["src"] == "toss"


def test_no_client_at_all_returns_none(monkeypatch):
    from backend.flow import usquote
    monkeypatch.setattr(usquote.toss, "get_client", lambda: None)
    assert asyncio.run(usquote.price_us(None, "AAPL")) is None


def _fx(name):
    import json
    from pathlib import Path
    return json.load(open(Path(__file__).parent / "fixtures" / "kis" / f"{name}.json", encoding="utf-8"))


def test_parse_us_ccnl_fixture_latest_vpow():
    from backend.flow.kis import parse_us_ccnl
    d = parse_us_ccnl(_fx("us_ccnl"))
    assert d["vpow"] == 58.4 and d["rows"][-1]["t"] == "08:59:59" and d["rows"][-1]["price"] == 229.5
    assert [r["t"] for r in d["rows"]] == sorted(r["t"] for r in d["rows"])
    assert parse_us_ccnl({"rt_cd": "1"}) == {"rows": [], "vpow": None}


def test_ccnl_walks_exchanges_and_caches():
    from backend.flow import usquote
    calls = []

    class C:
        async def us_ccnl(self, exch, sym):
            calls.append(exch)
            return _fx("us_ccnl") if exch == "NYS" else {"rt_cd": "0", "output2": []}
    usquote._exch_cache.clear(); usquote._ccnl_cache.clear()
    loop = asyncio.new_event_loop()
    d = loop.run_until_complete(usquote.ccnl(C(), "NVDA"))
    assert d["vpow"] == 58.4 and calls == ["NAS", "NYS"]          # NAS 빈 응답 → NYS 성공
    d2 = loop.run_until_complete(usquote.ccnl(C(), "NVDA"))
    assert d2["vpow"] == 58.4 and calls == ["NAS", "NYS"]        # 30초 캐시 — 추가 호출 0
    assert usquote._cached_exch("NVDA") == "NYS"                 # 성공 거래소를 캐시(시세 조회와 공유)
