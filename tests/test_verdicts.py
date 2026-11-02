"""판정 장부(backend/flow/verdicts.py) — 저장·채점 테스트. 실 data/cache는 절대 건드리지 않는다(cache_dir=tmp)."""
from __future__ import annotations

import datetime as dt

import pytest

from backend.config import settings
from backend.flow import kst, verdicts


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "flow_mode", "")


def test_record_upserts_same_key():
    assert verdicts.record("outlook", "000660", "2026-11-03", "up", 410000)
    assert verdicts.record("outlook", "000660", "2026-11-03", "down", 412000)
    d = verdicts.load()
    assert list(d) == ["outlook:000660:2026-11-03"]
    assert d["outlook:000660:2026-11-03"]["dir"] == "down"
    assert d["outlook:000660:2026-11-03"]["px"] == 412000
    assert "at" in d["outlook:000660:2026-11-03"]


def test_record_keeps_extra_fields():
    verdicts.record("signal", "005930", "2026-11-02", "buy", 71000, advice=True)
    assert verdicts.load()["signal:005930:2026-11-02"]["advice"] is True


@pytest.mark.parametrize("px", [None, 0, float("nan")])
def test_record_skips_unusable_px(px):
    assert verdicts.record("outlook", "000660", "2026-11-03", "up", px) is False
    assert not verdicts._path().exists()


def test_record_noop_in_demo(monkeypatch):
    monkeypatch.setattr(settings, "flow_mode", "demo")
    assert verdicts.record("outlook", "000660", "2026-11-03", "up", 1) is False
    assert not verdicts._path().exists()


def test_record_prunes_older_than_400_days(monkeypatch):
    monkeypatch.setattr(kst, "today", lambda: dt.date(2026, 11, 2))
    verdicts.record("outlook", "000660", "2025-09-01", "up", 1)   # 427일 전
    verdicts.record("outlook", "000660", "2026-11-03", "up", 1)
    assert list(verdicts.load()) == ["outlook:000660:2026-11-03"]


def test_load_tolerates_corrupt_file():
    verdicts._path().parent.mkdir(parents=True, exist_ok=True)
    verdicts._path().write_text("{not json", encoding="utf-8")
    assert verdicts.load() == {}
    assert verdicts.record("outlook", "000660", "2026-11-03", "up", 1)
    assert len(verdicts.load()) == 1


# ---- score (순수 채점) ----

def _closes(start, vals):
    d0 = dt.date.fromisoformat(start)
    return [((d0 + dt.timedelta(days=i)).isoformat(), float(v)) for i, v in enumerate(vals)]


TODAY = dt.date(2026, 11, 20)


def test_score_outlook_hit_miss_neutral_pending():
    entries = {
        "outlook:A:2026-11-03": {"dir": "up", "px": 100},       # 11-03 종가 110 → hit
        "outlook:A:2026-11-04": {"dir": "down", "px": 110},     # 11-04 종가 120 → miss
        "outlook:A:2026-11-05": {"dir": "neutral", "px": 120},  # skip
        "outlook:A:2026-11-06": {"dir": "up", "px": 130},       # 11-06 봉 뒤에 봉 없음 → pending
    }
    closes = {"A": _closes("2026-11-02", [100, 110, 120, 130, 140])}  # 11-02..11-06
    s = verdicts.score(entries, closes, TODAY)
    assert s["outlook"] == {"n": 2, "hit": 1, "skip": 1, "pending": 1}
    assert s["by_code"]["A"]["outlook"] == s["outlook"]
    assert s["signal"] == {"n": 0, "hit": 0, "skip": 0, "pending": 0}


def test_score_outlook_uses_first_bar_on_or_after_target():
    entries = {"outlook:A:2026-11-07": {"dir": "up", "px": 100}}   # 11-07 봉 없음(휴장)
    closes = {"A": _closes("2026-11-05", [100, 100]) + [("2026-11-08", 101.0), ("2026-11-09", 50.0)]}
    s = verdicts.score(entries, closes, TODAY)
    assert s["outlook"] == {"n": 1, "hit": 1, "skip": 0, "pending": 0}


