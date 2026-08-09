import json

import pytest

from harness.cmd import eval as ev


def test_run_scenario_matches_golden(tmp_path):
    # 임시 시나리오 + 골든으로 통과/불일치 양쪽 확인
    scen = tmp_path / "s.json"
    scen.write_text(json.dumps({
        "module": "backend.flow.shortbal", "func": "short_signal",
        "cases": [{"name": "c1", "input": {"price_rate": 1.5, "chg_qty": -500}}]
    }), encoding="utf-8")
    gdir = tmp_path / "golden"
    gdir.mkdir()
    (gdir / "s.json").write_text(json.dumps({
        "c1": {"text": "건강한 상승 (숏 이탈)", "tone": "good"}}), encoding="utf-8")
    res = ev.run_scenario(str(scen))
    assert res == [{"name": "c1", "ok": True,
                    "got": {"text": "건강한 상승 (숏 이탈)", "tone": "good"},
                    "want": {"text": "건강한 상승 (숏 이탈)", "tone": "good"}}]


def test_run_scenario_detects_drift(tmp_path):
    scen = tmp_path / "s.json"
    scen.write_text(json.dumps({
        "module": "backend.flow.shortbal", "func": "short_signal",
        "cases": [{"name": "c1", "input": {"price_rate": 1.5, "chg_qty": -500}}]
    }), encoding="utf-8")
    gdir = tmp_path / "golden"
    gdir.mkdir()
    (gdir / "s.json").write_text(json.dumps({
        "c1": {"text": "틀린 문구", "tone": "warn"}}), encoding="utf-8")
    res = ev.run_scenario(str(scen))
    assert res[0]["ok"] is False


def _front_month_scen(tmp_path, coerce):
    """만기가 오늘(2026-08-13)인 8월물 — 날짜를 되살려야만 '202608'이 나온다."""
    scen = tmp_path / "s.json"
    body = {"module": "backend.flow.optmaster", "func": "front_month",
            "cases": [{"name": "c1", "input": {
                "today": "2026-08-13",
                "rows": [{"expiry": "202608"}, {"expiry": "202609"}]}}]}
    if coerce:
        body["coerce"] = coerce
    scen.write_text(json.dumps(body), encoding="utf-8")
    (tmp_path / "golden").mkdir()
    (tmp_path / "golden" / "s.json").write_text(json.dumps({"c1": "202608"}),
                                                encoding="utf-8")
    return str(scen)


def test_coerce_revives_dates_from_json_strings(tmp_path):
    """JSON엔 날짜 타입이 없다 — 시나리오가 지목한 인자를 date로 되살리는지."""
    res = ev.run_scenario(_front_month_scen(tmp_path, {"today": "date"}))
    assert res[0]["ok"] is True and res[0]["got"] == "202608"


def test_without_coerce_the_date_stays_a_string(tmp_path):
    """coerce를 안 적으면 문자열 그대로 간다 — 자동 변환은 하지 않는다는 계약.

    (날짜 모양 텍스트가 입력에 섞였을 때 조용히 타입이 바뀌면 더 위험하다.)"""
    with pytest.raises(TypeError):
        ev.run_scenario(_front_month_scen(tmp_path, None))


def test_coerce_leaves_null_alone(tmp_path):
    """결측(null)은 변환하지 않고 그대로 넘긴다 — 함수의 결측 처리를 가려선 안 된다."""
    scen = tmp_path / "s.json"
    scen.write_text(json.dumps({
        "module": "backend.flow.exvol", "func": "distortion",
        "coerce": {"nxt_after_price": "date"},          # null이라 변환되지 않아야 한다
        "cases": [{"name": "c1", "input": {
            "nxt_after_price": None, "krx_close": 1000,
            "after_vol": 5000, "total_vol": 100000}}]}), encoding="utf-8")
    (tmp_path / "golden").mkdir()
    (tmp_path / "golden" / "s.json").write_text(json.dumps({"c1": None}),
                                                encoding="utf-8")
    res = ev.run_scenario(str(scen))
    assert res[0]["ok"] is True
