"""감시선 서버 저장(backend.flow.watch) — get/set 왕복·검증·폴백·원자성."""
import json
import os

import pytest

from backend.config import settings
from backend.flow import watch


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """캐시 디렉터리를 tmp로 격리 — 실제 data/cache 오염 방지."""
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    return tmp_path


def test_get_default_from_config(iso):
    # 파일이 없으면 config 기본값(000660엔 절대선·예약매도)으로 폴백
    lines = watch.get_lines("000660")
    labels = [l["label"] for l in lines]
    assert "절대선" in labels and "예약매도" in labels
    assert all(isinstance(l["price"], int) and l["price"] > 0 for l in lines)


def test_get_unknown_code_empty(iso):
    assert watch.get_lines("999999") == []


def test_set_get_roundtrip(iso):
    saved = watch.set_lines("000660", [{"price": 100000.7, "label": "  손절 "}])
    assert saved == [{"price": 100001, "label": "손절"}]     # 반올림 + strip
    assert watch.get_lines("000660") == [{"price": 100001, "label": "손절"}]


def test_file_overrides_config(iso):
    watch.set_lines("000660", [{"price": 50000, "label": "내선"}])
    # 파일에 코드 키가 있으면 config 기본값은 무시된다
    assert watch.get_lines("000660") == [{"price": 50000, "label": "내선"}]


def test_empty_array_persists(iso):
    # 전부 삭제(빈 배열)도 영속 — config 기본값으로 되돌아가지 않는다
    watch.set_lines("000660", [])
    assert watch.get_lines("000660") == []


@pytest.mark.parametrize("bad", [
    [{"price": -1, "label": "x"}],                 # 음수 가격
    [{"price": 0, "label": "x"}],                   # 0
    [{"price": "abc", "label": "x"}],               # 비수치
    [{"price": 1000, "label": ""}],                 # 빈 라벨
    [{"price": 1000, "label": "   "}],              # 공백 라벨
    [{"price": 1000, "label": "x" * 21}],           # 라벨 초과
    [{"label": "x"}],                                # 가격 없음
    [{"price": 1000, "label": "x"}] * 11,           # 11줄(상한 초과)
    "notalist",                                      # 리스트 아님
])
def test_set_rejects_invalid(iso, bad):
    with pytest.raises(ValueError):
        watch.set_lines("000660", bad)


def test_corrupt_file_falls_back(iso):
    (iso / "watch_lines.json").write_text("{ this is not json", encoding="utf-8")
    # 손상 파일이면 예외를 삼키고 config 폴백 — 화면이 죽지 않는다
    labels = [l["label"] for l in watch.get_lines("000660")]
    assert "절대선" in labels


def test_atomic_write_no_tmp_residue(iso):
    watch.set_lines("000660", [{"price": 12345, "label": "a"}])
    files = os.listdir(iso)
    assert "watch_lines.json" in files
    assert not any(f.endswith(".tmp") for f in files)     # temp 잔재 없음
    # 저장 내용이 올바른 JSON
    d = json.loads((iso / "watch_lines.json").read_text(encoding="utf-8"))
    assert d["000660"] == [{"price": 12345, "label": "a"}]


def test_set_preserves_order(iso):
    saved = watch.set_lines("000660", [
        {"price": 300, "label": "c"}, {"price": 100, "label": "a"}, {"price": 200, "label": "b"}])
    assert [l["label"] for l in saved] == ["c", "a", "b"]
