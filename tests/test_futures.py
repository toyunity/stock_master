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


# cls_code=""(정규/대형) 응답 — 2026-07-31 장중 실측 shape. 코드/종목명 접두는 미니("101W09"/
# "미니F 202609")와 다르다(2e0216a에서 cls_code를 "MKI"→""로 확정한 이유 그대로 여기도 반영).
_BOARD_JS = {"rt_cd": "0", "output": [
    {"futs_shrn_iscd": "A01609", "hts_kor_isnm": "F 202609", "futs_prpr": "885.25",
     "futs_prdy_ctrt": "-1.49", "prdy_vrss_sign": "5", "acml_vol": "141272"},
    {"futs_shrn_iscd": "A01612", "hts_kor_isnm": "F 202612", "futs_prpr": "889.00",
     "futs_prdy_ctrt": "-1.40", "prdy_vrss_sign": "5", "acml_vol": "312"},
]}


def test_parse_board_maps_documented_fields():
    rows = fx.parse_board(_BOARD_JS)
    assert len(rows) == 2
    assert rows[0] == {"code": "A01609", "name": "F 202609", "price": 885.25,
                       "rate": -1.49, "sign": "down", "volume": 141272}


def test_parse_board_returns_empty_on_failure_response():
    assert fx.parse_board({"rt_cd": "1", "msg1": "조회할 자료가 없습니다"}) == []
    assert fx.parse_board({}) == []


def test_pick_front_month_is_the_most_traded_row():
    """월물은 롤오버되므로 코드가 아니라 거래량으로 고른다."""
    assert fx.pick_front_month(fx.parse_board(_BOARD_JS))["code"] == "A01609"
    assert fx.pick_front_month([]) is None


# ── pick_latest_pair — FDR(NQ=F) 결측(all-NaN) 행 대응, 나스닥 선물 칩의 현재/직전값 ──
_NAN = float("nan")


def test_pick_latest_pair_normal_case():
    """정상 시계열 — 마지막 값이 현재, 그 앞이 직전."""
    assert fx.pick_latest_pair([100.0, 105.0, 110.0]) == (110.0, 105.0)


def test_pick_latest_pair_skips_nan_hole_in_middle():
    """중간의 결측 행(2026-08-03 실측처럼)은 건너뛰고 유효값끼리만 현재/직전을 고른다."""
    assert fx.pick_latest_pair([100.0, _NAN, 110.0]) == (110.0, 100.0)


def test_pick_latest_pair_skips_nan_at_end():
    """가장 최근 행이 결측이면 그 앞의 유효값이 현재가가 된다."""
    assert fx.pick_latest_pair([100.0, 105.0, _NAN]) == (105.0, 100.0)


def test_pick_latest_pair_single_valid_returns_price_only_no_previous():
    """유효값이 하나뿐이면 (price, None) — 0.00%를 꾸며내지 않고 rate:None으로 넘긴다.
    fxchip()은 rate:None을 대시로 렌더한다(dashboard.py) — 여기선 함수가 실제로 None을
    돌려주는지만 증명한다(믿지 않고 검증)."""
    price, prev = fx.pick_latest_pair([_NAN, _NAN, 105.0])
    assert price == 105.0
    assert prev is None


def test_pick_latest_pair_all_nan_returns_none():
    """전부 결측이면 현재가 자체가 없다 — (None, None), 호출부가 칩을 생략한다."""
    assert fx.pick_latest_pair([_NAN, _NAN]) == (None, None)


def test_pick_latest_pair_empty_returns_none():
    assert fx.pick_latest_pair([]) == (None, None)
