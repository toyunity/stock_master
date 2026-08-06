"""KIS 웹소켓 프레임 파서 테스트.

픽스처는 공식 open-trading-api 리포에서 검증한 필드 순서로 제작:
- H0STCNT0(실시간 체결가) 46필드, H0STPGM0(종목별 프로그램매매) 11필드
- 데이터 프레임 '0|TRID|N|f1^f2^...' (N레코드 연접), JSON 프레임(ACK/PINGPONG)
"""
import asyncio
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


def test_ws_tr_ids_by_market_div():
    from backend.flow.kis import ws_tr_ids
    assert ws_tr_ids("UN") == ("H0UNCNT0", "H0UNPGM0")  # KRX+NXT 통합(기본)
    assert ws_tr_ids("J") == ("H0STCNT0", "H0STPGM0")
    assert ws_tr_ids("NX") == ("H0NXCNT0", "H0NXPGM0")
    assert ws_tr_ids("잘못") == ("H0UNCNT0", "H0UNPGM0")  # 미지정 → 통합


def test_default_market_div_is_un():
    from backend.config import Settings
    assert Settings().market_div == "UN"  # NXT가 대형주 거래량 30%+ (실측)


def test_subscribe_error_detection():
    from backend.flow.kis import subscribe_error
    ok = {"header": {"tr_id": "H0STCNT0"}, "body": {"rt_cd": "0", "msg1": "SUBSCRIBE SUCCESS"}}
    assert subscribe_error(ok) is None
    # 실측: 좀비 세션이 남아 있으면 rt_cd=9 OPSP8996 ALREADY → 직후 서버가 절단
    zombie = {"header": {"tr_id": "(null)"}, "body": {"rt_cd": "9", "msg_cd": "OPSP8996",
                                                      "msg1": "ALREADY IN USE appkey"}}
    assert "OPSP8996" in subscribe_error(zombie)
    assert subscribe_error({"header": {"tr_id": "PINGPONG"}}) is None


def test_invalid_approval_detection():
    # 승인키 만료(OPSP0011)는 캐시 폐기·재발급 대상, 좀비(OPSP8996 ALREADY)는 대기만 — 구분해야 한다.
    from backend.flow.kis import is_invalid_approval
    assert is_invalid_approval("OPSP0011 invalid approval : 9c394f31-...") is True
    assert is_invalid_approval("OPSP8996 ALREADY IN USE appkey") is False
    assert is_invalid_approval(None) is False
    assert is_invalid_approval("") is False


def test_reset_approval_clears_memory_cache():
    # 무효 승인키 폐기 → 다음 approval_key()가 재발급하도록 메모리 캐시를 비운다.
    from backend.flow.kis import KisClient
    c = KisClient("appkey", "appsecret", "/tmp")
    c._approval = "STALE-9c394f31"
    c.reset_approval()
    assert c._approval is None


def test_build_subscribe_roundtrip():
    msg = json.loads(build_subscribe("KEY123", "H0STPGM0", "000660"))
    assert msg["header"]["approval_key"] == "KEY123"
    assert msg["header"]["tr_type"] == "1"
    assert msg["header"]["custtype"] == "P"
    assert msg["body"]["input"] == {"tr_id": "H0STPGM0", "tr_key": "000660"}
    off = json.loads(build_subscribe("K", "H0STCNT0", "000660", on=False))
    # 해지는 "2"다. "0"을 보내면 KIS가 OPSP8997 invalid tr_type으로 거부하고,
    # 그 거부가 공유 세션 전체를 끊는다(2026-08-06 실측 로그).
    assert off["header"]["tr_type"] == "2"


# ── 토큰·승인키 발급 직렬화 ────────────────────────────────────────
# 2026-08-06 19:24 실사고: 토큰이 24시간 만료되는 찰나에 서버의 동시 KIS 호출이
# 각자 캐시 미스를 보고 각자 발급해 **알림톡이 4통** 날아갔다.

def _client(tmp_path, issued):
    from backend.flow.kis import KisClient

    class C(KisClient):
        async def _issue_token(self):
            issued.append(1)
            await asyncio.sleep(0.01)          # 실제 HTTP처럼 양보 지점을 만든다
            return {"access_token": "TOK%d" % len(issued), "expires_in": 86400}

    return C("k", "s", str(tmp_path))


def test_concurrent_token_calls_issue_only_once(tmp_path):
    """만료 순간에 10개가 동시에 물어도 발급은 1회여야 한다."""
    import asyncio as aio
    issued = []
    c = _client(tmp_path, issued)

    async def go():
        return await aio.gather(*[c.token() for _ in range(10)])

    toks = aio.run(go())
    assert len(issued) == 1, "발급 %d회 — 락이 없거나 이중검사가 빠졌다" % len(issued)
    assert set(toks) == {"TOK1"}               # 전원이 같은 토큰을 받았다


def test_second_call_uses_the_disk_cache(tmp_path):
    """한 번 받은 뒤엔 파일 캐시로 끝난다(다음 프로세스도 재발급 안 함)."""
    import asyncio as aio
    issued = []
    c = _client(tmp_path, issued)
    aio.run(c.token())
    aio.run(c.token())
    assert len(issued) == 1
    # 새 클라이언트(=재기동 흉내)도 같은 파일을 읽어 발급하지 않는다
    c2 = _client(tmp_path, issued)
    assert aio.run(c2.token()) == "TOK1" and len(issued) == 1


def test_expired_cache_still_issues(tmp_path):
    """만료된 캐시는 당연히 새로 받아야 한다 — 락이 발급을 막아버리면 안 된다."""
    import asyncio as aio
    import json as _json
    import time as _time
    issued = []
    c = _client(tmp_path, issued)
    (tmp_path / "kis_token.json").write_text(
        _json.dumps({"token": "OLD", "expires_at": _time.time() - 1}), encoding="utf-8")
    assert aio.run(c.token()) == "TOK1" and len(issued) == 1


def test_concurrent_approval_key_calls_issue_only_once(tmp_path, monkeypatch):
    """승인키도 같다 — 재기동 직후 여러 화면이 동시에 붙으면 겹친다."""
    import asyncio as aio
    from backend.flow.kis import KisClient
    calls = []

    class C(KisClient):
        pass

    c = C("k", "s", str(tmp_path))

    class _R:
        def raise_for_status(self): pass
        def json(self): return {"approval_key": "AK"}

    class _Cli:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw):
            calls.append(1)
            await aio.sleep(0.01)
            return _R()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Cli())

    async def go():
        return await aio.gather(*[c.approval_key() for _ in range(8)])

    keys = aio.run(go())
    assert len(calls) == 1 and set(keys) == {"AK"}
