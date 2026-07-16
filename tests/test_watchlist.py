"""관심종목 저장소 — watch.py(감시선) 미러: 검증·원자성·시드 폴백."""
import json
import os

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))


def test_get_falls_back_to_seed_when_no_file():
    from backend.flow.watchlist import get_watchlist
    from backend.config import settings
    assert get_watchlist() == list(settings.watchlist)


def test_set_then_get_roundtrip(tmp_path):
    from backend.flow import watchlist as wl
    saved = wl.set_watchlist(["035720", "005930"])
    assert saved == ["035720", "005930"]
    assert wl.get_watchlist() == ["035720", "005930"]
    with open(os.path.join(str(tmp_path), "watchlist.json"), encoding="utf-8") as f:
        assert json.load(f) == {"codes": ["035720", "005930"]}


def test_set_validates():
    from backend.flow import watchlist as wl
    with pytest.raises(ValueError):
        wl.set_watchlist("not-a-list")
    with pytest.raises(ValueError):
        wl.set_watchlist(["12345"])            # 6자리 아님
    with pytest.raises(ValueError):
        wl.set_watchlist([])                    # 최소 1개
    with pytest.raises(ValueError):
        wl.set_watchlist(["%06d" % i for i in range(11)])   # 최대 10개


def test_set_dedups_preserving_order():
    from backend.flow import watchlist as wl
    assert wl.set_watchlist(["005930", "000660", "005930"]) == ["005930", "000660"]


def test_corrupt_file_falls_back_to_seed(tmp_path):
    from backend.flow.watchlist import get_watchlist
    from backend.config import settings
    with open(os.path.join(str(tmp_path), "watchlist.json"), "w") as f:
        f.write("{broken")
    assert get_watchlist() == list(settings.watchlist)
