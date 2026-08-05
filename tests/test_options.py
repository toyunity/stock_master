"""옵션 지표 순수 함수 — fixture만으로 100%. KIS·네트워크 미접촉.

이 파일의 핵심 회귀 3개(2026-08-05 실측이 만든 규칙):
  · wall()이 범위 밖 최대값(사다리 양 끝)을 집으면 안 된다
  · atm_iv()가 거래 0인 행사가를 쓰면 안 된다(IV가 낡아 51~61%로 나온다)
  · summarize()가 콜 벽을 내면 안 된다
"""
import datetime as dt

from backend.flow import options as opt
from backend.flow.kst import KST


def _row(strike, oi=0, chg=0, vol=0, iv=0.0):
    return {"strike": strike, "oi": oi, "oi_chg": chg, "vol": vol, "iv": iv}


def test_parse_quote_reads_output1_not_output():
    js = {"rt_cd": "0", "output1": {"acpr": "1000.0", "futs_prpr": "12.35",
                                    "acml_vol": "1,234", "hts_otst_stpl_qty": "5678",
                                    "otst_stpl_qty_icdc": "-224",
                                    "hts_ints_vltl": "87.12", "delta_val": "0.4821",
                                    "hts_rmnn_dynu": "9"}}
    q = opt.parse_quote(js)
    assert q["strike"] == 1000.0 and q["price"] == 12.35
    assert q["vol"] == 1234                     # 천단위 콤마
    assert q["oi"] == 5678 and q["oi_chg"] == -224    # 증감은 음수가 정상값이다
    assert q["iv"] == 87.12 and q["delta"] == 0.4821 and q["remain_days"] == 9


def test_parse_quote_rejects_error_and_empty_body():
    assert opt.parse_quote({"rt_cd": "1", "msg1": "초당 거래건수를 초과"}) is None
    assert opt.parse_quote({"rt_cd": "0", "output1": {}}) is None
    assert opt.parse_quote({"rt_cd": "0", "output": {"acpr": "1"}}) is None   # output은 안 본다
    assert opt.parse_quote(None) is None


def test_parse_quote_defaults_missing_fields_to_zero():
    q = opt.parse_quote({"rt_cd": "0", "output1": {"acpr": "1000.0"}})
    assert q["vol"] == 0 and q["oi"] == 0 and q["oi_chg"] == 0 and q["iv"] == 0.0


def test_put_call_ratio_and_zero_denominator():
    calls, puts = [_row(1000, vol=100), _row(1010, vol=100)], [_row(1000, vol=150)]
    assert opt.put_call_ratio(calls, puts) == 0.75
    assert opt.put_call_ratio([], puts) is None          # 0으로 나눈 값을 지어내지 않는다
    assert opt.put_call_ratio([_row(1000, vol=0)], puts) is None


def test_wall_ignores_the_ladder_edge_outside_the_band():
    """실측 재현 — 전 구간 최대는 최저 행사가 625.0(지수 −40%)에 있지만 그건
    폭락 보험이 경계에 쌓인 것이지 지지선이 아니다. ±20% 안에서는 1,000이 답."""
    puts = [_row(625.0, oi=100000), _row(900.0, oi=3000),
            _row(1000.0, oi=9000), _row(1200.0, oi=500)]
    w = opt.wall(puts, spot=1039.35, pct=20.0)
    assert w["strike"] == 1000.0
    assert opt.wall(puts, spot=1039.35, pct=60.0)["strike"] == 625.0   # 넓히면 끝이 잡힌다


def test_wall_requires_explicit_range():
    import inspect
    sig = inspect.signature(opt.wall)
    assert sig.parameters["pct"].default is inspect.Parameter.empty


def test_wall_returns_none_without_spot_or_rows():
    assert opt.wall([], 1000.0, 20.0) is None
    assert opt.wall([_row(1000, oi=5)], None, 20.0) is None
    assert opt.wall([_row(1000, oi=0)], 1000.0, 20.0) is None     # 미결제 0만 있으면 없음


