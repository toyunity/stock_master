"""옵션 종목마스터 파싱 — 고정폭 cp949 레이아웃과 근월물 선택.

만기·행사가가 코드가 아니라 **이름 필드**에 있다는 게 이 모듈의 전부다
(2026-08-05 O1 실측: 코드의 '01608'은 상품+연월 축약이라 "202608"로 못 찾는다).
"""
import datetime as dt

from backend.flow import optmaster as om


def _line(head, code, isin, name):
    """마스터 한 행 조립 — [0]=구분 · [1:10]=단축코드 · [10:22]=ISIN · [22:]=이름."""
    return head + code.ljust(9) + isin.ljust(12) + name


# 2026-08-05 실제 마스터에서 뜬 모양: '5' 'B01608625' 'KR4B01686256' | 'C 202608   625.0'
_CALL = _line("5", "B01608625", "KR4B01686256", "C 202608   625.0")
_PUT = _line("6", "B01658625", "KR4B01686264", "P 202608   625.0")
_CALL_NEXT = _line("5", "B01609130", "KR4B01690001", "C 202609 1,300.0")
_FUTURE = _line("1", "A01609000", "KR4101SC0009", "F 202609")


def test_parse_master_reads_side_expiry_strike_from_name_field():
    rows = om.parse_master([_CALL, _PUT, _CALL_NEXT])
    assert len(rows) == 3
    c = rows[0]
    assert c["code"] == "B01608625" and c["side"] == "call"
    assert c["expiry"] == "202608" and c["strike"] == 625.0
    assert rows[1]["side"] == "put"
    assert rows[2]["strike"] == 1300.0          # 콤마 제거


def test_parse_master_skips_non_option_rows_and_garbage():
    rows = om.parse_master([_FUTURE, "", "5", _line("5", "B0160XXXX", "KR4X", "잘못된이름")])
    assert rows == []                            # 선물·빈행·형식 불일치는 조용히 버린다


def test_expiry_date_is_second_thursday():
    assert om.expiry_date("202608") == dt.date(2026, 8, 13)   # 8/6이 첫 목요일
    assert om.expiry_date("202609") == dt.date(2026, 9, 10)


def test_front_month_picks_earliest_unexpired_and_includes_expiry_day():
    rows = om.parse_master([_CALL, _CALL_NEXT])
    assert om.front_month(rows, dt.date(2026, 8, 5)) == "202608"
    assert om.front_month(rows, dt.date(2026, 8, 13)) == "202608"   # 만기 당일은 아직 거래
    assert om.front_month(rows, dt.date(2026, 8, 14)) == "202609"
    assert om.front_month(rows, dt.date(2026, 12, 1)) is None


def test_chain_splits_and_sorts_by_strike():
    rows = om.parse_master([_CALL_NEXT, _CALL, _PUT])
    ch = om.chain(rows, "202608")
    assert [r["strike"] for r in ch["calls"]] == [625.0]
    assert [r["strike"] for r in ch["puts"]] == [625.0]
    assert om.chain(rows, "202609")["puts"] == []


def test_load_uses_injected_fetch_and_caches_to_disk(tmp_path):
    payload = ("\n".join([_CALL, _PUT])).encode("cp949")
    calls = {"n": 0}

    def _fetch():
        calls["n"] += 1
        return payload

    rows = om.load(str(tmp_path), fetch=_fetch)
    assert len(rows) == 2 and calls["n"] == 1
    rows2 = om.load(str(tmp_path), fetch=_fetch)      # 하루 안 → 재다운로드 없음
    assert len(rows2) == 2 and calls["n"] == 1


def test_load_falls_back_to_stale_cache_when_download_fails(tmp_path):
    om.load(str(tmp_path), fetch=lambda: _CALL.encode("cp949"))

    def _boom():
        raise RuntimeError("네트워크 끊김")

    rows = om.load(str(tmp_path), force=True, fetch=_boom)
    assert len(rows) == 1        # 낡은 캐시라도 쓴다 — 만기·행사가는 하루 사이 안 바뀐다


def test_load_returns_empty_when_no_cache_and_download_fails(tmp_path):
    def _boom():
        raise RuntimeError("네트워크 끊김")

    assert om.load(str(tmp_path), fetch=_boom) == []
