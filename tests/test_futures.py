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
