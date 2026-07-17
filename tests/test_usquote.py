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
