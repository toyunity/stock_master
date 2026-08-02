"""선물 세션 판정 + 전광판/해외선물 마스터 파서 — 네트워크 없음."""
import datetime as dt

from backend.flow import futures as fx
from backend.flow.kst import KST


def _at(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=KST)


def test_session_boundaries_on_weekday():
    """2026-07-30은 목요일. 주간 08:45~15:45, 야간 18:00~."""
    assert fx.session_of(_at(2026, 7, 30, 8, 44)) == "closed"
    assert fx.session_of(_at(2026, 7, 30, 8, 45)) == "day"
    assert fx.session_of(_at(2026, 7, 30, 15, 44)) == "day"
    assert fx.session_of(_at(2026, 7, 30, 15, 45)) == "gap"
    assert fx.session_of(_at(2026, 7, 30, 17, 59)) == "gap"
    assert fx.session_of(_at(2026, 7, 30, 18, 0)) == "night"
    assert fx.session_of(_at(2026, 7, 30, 23, 59)) == "night"


def test_session_night_spans_midnight_and_ends_at_six():
    """야간은 자정을 넘겨 아침 6시에 닫힌다(5시가 아니다 — teardown 실측)."""
    assert fx.session_of(_at(2026, 7, 31, 0, 30)) == "night"
    assert fx.session_of(_at(2026, 7, 31, 5, 59)) == "night"
    assert fx.session_of(_at(2026, 7, 31, 6, 0)) == "closed"


def test_session_weekend():
    """토요일 새벽은 금요일 야간의 연장이고, 토요일 저녁엔 열지 않는다."""
    assert fx.session_of(_at(2026, 8, 1, 3, 0)) == "night"
    assert fx.session_of(_at(2026, 8, 1, 10, 0)) == "closed"
    assert fx.session_of(_at(2026, 8, 1, 19, 0)) == "closed"
    assert fx.session_of(_at(2026, 8, 2, 3, 0)) == "closed"


_BOARD_JS = {"rt_cd": "0", "output": [
    {"futs_shrn_iscd": "101W09", "hts_kor_isnm": "미니F 202609", "futs_prpr": "885.25",
     "futs_prdy_ctrt": "-1.49", "prdy_vrss_sign": "5", "acml_vol": "141272"},
    {"futs_shrn_iscd": "101W12", "hts_kor_isnm": "미니F 202612", "futs_prpr": "889.00",
     "futs_prdy_ctrt": "-1.40", "prdy_vrss_sign": "5", "acml_vol": "312"},
]}


def test_parse_board_maps_documented_fields():
    rows = fx.parse_board(_BOARD_JS)
    assert len(rows) == 2
    assert rows[0] == {"code": "101W09", "name": "미니F 202609", "price": 885.25,
                       "rate": -1.49, "sign": "down", "volume": 141272}


def test_parse_board_returns_empty_on_failure_response():
    assert fx.parse_board({"rt_cd": "1", "msg1": "조회할 자료가 없습니다"}) == []
    assert fx.parse_board({}) == []


def test_pick_front_month_is_the_most_traded_row():
    """월물은 롤오버되므로 코드가 아니라 거래량으로 고른다."""
    assert fx.pick_front_month(fx.parse_board(_BOARD_JS))["code"] == "101W09"
    assert fx.pick_front_month([]) is None


# ffcode.mst 실제 레이아웃(2026-07-31 실측): 종목코드 0:32, 시리즈명 82:132, 총 223자
def _ff_row(code, name):
    return code.ljust(32) + "YYN" + " " * 47 + name.ljust(50) + " " * 91


_FF_TEXT = "\n".join([
    _ff_row("NQU26", "E-mini Nasdaq100-202609"),
    _ff_row("NQZ26", "E-mini Nasdaq100-202612"),
    _ff_row("NQU26-Z26", "E-mini Nasdaq100-2609-2612"),   # 스프레드
    _ff_row("MNQU26", "Micro E-mini Nasdaq100-202609"),   # 마이크로
    _ff_row("MNDU26", "MSCI Indonesia-202609"),           # 이름이 나스닥이 아님
])


def test_parse_ff_master_reads_fixed_width_fields():
    rows = fx.parse_ff_master(_FF_TEXT)
    assert len(rows) == 5
    assert rows[0] == {"code": "NQU26", "name": "E-mini Nasdaq100-202609"}


def test_pick_nq_series_takes_nearest_expiry_emini():
    """코드 접두로 고르면 안 된다 — MND*는 나스닥이 아니라 MSCI Indonesia다."""
    import datetime as dt
    rows = fx.parse_ff_master(_FF_TEXT)
    got = fx.pick_nq_series(rows, now=dt.datetime(2026, 7, 31, 12, 0, tzinfo=KST))
    assert got == "NQU26"


def test_pick_nq_series_rolls_to_next_when_current_expired():
    import datetime as dt
    rows = fx.parse_ff_master(_FF_TEXT)
    got = fx.pick_nq_series(rows, now=dt.datetime(2026, 10, 1, 12, 0, tzinfo=KST))
    assert got == "NQZ26"


def test_pick_nq_series_returns_none_when_absent():
    assert fx.pick_nq_series([]) is None


def test_download_ff_master_caches_and_reuses(tmp_path):
    """공개 파일이라 인증 불필요. 12시간 캐시 — 두 번째 호출은 네트워크를 타지 않는다."""
    from backend.flow import kis
    calls = []

    def _fetch(url):
        calls.append(url)
        return _FF_TEXT

    t1 = kis.download_ff_master(str(tmp_path), fetch=_fetch)
    t2 = kis.download_ff_master(str(tmp_path), fetch=_fetch)
    assert t1 == t2 == _FF_TEXT
    assert len(calls) == 1                       # 두 번째는 캐시


def test_download_ff_master_keeps_stale_cache_on_failure(tmp_path):
    """월물 코드는 만기 전까지 유효 — 낡은 캐시가 무응답보다 낫다."""
    from backend.flow import kis

    def _boom(url):
        raise RuntimeError("network down")

    kis.download_ff_master(str(tmp_path), fetch=lambda url: _FF_TEXT)
    assert kis.download_ff_master(str(tmp_path), ttl_sec=0.0, fetch=_boom) == _FF_TEXT


def test_parse_overseas_reads_price_and_rate():
    """HHDFC55010000 응답. 실제 키 이름은 G3에서 확인해 좁힌다(현재는 후보 중 첫 존재 키)."""
    js = {"rt_cd": "0", "output1": {"last": "27713.25", "prdy_ctrt": "-0.75"}}
    assert fx.parse_overseas(js) == {"price": 27713.25, "rate": -0.75}


def test_parse_overseas_returns_none_on_failure():
    assert fx.parse_overseas({"rt_cd": "1"}) is None
    assert fx.parse_overseas({"rt_cd": "0", "output1": {}}) is None
