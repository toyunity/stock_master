"""KIS 웹소켓 프레임 파서 테스트.

픽스처는 공식 open-trading-api 리포에서 검증한 필드 순서로 제작:
- H0STCNT0(실시간 체결가) 46필드, H0STPGM0(종목별 프로그램매매) 11필드
- 데이터 프레임 '0|TRID|N|f1^f2^...' (N레코드 연접), JSON 프레임(ACK/PINGPONG)
"""
import json

from backend.flow.kis import (
    build_subscribe,
    is_pingpong,
    parse_ccnl,
    parse_program,
    split_frames,
)


def _ccnl_record(price="2187000", side="1"):
    """H0STCNT0 46필드 레코드. 사용 인덱스만 의미값, 나머지는 자리 채움."""
    f = ["0"] * 46
    f[0] = "000660"      # MKSC_SHRN_ISCD
    f[1] = "093015"      # STCK_CNTG_HOUR
    f[2] = price         # STCK_PRPR
    f[3] = "5"           # PRDY_VRSS_SIGN (4/5=하락)
    f[4] = "-41000"      # PRDY_VRSS
    f[5] = "-1.84"       # PRDY_CTRT
    f[12] = "15"         # CNTG_VOL
    f[13] = "1179948"    # ACML_VOL
    f[14] = "2593885000000"  # ACML_TR_PBMN
    f[18] = "112.34"     # CTTR(체결강도)
    f[21] = side         # CCLD_DVSN (1=매수, 5=매도)
    return f


_PGM_RECORD = ["000660", "093016", "1000", "2187000000", "1500",
               "3280500000", "500", "1093500000", "200", "300", "150"]


def test_split_frames_single_ccnl():
    raw = "0|H0STCNT0|001|" + "^".join(_ccnl_record())
    kind, (tr_id, records) = split_frames(raw)
    assert kind == "data" and tr_id == "H0STCNT0"
    assert len(records) == 1 and len(records[0]) == 46
    assert records[0][2] == "2187000"


def test_split_frames_multi_record():
    two = "^".join(_ccnl_record()) + "^" + "^".join(_ccnl_record(price="2188000"))
    kind, (tr_id, records) = split_frames("0|H0STCNT0|002|" + two)
    assert len(records) == 2
    assert records[0][2] == "2187000" and records[1][2] == "2188000"


def test_split_frames_json_ack():
    ack = json.dumps({"header": {"tr_id": "H0STCNT0"},
                      "body": {"rt_cd": "0", "msg1": "SUBSCRIBE SUCCESS"}})
    kind, obj = split_frames(ack)
    assert kind == "json" and obj["body"]["rt_cd"] == "0"


def test_split_frames_garbage_returns_none():
    assert split_frames("not|a^frame") is None


def test_is_pingpong():
    pp = json.dumps({"header": {"tr_id": "PINGPONG", "datetime": "20260710093000"}})
    assert is_pingpong(pp) is True
    assert is_pingpong(json.dumps({"header": {"tr_id": "H0STCNT0"}})) is False
    assert is_pingpong("0|H0STCNT0|001|x") is False


def test_parse_ccnl_buy_tick():
    d = parse_ccnl(_ccnl_record())
    assert d["t"] == "09:30:15"
    assert d["price"] == 2187000 and d["vol"] == 15
    assert d["acml_vol"] == 1179948 and d["acml_value"] == 2593885000000
    assert d["rate"] == -1.84 and d["sign"] == "down"
    assert d["strength"] == 112.34
    assert d["side"] == "buy"


def test_parse_ccnl_sell_side_and_up_sign():
    rec = _ccnl_record(side="5")
    rec[3] = "2"  # 상승
    d = parse_ccnl(rec)
    assert d["side"] == "sell" and d["sign"] == "up"


def test_parse_program_record():
    d = parse_program(_PGM_RECORD)
    assert d["t"] == "09:30:16"
    assert d["sell_qty"] == 1000 and d["sell_value"] == 2187000000
    assert d["buy_qty"] == 1500 and d["buy_value"] == 3280500000
    assert d["net_qty"] == 500 and d["net_value"] == 1093500000


def test_build_subscribe_roundtrip():
    msg = json.loads(build_subscribe("KEY123", "H0STPGM0", "000660"))
    assert msg["header"]["approval_key"] == "KEY123"
    assert msg["header"]["tr_type"] == "1"
    assert msg["header"]["custtype"] == "P"
    assert msg["body"]["input"] == {"tr_id": "H0STPGM0", "tr_key": "000660"}
    off = json.loads(build_subscribe("K", "H0STCNT0", "000660", on=False))
    assert off["header"]["tr_type"] == "0"
