from backend.market.universe import get_universe, price_map, _to_float


def _fake():
    return [{"code": "005930", "name": "삼성전자", "close": 71000.0, "change": -2.1},
            {"code": "000660", "name": "SK하이닉스", "close": 250000.0, "change": 1.3}]


def test_to_float_handles_nan_none_garbage():
    assert _to_float(1.5) == 1.5
    assert _to_float(None) is None
    assert _to_float(float("nan")) is None
    assert _to_float("x") is None


def test_get_universe_fetches_then_caches(tmp_path):
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return _fake()

    u = get_universe(str(tmp_path), fetch=fetch)
    assert len(u) == 2 and u[0]["code"] == "005930"
    # 두 번째 호출은 신선 캐시 사용(추가 수집 없음)
    get_universe(str(tmp_path), fetch=fetch)
    assert calls["n"] == 1


def test_get_universe_falls_back_to_cache_on_fetch_failure(tmp_path):
    get_universe(str(tmp_path), fetch=_fake)  # 캐시 적재

    def boom():
        raise RuntimeError("StockListing down")

    # force=True여도 수집 실패 시 캐시로 폴백
    u = get_universe(str(tmp_path), force=True, fetch=boom)
    assert len(u) == 2


def test_get_universe_empty_when_no_cache_and_fetch_fails(tmp_path):
    def boom():
        raise RuntimeError("down")

    assert get_universe(str(tmp_path), fetch=boom) == []


def test_price_map():
    pm = price_map(_fake())
    assert pm["005930"]["close"] == 71000.0
    assert pm["000660"]["change"] == 1.3
