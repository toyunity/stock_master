import json

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
