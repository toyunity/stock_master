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