def test_score_signal_grades_10th_bar_after_D_and_needs_11th():
    entries = {"signal:A:2026-11-01": {"dir": "buy", "px": 100},
               "signal:A:2026-11-02": {"dir": "sell", "px": 100},
               "signal:A:2026-11-03": {"dir": "hold", "px": 100}}
    # 11-01 이후 10번째 봉 = 11-11(종가 90) → buy miss; 11번째 봉(11-12) 있어야 확정
    closes = {"A": _closes("2026-11-01", [100] * 10 + [90, 95])}      # 11-01..11-12
    s = verdicts.score(entries, closes, TODAY)
    # 11-02 이후 10번째 = 11-12(95), 그 다음 봉 없음 → sell pending
    assert s["signal"] == {"n": 1, "hit": 0, "skip": 1, "pending": 1}


def test_score_zero_return_is_miss():
    entries = {"outlook:A:2026-11-03": {"dir": "up", "px": 100}}
    closes = {"A": _closes("2026-11-03", [100, 100])}
    assert verdicts.score(entries, closes, TODAY)["outlook"]["hit"] == 0


def test_score_code_missing_in_closes_is_pending():
    entries = {"outlook:GONE:2026-11-03": {"dir": "up", "px": 100}}
    s = verdicts.score(entries, {}, TODAY)
    assert s["outlook"]["pending"] == 1 and s["by_code"]["GONE"]["outlook"]["pending"] == 1


def test_score_window_is_last_60_bars():
    vals = [100] * 70 + [110]
    closes = {"A": _closes("2026-08-01", vals)}        # 71봉, 마지막 2026-10-10
    dates = [d for d, _ in closes["A"]]
    old, new = dates[5], dates[-2]                      # 창 밖 / 창 안
    entries = {"outlook:A:%s" % old: {"dir": "up", "px": 90},
               "outlook:A:%s" % new: {"dir": "up", "px": 90}}
    s = verdicts.score(entries, closes, TODAY)
    assert s["outlook"]["n"] == 1 and s["outlook"]["hit"] == 1   # 창 밖 1건은 집계 안 됨


def test_score_window_falls_back_to_90_calendar_days_without_bars():
    entries = {"outlook:A:%s" % (TODAY - dt.timedelta(days=100)).isoformat(): {"dir": "up", "px": 1},
               "outlook:A:%s" % (TODAY - dt.timedelta(days=10)).isoformat(): {"dir": "up", "px": 1}}
    s = verdicts.score(entries, {}, TODAY)
    assert s["outlook"]["pending"] == 1     # 창 안 1건만 집계(pending), 창 밖은 제외


def test_record_many_writes_file_once(monkeypatch):
    """홈 1회·/api/outlook 1회에 종목 수만큼 전체 파일을 다시 쓰지 않는다(리뷰 2026-11-02:
    12회 record ≈ 0.48초, async 경로에선 이벤트 루프가 그만큼 멈춘다)."""
    import os
    calls = {"n": 0}
    real = os.replace

    def counting(a, b):
        calls["n"] += 1
        return real(a, b)
    monkeypatch.setattr(os, "replace", counting)
    rows = [("outlook", "000660", "2026-11-03", "up", 1, {}),
            ("outlook", "005930", "2026-11-03", "down", 2, {"x": 1}),
            ("outlook", "BAD", "2026-11-03", "up", None, {})]
    assert verdicts.record_many(rows) == 2
    assert calls["n"] == 1
    d = verdicts.load()
    assert set(d) == {"outlook:000660:2026-11-03", "outlook:005930:2026-11-03"}
    assert d["outlook:005930:2026-11-03"]["x"] == 1
    assert verdicts.record_many([]) == 0 and calls["n"] == 1     # 쓸 게 없으면 파일도 안 건드린다
