"""내일장 방향 규칙 엔진 — 순수 함수. 신호 번들 → 방향·근거·주의."""
from backend.signals.nextday import outlook


def _sig(**kw):
    base = {"session": "us_closed", "is_semi": True, "us": None,
            "adr": None, "flow": None, "momentum": None}
    base.update(kw)
    return base


def test_bullish_when_us_up_and_dual_buy():
    o = outlook(_sig(us={"sox_rate": 2.1, "nasdaq_rate": 1.2, "us_open": False},
                     flow={"frgn_net": 1000, "orgn_net": 2000}))
    assert o["direction"] == "up"
    assert any("반도체" in r["text"] or "미국" in r["text"] for r in o["reasons"])
    assert o["caution"]


def test_overheated_pulls_to_neutral_with_caution():
    o = outlook(_sig(momentum={"rate": 12.0, "overheated": True},
                     flow={"frgn_net": -500, "orgn_net": 300}))
    assert o["direction"] == "neutral"
    assert "되돌림" in o["caution"] or "과열" in o["caution"]


def test_adr_gap_up_drives_bullish():
    o = outlook(_sig(adr={"overnight_rate": 2.5}))
    assert o["direction"] == "up"
    assert any("DR" in r["text"] for r in o["reasons"])


def test_bearish_when_us_down_and_outflow():
    o = outlook(_sig(us={"sox_rate": -2.5, "nasdaq_rate": -1.5, "us_open": False},
                     flow={"frgn_net": -900, "orgn_net": -400}))
    assert o["direction"] == "down"


def test_framing_follows_session():
    assert "밤" in outlook(_sig(session="kr_closed_us_pending"))["framing"]
    assert "간밤" in outlook(_sig(session="us_closed"))["framing"]
