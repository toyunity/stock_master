"""종목 상세 부가 데이터 6종(투자의견·매물대·시간외·프로그램 일별·일별 체결량·체결금액 비중) + 조립·데모.
픽스처는 2026-09-08 실응답(행 6개 축약)."""
import asyncio
import json
from pathlib import Path

from backend.flow import stockinfo as si

_FX = Path(__file__).parent / "fixtures" / "kis"


def _fx(name):
    return json.load(open(_FX / f"{name}.json", encoding="utf-8"))


def test_parse_opinions_normalizes_and_summarizes():
    rows = si.parse_opinions(_fx("invest_opinion"))
    assert rows[0]["broker"] == "DB증권" and rows[0]["target"] == 2300000
    assert rows[0]["opinion"] == "매수" and rows[1]["opinion"] == "매수"    # 'BUY'와 '매수'를 한 단어로
    s = si.summarize_opinions(rows, 1793000)
    brokers = {r["broker"] for r in rows}
    assert s["n"] == len(brokers)                       # 증권사별 최신 1건만 집계
    assert s["buy"] == s["n"] and s["sell"] == 0
    assert s["max_target"] == max(r["target"] for r in rows)
    assert s["gap_pct"] < 0 and s["latest"] == "2026-09-07"
    assert si.summarize_opinions([], 100)["n"] == 0


def test_parse_profile_top_levels():
    p = si.parse_profile(_fx("pbar_tratio"))
    assert p["price"] == 1793000 and p["wavg"] == 1841491.05
    assert p["top"] == {"price": 1793000, "pct": 5.81}
    assert [l["price"] for l in p["levels"]] == sorted([l["price"] for l in p["levels"]], reverse=True)
    assert len(p["levels"]) <= 8


def test_parse_overtime_value_and_zero():
    o = si.parse_overtime(_fx("overtime_price"))
    assert o["price"] == 11950 and o["rate"] == 1.19 and o["vol"] == 35757 and o["expected"] == 11920
    z = si.parse_overtime(_fx("overtime_price_zero"))
    assert z["vol"] == 0


def test_parse_daily_series_ascending():
    pg = si.parse_pgm_daily(_fx("program_trade_by_stock_daily"))
    assert pg[-1]["date"] == "2026-09-08" and pg[-1]["net_qty"] == 126584
    assert [r["date"] for r in pg] == sorted(r["date"] for r in pg)
    tv = si.parse_trade_volume(_fx("daily_trade_volume"))
    assert tv[-1]["buy"] == 1998606 and tv[-1]["sell"] == 1862332
    assert round(tv[-1]["strength"], 1) == 107.3
    ta = si.parse_trade_by_amount(_fx("tradprt_byamt"))
    assert ta[0]["band"] == "3백 이하" and ta[0]["buy_cnt"] == 55150 and ta[0]["net_rate"] == -0.19


def test_get_stockinfo_isolates_and_demo(monkeypatch):
    class C:
        async def _get(self, path, tr, params):
            if tr == "FHPST01130000":
                return _fx("pbar_tratio")
            raise RuntimeError("down")
    si.reset_caches()
    monkeypatch.setattr(si.ksdinfo, "get_events", _boom)
    monkeypatch.setattr(si.rankpos, "get_position", _boom)
    d = asyncio.new_event_loop().run_until_complete(si.get_stockinfo("000660", C()))
    assert d["pbar"]["top"]["price"] == 1793000
    assert d["opinion"] is None and d["events"] is None and d["overtime"] is None
    demo = si.demo_stockinfo("000660")
    for k in ("events", "opinion", "pbar", "overtime", "pgm_daily", "tradevol", "tradeamt", "rankpos"):
        assert demo[k], k
    assert demo["overtime"]["vol"] > 0 and len(demo["pbar"]["levels"]) == 8
    assert si.demo_stockinfo("000660") == demo      # 결정적


async def _boom(*a, **k):
    raise RuntimeError("down")
