"""감시선 서버 저장(backend.flow.watch) — get/set 왕복·검증·폴백·원자성."""
import json
import os

import pytest

from backend.config import settings
from backend.flow import watch


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """캐시 디렉터리를 tmp로 격리 + config 시드를 테스트 소유 값으로 고정.

    settings.watch_lines의 기본값은 비어 있다(개인 매매 목표를 리포에 안 남긴다).
    폴백 경로를 검증하려면 테스트가 자기 시드를 들고 와야 한다."""
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "watch_lines", {
        "000660": [{"price": 100_000, "label": "시드A"},
                   {"price": 150_000, "label": "시드B"}]})
    return tmp_path


def test_get_default_from_config(iso):
    # 파일이 없으면 config 시드로 폴백
    lines = watch.get_lines("000660")
    labels = [l["label"] for l in lines]
    assert "시드A" in labels and "시드B" in labels
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
    assert "시드A" in labels


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


# ── 시장별 가격 정밀도 ────────────────────────────────────────────
# 감시선 가격을 무조건 정수로 반올림하던 규칙은 원화 전용이었다.
# US 티커에 $153.16 감시선을 걸면 153으로 잘려 저장됐다(조용한 데이터 손상).

def test_kr_price_stays_integer_won(iso):
    """국내는 원 단위 정수 — 소수 입력도 반올림한다(기존 동작 보존)."""
    saved = watch._validate_lines([{"price": 71234.6, "label": "절대선"}], market="KR")
    assert saved == [{"price": 71235, "label": "절대선"}]
    assert isinstance(saved[0]["price"], int)


def test_us_price_keeps_cents(iso):
    """미국은 센트가 살아야 한다 — $153.16을 153으로 저장하면 감시선이 무의미해진다."""
    saved = watch._validate_lines([{"price": 153.16, "label": "절대선"}], market="US")
    assert saved == [{"price": 153.16, "label": "절대선"}]


def test_us_price_rounds_to_cents_not_beyond(iso):
    """소수 셋째 자리는 버린다 — 호가 단위가 센트라 그 아래는 의미가 없다."""
    assert watch._validate_lines([{"price": 12.3456, "label": "a"}],
                                 market="US")[0]["price"] == 12.35


def test_us_whole_dollar_has_no_trailing_decimal_noise(iso):
    """정수 달러는 150.0이 아니라 150으로 — 화면 표기가 지저분해지지 않게."""
    p = watch._validate_lines([{"price": 150, "label": "a"}], market="US")[0]["price"]
    assert p == 150 and isinstance(p, int)


def test_default_market_is_kr(iso):
    """market을 안 넘기는 기존 호출부(전역 set_lines 등)는 국내 규칙 그대로."""
    assert watch._validate_lines([{"price": 99.9, "label": "a"}])[0]["price"] == 100


def test_clean_honors_market_too(iso):
    """읽기 경로(_clean)도 같은 규칙 — 저장은 됐는데 읽을 때 잘리면 소용없다."""
    assert watch._clean([{"price": 153.16, "label": "a"}], market="US") == \
        [{"price": 153.16, "label": "a"}]
