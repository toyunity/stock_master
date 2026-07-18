"""오늘 현황 서술 엔진 — 신호+재무를 사실+해석 문장으로. ADR 유무 제어."""
from backend.signals.situation import commentary


def _sig(**kw):
    base = {"is_semi": True, "has_adr": True, "us": None, "adr": None,
            "flow": None, "momentum": None}
    base.update(kw)
    return base


def test_commentary_reads_todays_situation():
    c = commentary(_sig(us={"sox_rate": -1.6},
                        flow={"frgn_net": -400, "orgn_net": -600},
                        momentum={"rate": -12.1, "overheated": False}),
                   {"per": 31.0, "w52_pos": 58.0}, [{"roe": 61.0, "debt": 36.0}])
    text = " ".join(c["sentences"])
    assert "하락" in text
    assert "순매도" in text
    assert ("체력" in text or "튼튼" in text)
    assert "PER" in text
    assert c["caution"]


def test_commentary_omits_adr_when_absent():
    # has_adr=False → adr 데이터가 있어도 DR 언급 안 함(패널 제어)
    c = commentary(_sig(has_adr=False, adr={"overnight_rate": 2.0},
                        momentum={"rate": 0.2}), {}, [])
    assert all("DR" not in s for s in c["sentences"])


def test_commentary_mentions_adr_when_present():
    c = commentary(_sig(has_adr=True, adr={"overnight_rate": 2.0}), {}, [])
    assert any("DR" in s for s in c["sentences"])


def test_commentary_handles_sparse():
    c = commentary(_sig(), None, None)
    assert isinstance(c["sentences"], list) and c["caution"]
