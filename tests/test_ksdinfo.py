"""예탁원 일정 7종(HHKDB6691xxC0) — 파서·조회. 픽스처는 2026-09-08 실응답(행 6개 축약)."""
import asyncio
import json
from pathlib import Path

from backend.flow import ksdinfo
from backend.flow.ksdinfo import parse_events

_FX = Path(__file__).parent / "fixtures" / "kis"


def _fx(name):
    return json.load(open(_FX / f"{name}.json", encoding="utf-8"))


def test_parse_dividend_uses_record_date_and_amount():
    rows = parse_events("dividend", _fx("ksdinfo_dividend"))
    assert rows[0]["date"] == "2026-08-31" and rows[0]["kind"] == "dividend"
    assert rows[0]["label"] == "배당 기준일"
    assert "375원" in rows[0]["detail"] and "지급 2026-09-30" in rows[0]["detail"]
    assert rows[0]["code"] == "000660"


def test_parse_paidin_uses_right_date_and_terms():
    rows = parse_events("paidin", _fx("ksdinfo_paidin_capin"))
    r = rows[0]
    assert r["date"] == "2026-11-06" and r["label"] == "유상증자 권리락"   # right_dt, 기준일 11-09 아님
    assert "배정률 60.41%" in r["detail"] and "청약 2026/12/14" in r["detail"]


def test_parse_bonus_and_meeting():
    b = parse_events("bonus", _fx("ksdinfo_bonus_issue"))[0]
    assert b["date"] == "2026-10-26" and b["label"] == "무상증자 권리락" and "100.00%" in b["detail"]
    m = parse_events("meet", _fx("ksdinfo_sharehld_meet"))[0]
    assert m["date"] == "2026-12-07" and m["label"] == "주주총회(임시총회)" and "합병" in m["detail"]


def test_parse_split_and_purreq_strip_padding():
    s = parse_events("split", _fx("ksdinfo_rev_split"))[0]
    assert s["date"] == "2026-10-02"                      # 거래정지 시작일(td_stop_dt 앞 날짜)
    assert "500원→2,500원" in s["detail"] and "거래정지 2026/10/02 ~" in s["detail"]
    p = parse_events("purreq", _fx("ksdinfo_purreq"))[0]
    assert p["date"] == "2026-11-18"                      # buy_req_rcpt_term '020261118'의 앞 0 제거
    assert "20,891원" in p["detail"] and "주총 2026-10-30" in p["detail"]


def test_parse_rejects_error_and_empty():
    assert parse_events("dividend", {"rt_cd": "1"}) == []
    assert parse_events("merger", {"rt_cd": "0", "output1": []}) == []


def test_get_events_isolates_failures_and_sorts(monkeypatch):
    calls = []

    class C:
        async def _get(self, path, tr, params):
            calls.append((tr, params["SHT_CD"], params["F_DT"], params["T_DT"]))
            if tr == "HHKDB669111C0":
                raise RuntimeError("boom")            # 주총 TR만 실패 — 나머지는 살아야 한다
            if tr == "HHKDB669102C0":
                return _fx("ksdinfo_dividend")
            if tr == "HHKDB669100C0":
                return _fx("ksdinfo_paidin_capin")
            return {"rt_cd": "0", "output1": []}
    ksdinfo._cache.clear()
    import datetime as dt
    d = asyncio.new_event_loop().run_until_complete(
        ksdinfo.get_events(C(), "000660", today=dt.date(2026, 9, 8)))
    assert len(calls) == 7 and all(c[1] == "000660" for c in calls)
    assert calls[0][2] == "20260725" and calls[0][3] == "20270106"   # today-45 ~ today+120
    dates = [r["date"] for r in d["rows"]]
    assert dates == sorted(dates) and d["asof"] == "2026-09-08"
    assert any(r["kind"] == "paidin" for r in d["rows"]) and any(r["kind"] == "dividend" for r in d["rows"])
    # 캐시 히트 — 두 번째 호출은 원격 0건
    n = len(calls)
    asyncio.new_event_loop().run_until_complete(ksdinfo.get_events(C(), "000660", today=dt.date(2026, 9, 8)))
    assert len(calls) == n