def test_atm_iv_skips_untraded_strikes_with_stale_iv():
    """거래 0인 행사가의 IV는 낡았다(실측: 거래분 80~92% vs 무거래분 51~61%)."""
    calls = [_row(1040.0, vol=0, iv=55.0), _row(1050.0, vol=12, iv=88.0)]
    puts = [_row(1030.0, vol=0, iv=52.0)]
    a = opt.atm_iv(calls, puts, spot=1039.35)
    assert a["strike"] == 1050.0 and a["iv"] == 88.0     # 더 가깝지만 무거래인 1040을 건너뛴다
    assert opt.atm_iv([_row(1040.0, vol=0, iv=55.0)], [], 1039.35) is None


def test_top_changes_splits_up_and_down_by_magnitude():
    rows = [_row(1300, chg=2214), _row(1250, chg=800),
            _row(1597.5, chg=-224), _row(1100, chg=0)]
    t = opt.top_changes(rows, n=2)
    assert [r["strike"] for r in t["up"]] == [1300, 1250]
    assert [r["strike"] for r in t["down"]] == [1597.5]
    assert opt.top_changes([_row(1000, chg=0)])["up"] == []      # 0은 증감이 아니다


def test_histogram_keeps_zero_bins_and_sorts():
    rows = [_row(1010, oi=0), _row(1000, oi=5)]
    assert opt.histogram(rows, "oi") == [{"k": 1000, "v": 5}, {"k": 1010, "v": 0}]


def test_summarize_publishes_put_wall_but_never_call_wall():
    calls = [_row(1050, oi=9000, chg=100, vol=10, iv=90.0),
             _row(1300, oi=8000, chg=2214, vol=5, iv=95.0)]
    puts = [_row(1000, oi=7000, chg=1189, vol=20, iv=88.0)]
    s = opt.summarize(calls, puts, spot=1039.35)
    assert s["put_wall"] == 1000 and s["wall_pct"] == opt.WALL_PCT
    assert "call_wall" not in s                     # 정직성 규칙 — 콜 벽은 내지 않는다
    assert s["call_chg_sum"] == 2314 and s["put_chg_sum"] == 1189
    assert s["top_call"]["strike"] == 1300 and s["top_put"]["strike"] == 1000
    assert s["atm_iv"] == 90.0                      # spot에 가장 가까운 '거래된' 행사가


def test_summarize_survives_empty_board():
    s = opt.summarize([], [], spot=None)
    assert s["pcr"] is None and s["put_wall"] is None and s["atm_iv"] is None
    assert s["call_chg_sum"] == 0 and s["top_call"] is None


def test_session_of_covers_option_regular_hours():
    def at(h, m, day=5):
        return dt.datetime(2026, 8, day, h, m, tzinfo=KST)
    assert opt.session_of(at(9, 0)) == "live"
    assert opt.session_of(at(15, 44)) == "live"
    assert opt.session_of(at(15, 45)) == "closed"   # 15:45 마감
    assert opt.session_of(at(8, 59)) == "closed"    # 선물(08:45)과 다르다
    assert opt.session_of(at(11, 0, day=8)) == "closed"   # 2026-08-08 = 토요일


def test_month_label():
    assert opt.month_label("202608") == "8월물"
    assert opt.month_label("202612") == "12월물"
    assert opt.month_label("") == ""


def test_last_close_is_the_most_recent_weekday_1545():
    """직전 마감 시각 — 마감 후 캐시가 '다음 개장까지' 유효한지 판단하는 기준."""
    def at(y, m, d, h, mi):
        return dt.datetime(y, m, d, h, mi, tzinfo=KST)
    # 수요일 18:40 → 같은 날 15:45
    assert opt.last_close(at(2026, 8, 5, 18, 40)) == at(2026, 8, 5, 15, 45)
    # 수요일 08:00(개장 전) → 전날(화) 15:45
    assert opt.last_close(at(2026, 8, 5, 8, 0)) == at(2026, 8, 4, 15, 45)
    # 토요일 12:00 → 금요일 15:45
    assert opt.last_close(at(2026, 8, 8, 12, 0)) == at(2026, 8, 7, 15, 45)
    # 일요일 20:00 → 금요일 15:45(주말엔 마감이 없다)
    assert opt.last_close(at(2026, 8, 9, 20, 0)) == at(2026, 8, 7, 15, 45)
    # 월요일 08:00 → 금요일 15:45
    assert opt.last_close(at(2026, 8, 10, 8, 0)) == at(2026, 8, 7, 15, 45)
