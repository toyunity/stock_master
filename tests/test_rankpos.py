"""공매도 상위(FHPST04820000)·신용잔고 상위(FHKST17010000) 속 종목 위치. 픽스처 2026-09-08 실응답."""
import asyncio
import json
from pathlib import Path

from backend.flow import rankpos

_FX = Path(__file__).parent / "fixtures" / "kis"


def _fx(name):
    return json.load(open(_FX / f"{name}.json", encoding="utf-8"))


def test_parse_ranks_from_real_fixture():
    s = rankpos.parse_short_rank(_fx("short_sale_rank"))
    assert s[1] == {"code": "034220", "name": "LG디스플레이", "ratio": 19.46}
    c = rankpos.parse_credit_rank(_fx("credit_balance_rank"))
    assert c[1]["code"] == "251340" and c[1]["rate"] == 6.67
    assert rankpos.parse_short_rank({"rt_cd": "1"}) == [] and rankpos.parse_credit_rank({}) == []


def test_get_position_ranks_and_out_of_list(monkeypatch):
    calls = []

    class C:
        async def _get(self, path, tr, params):
            calls.append(tr)
            return _fx("short_sale_rank") if tr == "FHPST04820000" else _fx("credit_balance_rank")
    rankpos._cache.clear()
    run = lambda co: asyncio.new_event_loop().run_until_complete(co)
    p = run(rankpos.get_position(C(), "034220"))
    assert p["short"] == {"rank": 2, "n": 6, "ratio": 19.46}
    assert p["credit"] == {"rank": None, "n": 6, "rate": None}
    assert p["asof"] == "2026-09-07"
    q = run(rankpos.get_position(C(), "251340"))   # 시장 전체 목록은 캐시 — 원격 2콜뿐
    assert q["credit"]["rank"] == 2 and len(calls) == 2
