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


def test_watch_lines_non_master_never_sees_config(monkeypatch):
    """blocker 회귀 방지 — 비마스터 계정은 config 감시선(마스터 실매도가) 절대 못 봄."""
    from backend.flow import userstore as us
    from backend.config import settings
    monkeypatch.setattr(settings, "watch_lines", {"000660": [{"price": 1853000, "label": "절대선"}]})
    assert us.get_lines(B, "000660") == []                 # B는 빈(폴백 금지)
    assert us.get_lines(M, "000660")[0]["price"] == 1853000  # 마스터만 시드


def test_watch_lines_set_get_isolation():
    from backend.flow import userstore as us
    us.set_lines(M, "005930", [{"price": 70000, "label": "지지"}])
    assert us.get_lines(M, "005930")[0]["price"] == 70000
    assert us.get_lines(B, "005930") == []                 # 격리


def test_token_lifecycle_and_reverse():
    from backend.flow import userstore as us
    t = us.ensure_token(M)
    assert len(t) >= 20 and us.email_for_token(t) == M
    assert us.email_for_token("nope-" + "x" * 20) is None      # 미매칭 None(폴백 금지)


def test_token_rotation_kills_old():
    from backend.flow import userstore as us
    old = us.ensure_token(M)
    new = us.rotate_token(M)
    assert new != old
    assert us.email_for_token(new) == M
    assert us.email_for_token(old) is None                     # 구 토큰 즉시 사망


def test_cross_account_token_never_crosses():
    from backend.flow import userstore as us
    ta, tb = us.ensure_token(M), us.ensure_token(B)
    assert us.email_for_token(ta) == M and us.email_for_token(tb) == B
    assert us.email_for_token(ta) != B                         # 교차 금지
