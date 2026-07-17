"""계정별 저장소 — 격리·검증·마이그레이션·토큰. 설계 2026-07-17.
⚠ Settings는 .env 자동로드 — 테스트는 tmp cache_dir·명시 값으로 격리."""
import pytest

M = "master@gmail.com"
B = "b@gmail.com"


def test_norm_email():
    from backend.flow.userstore import norm_email
    assert norm_email("  Master@Gmail.com ") == "master@gmail.com"


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "default_account", M)
    monkeypatch.setattr(settings, "watchlist", ["005930", "000660"])


def test_master_seeds_others_empty():
    from backend.flow import userstore as us
    assert [i["code"] for i in us.get_watchlist(M)] == ["005930", "000660"]  # 마스터 시드
    assert us.get_watchlist(B) == []                                        # 비마스터 빈


def test_set_get_roundtrip_and_isolation():
    from backend.flow import userstore as us
    us.set_watchlist(M, [{"code": "005930", "market": "KR", "shares": 10, "avg": 230000}])
    us.set_watchlist(B, [{"code": "NVDA", "market": "US", "shares": 5, "avg": 170.5}])
    assert us.get_watchlist(M)[0]["code"] == "005930"
    assert us.get_watchlist(B)[0]["code"] == "NVDA"           # 격리
    assert all(i["market"] == "KR" for i in us.get_watchlist(M))


def test_get_kr_codes_excludes_us():
    from backend.flow import userstore as us
    us.set_watchlist(M, [{"code": "005930", "market": "KR"},
                         {"code": "NVDA", "market": "US"}])
    assert us.get_kr_codes(M) == ["005930"]                   # US 제외


def test_set_validates():
    from backend.flow import userstore as us
    with pytest.raises(ValueError):
        us.set_watchlist(M, [{"code": "12345", "market": "KR"}])   # 6자리 아님
    with pytest.raises(ValueError):
        us.set_watchlist(M, [])                                     # 최소 1
    with pytest.raises(ValueError):
        us.set_watchlist(M, [{"code": "A%d" % i, "market": "US"} for i in range(11)])
    with pytest.raises(ValueError):
        us.set_watchlist(M, [{"code": "005930", "market": "KR", "avg": -1}])  # 음수


def test_us_avg_keeps_float():
    from backend.flow import userstore as us
    saved = us.set_watchlist(M, [{"code": "NVDA", "market": "US", "shares": 1, "avg": 170.55}])
    assert saved[0]["avg"] == 170.55           # US 소수 보존(int 반올림 금지)
