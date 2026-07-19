"""주린이 가이드 엔진 — 왜 움직였나 / 지금 볼 포인트 3개 / 다음에 뭘 하면 되나."""
from backend.signals.guide import guide


def _sig(**kw):
    base = {"is_semi": True, "has_adr": True, "us": None, "adr": None,
            "flow": None, "momentum": None}
    base.update(kw)
    return base


def test_guide_explains_big_drop():
    g = guide(_sig(us={"sox_rate": -1.6}, flow={"frgn_net": -1, "orgn_net": -1},
                   momentum={"rate": -12.1, "overheated": False}),
              {"per": 31.0, "w52_pos": 58.0}, [{"roe": 61.0, "debt": 36.0}])
    assert "하락" in g["why_moved"] and "12.1" in g["why_moved"]
    assert len(g["points"]) == 3
    assert "서두르지" in g["next_action"]


def test_guide_no_driver_when_move_unexplained():
    g = guide(_sig(us=None, flow=None, momentum={"rate": -6.0}), {}, [])
    assert "뚜렷한 외부 원인" in g["why_moved"]
    assert len(g["points"]) == 3          # 필러로 항상 3개
    assert g["next_action"]


def test_guide_neutral():
    g = guide(_sig(momentum={"rate": 0.3}), {}, [])
    assert "큰 변동이 없" in g["why_moved"]
    assert "관망" in g["next_action"]
