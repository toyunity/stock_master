"""홈 시장 수급·자금·폭·업종·예상시가·베이시스(/api/market-flow). 픽스처 2026-09-08 실응답(행 6개 축약)."""
import asyncio
import datetime as dt
import json
from pathlib import Path

from backend.flow import marketflow as mf

_FX = Path(__file__).parent / "fixtures" / "kis"


def _fx(name):
    return json.load(open(_FX / f"{name}.json", encoding="utf-8"))


def _run(co):
    return asyncio.new_event_loop().run_until_complete(co)


def test_parse_investor_daily_ascending_in_eok():
    rows = mf.parse_investor_daily(_fx("investor_daily_today"))
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    last = rows[-1]
    assert last["date"] == "2026-09-08"
    assert last["frgn"] == 6316.23 and last["prsn"] == -30330.97 and last["orgn"] == 6426.9   # 백만원 → 억
    assert last["close"] > 0
    assert mf.parse_investor_daily({"rt_cd": "1"}) == []


def test_streak_counts_consecutive_sign_from_end():
    assert mf.streak([{"frgn": 1}, {"frgn": 2}, {"frgn": -1}, {"frgn": -3}], "frgn") == -2
    assert mf.streak([{"frgn": -1}, {"frgn": 5}, {"frgn": 6}, {"frgn": 7}], "frgn") == 3
    assert mf.streak([{"frgn": 1}, {"frgn": 0}], "frgn") == 0 and mf.streak([], "frgn") == 0


def test_parse_funds_in_eok_ascending():
    rows = mf.parse_funds(_fx("mktfunds"))
    assert rows[-1]["date"] == "2026-09-04" and rows[0]["date"] < rows[-1]["date"]
    assert rows[-1]["deposit"] == 935500 and rows[-1]["deposit_chg"] == -42115
    assert rows[-1]["credit"] == 335958 and rows[-1]["uncl"] == 10520 and rows[-1]["mmf"] == 2670887


def test_parse_breadth_sectors_expected():
    assert mf.parse_breadth(_fx("index_category_kospi")) == {"up": 231, "down": 634, "flat": 45}
    assert mf.parse_breadth(_fx("index_category_kosdaq"))["down"] == 1141
    sec = mf.parse_sectors(_fx("index_category_kospi"))
    assert [s["name"] for s in sec] == ["음식료·담배", "섬유·의류"]     # 종합·대형·중형·소형은 업종이 아니다
    assert sec[0]["rate"] == -0.92
    assert mf.parse_expected(_fx("exp_total_index")) == 0.94
    assert mf.parse_expected({"rt_cd": "0", "output2": []}) is None


def test_get_market_flow_live_and_demo(monkeypatch):
    class C:
        async def _get(self, path, tr, params):
            if tr == "FHPTJ04040000":
                return _fx("investor_daily_today")
            if tr == "FHKST649100C0":
                return _fx("mktfunds")
            if tr == "FHPUP02140000":
                return _fx("index_category_kospi" if params["FID_INPUT_ISCD"] == "0001" else "index_category_kosdaq")
            if tr == "FHKUP11750000":
                return _fx("exp_total_index")
            if tr == "FHPUP02100000":
                return _fx("k200_index")
            raise AssertionError(tr)

        async def index(self, iscd):
            from backend.flow.kis import parse_index
            return parse_index(_fx("k200_index"))
    mf.reset_caches()
    d = _run(mf.get_market_flow(C(), now=dt.datetime(2026, 9, 8, 8, 45), futures={"k200": {"price": 1101.2}}))
    assert d["investors"]["today"]["frgn"] == 6316.23 and d["investors"]["asof"] == "2026-09-08"
    assert isinstance(d["investors"]["streak_frgn"], int) and len(d["investors"]["rows"]) <= 20
    assert d["investors"]["provisional"] is True                       # 08:45 — 당일 행은 잠정
    assert d["funds"]["deposit"] == 935500 and d["funds"]["asof"] == "2026-09-04"
    assert d["funds"]["credit_pos20"] is not None
    assert d["breadth"]["kospi"]["up"] == 231 and d["breadth"]["kosdaq"]["down"] == 1141
    assert d["sectors"]["up"][0]["name"] == "섬유·의류" and d["sectors"]["down"][0]["name"] == "음식료·담배"
    assert d["expected"] == {"rate": 0.94}
    assert d["basis"] == {"fut": 1101.2, "spot": 1100.08, "basis": 1.12}
    mf.reset_caches()
    d2 = _run(mf.get_market_flow(C(), now=dt.datetime(2026, 9, 8, 17, 10), futures={}))
    assert d2["expected"] is None and d2["basis"] is None and d2["investors"]["provisional"] is False
    demo = mf.demo_market_flow()
    for k in ("investors", "funds", "breadth", "sectors", "basis"):
        assert demo[k], k
    assert demo["demo"] is True
