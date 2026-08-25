"""KIS REST 응답 파서 + 토큰 캐시 테스트 (네트워크 없음 — 문서 필드명 기반 목 JSON)."""
import asyncio
import json
import time

from backend.flow.kis import (
    KisClient,
    parse_daily_investor,
    parse_estimate,
    parse_program_trend,
)


def test_parse_fundamentals_from_inquire_price():
    """inquire-price(FHKST01010100) output의 밸류 필드 → {per,pbr,eps,bps,52주,52주위치}.
    필드는 우리가 이미 부르는 응답에 존재(2026-07-18 라이브 실측: SK하이닉스)."""
    from backend.flow.kis import parse_fundamentals
    js = {"rt_cd": "0", "output": {
        "stck_prpr": "1842000", "per": "31.24", "pbr": "10.55",
        "eps": "58955.00", "bps": "174539.00",
        "w52_hgpr": "2987000", "w52_lwpr": "245000"}}
    f = parse_fundamentals(js)
    assert f["per"] == 31.24 and f["pbr"] == 10.55
    assert f["eps"] == 58955.0 and f["bps"] == 174539.0
    assert f["w52_high"] == 2987000 and f["w52_low"] == 245000
    assert f["w52_pos"] == 58.2                       # (184.2-24.5)/(298.7-24.5)


def test_parse_fundamentals_handles_missing_and_failure():
    from backend.flow.kis import parse_fundamentals
    assert parse_fundamentals({"rt_cd": "1"}) is None         # 실패 응답
    # 적자(per/pbr 빈값)·52주 결측 → 해당 필드 None, 크래시 금지
    f = parse_fundamentals({"rt_cd": "0", "output": {
        "stck_prpr": "1000", "per": "", "pbr": "0.00", "eps": "-500.00"}})
    assert f["per"] is None and f["pbr"] is None               # 빈값·0은 None
    assert f["eps"] == -500.0                                   # 적자 EPS는 음수 유지
    assert f["w52_pos"] is None                                 # 52주 결측 → 위치 None


def test_parse_top_view():
    """hts-top-view(HHMCM000100C0) → 조회상위 코드 배열(순위순, 빈코드 제외). 실측: 코드만 옴."""
    from backend.flow.kis import parse_top_view
    js = {"rt_cd": "0", "output1": [
        {"mrkt_div_cls_code": "J", "mksc_shrn_iscd": "005930"},
        {"mrkt_div_cls_code": "J", "mksc_shrn_iscd": "000660"},
        {"mrkt_div_cls_code": "J", "mksc_shrn_iscd": ""}]}
    assert parse_top_view(js) == ["005930", "000660"]
    assert parse_top_view({"rt_cd": "1"}) == []


def test_parse_asking():
    """inquire-asking-price-exp-ccn(output1) → 호가 사다리 + 총잔량 + 매수세%. 실측 SK하이닉스."""
    from backend.flow.kis import parse_asking
    o1 = {"askp1": "1842000", "askp_rsqn1": "30790",
          "askp2": "1843000", "askp_rsqn2": "12016",
          "askp3": "0", "askp_rsqn3": "0",              # 빈 레벨은 컷
          "bidp1": "1841000", "bidp_rsqn1": "8624",
          "bidp2": "1840000", "bidp_rsqn2": "18230",
          "total_askp_rsqn": "61953", "total_bidp_rsqn": "48666"}
    a = parse_asking({"rt_cd": "0", "output1": o1})
    assert a["asks"][0] == {"price": 1842000, "qty": 30790}
    assert len(a["asks"]) == 2 and len(a["bids"]) == 2      # 0가격 레벨 제외
    assert a["total_ask"] == 61953 and a["total_bid"] == 48666
    assert a["bid_ratio"] == 44.0                          # 48666/(61953+48666)
    assert parse_asking({"rt_cd": "1"}) is None


def test_parse_index():
    """inquire-index-price(FHPUP02100000) → {price,change,rate,sign}. 실측 코스피(2026-07-18)."""
    from backend.flow.kis import parse_index
    js = {"rt_cd": "0", "output": {
        "bstp_nmix_prpr": "6820.60", "bstp_nmix_prdy_vrss": "-463.81",
        "prdy_vrss_sign": "5", "bstp_nmix_prdy_ctrt": "-6.37"}}
    ix = parse_index(js)
    assert ix == {"price": 6820.60, "change": -463.81, "rate": -6.37, "sign": "down"}
    assert parse_index({"rt_cd": "1"}) is None


def test_parse_financials():
    """financial-ratio(FHKST66430300) → 최근 분기 배열 {period,roe,eps,debt,sales_growth}.
    실측 SK하이닉스 [0](2026-03분기)."""
    from backend.flow.kis import parse_financials
    js = {"rt_cd": "0", "output": [
        {"stac_yymm": "202603", "grs": "198.0700", "roe_val": "61.16",
         "eps": "56066.00", "lblt_rate": "35.5600"},
        {"stac_yymm": "202512", "grs": "150.0000", "roe_val": "40.00",
         "eps": "40000.00", "lblt_rate": "40.0000"}]}
    fs = parse_financials(js)
    assert fs[0] == {"period": "2026-03", "roe": 61.16, "eps": 56066.0,
                     "debt": 35.56, "sales_growth": 198.07}
    assert len(fs) == 2 and fs[1]["period"] == "2025-12"
    assert parse_financials({"rt_cd": "1"}) == []


def test_parse_daily_investor():
    js = {"rt_cd": "0", "output": [
        {"stck_bsop_date": "20260709", "stck_clpr": "2186000",
         "prsn_ntby_qty": "120000", "frgn_ntby_qty": "-350000",
         "orgn_ntby_qty": "210000"},
        {"stck_bsop_date": "20260708", "stck_clpr": "2228000",
         "prsn_ntby_qty": "-80000", "frgn_ntby_qty": "150000",
         "orgn_ntby_qty": "-60000"},
    ]}
    rows = parse_daily_investor(js)
    assert rows[0] == {"date": "2026-07-09", "prsn": 120000, "frgn": -350000,
                       "orgn": 210000, "close": 2186000}
    assert rows[1]["frgn"] == 150000


def test_parse_estimate_maps_hour_gb_and_sorts_ascending():
    # 실API(2026-07-10 실측)는 최신순으로 내려온다 → 파서가 오름차순 보장해야
    # '마지막 행=최신' 계약(UI·snapshot)이 성립한다.
    js = {"rt_cd": "0", "output2": [
        {"bsop_hour_gb": "2", "frgn_fake_ntby_qty": "-70000",
         "orgn_fake_ntby_qty": "30000", "sum_fake_ntby_qty": "-40000"},
        {"bsop_hour_gb": "1", "frgn_fake_ntby_qty": "-50000",
         "orgn_fake_ntby_qty": "0", "sum_fake_ntby_qty": "-50000"},
    ]}
    rows = parse_estimate(js)
    assert rows[0] == {"asof": "09:30", "frgn": -50000, "orgn": 0, "sum": -50000}
    assert rows[-1]["asof"] == "10:00" and rows[-1]["orgn"] == 30000


def test_parse_estimate_empty_output():
    assert parse_estimate({"rt_cd": "0", "output2": []}) == []
    assert parse_estimate({"rt_cd": "1"}) == []


def test_parse_program_trend_sorts_ascending():
    js = {"rt_cd": "0", "output": [
        {"bsop_hour": "094000", "whol_smtn_ntby_qty": "800",
         "whol_smtn_ntby_tr_pbmn": "1750000000"},
        {"bsop_hour": "093000", "whol_smtn_ntby_qty": "500",
         "whol_smtn_ntby_tr_pbmn": "1093500000"},
    ]}
    pts = parse_program_trend(js)
    assert pts[0] == {"t": "09:30:00", "net_qty": 500, "net_value": 1093500000}
    assert pts[-1]["net_value"] == 1750000000  # 차트 요구사항: 시간 오름차순


def test_drop_empty_daily_removes_unsettled_today():
    from backend.flow.kis import drop_empty_daily
    rows = [{"date": "2026-07-10", "prsn": 0, "frgn": 0, "orgn": 0, "close": 2223000},
            {"date": "2026-07-09", "prsn": 100, "frgn": -200, "orgn": 90,
             "close": 2186000}]
    out = drop_empty_daily(rows)
    assert len(out) == 1 and out[0]["date"] == "2026-07-09"


def _detail_row(**over):
    """FHPTJ04160001 output2 실응답 행(2026-07-09 SK하이닉스 라이브 캡처 기반)."""
    r = {"stck_bsop_date": "20260709", "stck_clpr": "2186000",
         "prsn_ntby_qty": "-179724", "frgn_ntby_qty": "-209485",
         "orgn_ntby_qty": "404365",
         "scrt_ntby_qty": "-10150", "ivtr_ntby_qty": "295211",
         "pe_fund_ntby_vol": "55420",  # 사모는 접미사가 _vol (실측)
         "bank_ntby_qty": "1672", "insu_ntby_qty": "13630",
         "mrbn_ntby_qty": "-325", "fund_ntby_qty": "48907",
         "etc_corp_ntby_vol": "-15156", "etc_orgt_ntby_vol": "0",
         "fund_ntby_tr_pbmn": "113357", "ivtr_ntby_tr_pbmn": "645575",
         "scrt_ntby_tr_pbmn": "-23268", "pe_fund_ntby_tr_pbmn": "121153",
         "bank_ntby_tr_pbmn": "3655", "insu_ntby_tr_pbmn": "29802",
         "mrbn_ntby_tr_pbmn": "-710", "etc_corp_ntby_tr_pbmn": "-33131"}
    r.update(over)
    return r


def test_parse_investor_detail_latest_confirmed_day():
    from backend.flow.kis import parse_investor_detail
    js = {"rt_cd": "0", "output2": [_detail_row(),
                                    _detail_row(stck_bsop_date="20260708")]}
    d = parse_investor_detail(js)
    assert d["date"] == "2026-07-09"  # output2[0] = 최신 확정일
    by = {r["name"]: r for r in d["rows"]}
    assert by["연기금"]["qty"] == 48907
    assert by["연기금"]["value"] == 113357 * 1_000_000  # 백만원 → 원
    assert by["투신"]["qty"] == 295211
    assert by["사모펀드"]["qty"] == 55420   # _vol 접미사 예외
    assert by["기타법인"]["qty"] == -15156  # _vol 접미사 예외
    # 실데이터 불변식: 기관 세부 7종 합 == 기관계 (라이브에서 정확히 성립)
    detail7 = sum(by[n]["qty"] for n in
                  ("금융투자", "투신", "사모펀드", "은행", "보험", "기타금융", "연기금"))
    assert detail7 == 404365
    assert d["rows"][0]["qty"] == 295211  # |순매수| 내림차순 정렬


def test_parse_investor_detail_rejects_time_limit():
    from backend.flow.kis import parse_investor_detail
    # 장중(00:00~15:40)에 오늘 날짜로 조회하면 HTTP 200 + rt_cd=2 (실측)
    assert parse_investor_detail({"rt_cd": "2", "msg1": "TIME LIMIT"}) is None
    assert parse_investor_detail({"rt_cd": "0", "output2": []}) is None


def test_investor_detail_falls_back_to_previous_day(monkeypatch):
    import datetime as dt
    c = KisClient("k", "s", "/tmp")
    today = dt.date.today().strftime("%Y%m%d")
    calls = []

    async def fake_get(path, tr_id, params):
        calls.append(params["FID_INPUT_DATE_1"])
        if params["FID_INPUT_DATE_1"] == today:
            return {"rt_cd": "2", "msg1": "TIME LIMIT 00:00 ~ 15:40"}
        return {"rt_cd": "0", "output2": [_detail_row()]}
    monkeypatch.setattr(c, "_get", fake_get)
    d = asyncio.get_event_loop().run_until_complete(c.investor_detail("000660"))
    assert d["date"] == "2026-07-09"
    assert len(calls) == 2 and calls[0] == today  # 오늘 시도 → 전일 폴백


def test_parse_price():
    from backend.flow.kis import parse_price
    js = {"rt_cd": "0", "output": {
        "stck_prpr": "2244000", "prdy_vrss": "58000", "prdy_vrss_sign": "2",
        "prdy_ctrt": "2.65", "acml_vol": "3317403",
        "acml_tr_pbmn": "7371903475500"}}
    d = parse_price(js)
    assert d == {"price": 2244000, "sign": "up", "change": 58000, "rate": 2.65,
                 "acml_vol": 3317403, "acml_value": 7371903475500}
    assert parse_price({"rt_cd": "1"}) is None


def test_get_retries_on_5xx(monkeypatch):
    # KIS는 연속 호출에 간헐 HTTP 500을 반환(실측 2026-07-10) — 재시도로 흡수해야 한다.
    import httpx

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(200, json={"rt_cd": "0", "output": []})

    c = KisClient("k", "s", "/tmp")
    monkeypatch.setattr(c, "_client_factory",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def fake_token():
        return "TOK"
    monkeypatch.setattr(c, "token", fake_token)
    monkeypatch.setattr("backend.flow.kis._RETRY_BASE_SEC", 0.01)  # 테스트 가속
    js = asyncio.get_event_loop().run_until_complete(
        c._get("/x", "TR", {}))
    assert js["rt_cd"] == "0" and calls["n"] == 3  # 500 두 번 → 재시도 끝에 성공


def test_token_disk_cache_reused_without_network(tmp_path):
    cache = {"token": "CACHED-TOKEN", "expires_at": time.time() + 3600}
    (tmp_path / "kis_token.json").write_text(json.dumps(cache), encoding="utf-8")
    c = KisClient("appkey", "appsecret", str(tmp_path))
    tok = asyncio.get_event_loop().run_until_complete(c.token())
    assert tok == "CACHED-TOKEN"  # 유효 캐시면 네트워크 호출 없이 재사용


def test_token_expired_cache_ignored(tmp_path, monkeypatch):
    cache = {"token": "STALE", "expires_at": time.time() - 10}
    (tmp_path / "kis_token.json").write_text(json.dumps(cache), encoding="utf-8")
    c = KisClient("appkey", "appsecret", str(tmp_path))

    async def fake_issue():
        return {"access_token": "FRESH", "expires_in": 86400}
    monkeypatch.setattr(c, "_issue_token", fake_issue)
    tok = asyncio.get_event_loop().run_until_complete(c.token())
    assert tok == "FRESH"
    saved = json.loads((tmp_path / "kis_token.json").read_text(encoding="utf-8"))
    assert saved["token"] == "FRESH"  # 새 토큰이 디스크에 저장됨


def _counting_client(tmp_path, issued):
    """발급 횟수를 세는 KisClient. token()이 성공 후 디스크에 캐시를 쓰므로,
    뒤이어 락을 잡은 쪽은 이중검사에서 그 파일을 읽고 발급을 건너뛴다."""
    c = KisClient("KEY", "SECRET", str(tmp_path))

    async def fake_issue():
        await asyncio.sleep(0)          # 락이 없으면 여기서 서로 끼어든다
        issued.append(1)
        return {"access_token": "TOK%d" % len(issued), "expires_in": 86400}

    c._issue_token = fake_issue
    return c


def test_token_lock_survives_a_throwaway_event_loop(tmp_path):
    """cli._live_prices()는 new_event_loop()로 KIS를 부르고 그 루프를 닫는다.

    Lock을 인스턴스에 영구 기억하면 그 죽은 루프에 묶여, 다음 토큰 만료 때
    서버 루프에서 'attached to a different loop'로 터진다 — 분봉이 통째로 빈
    결과가 됐다(2026-08-25 실사고). 캐시가 살아 있는 동안엔 락 앞에서 return
    하므로 24시간에 한 번, 만료되는 그 순간에만 발현된다."""
    issued = []
    c = _counting_client(tmp_path, issued)
    loop1 = asyncio.new_event_loop()        # ① 일회용 루프에서 최초 발급(락 생성)
    try:
        loop1.run_until_complete(c.token())
    finally:
        loop1.close()
    (tmp_path / "kis_token.json").unlink()  # ② 만료된 척 — 락까지 도달하게
    # ③ 서버 루프(다른 루프)에서 **동시에** 두 번. 경합이 있어야 터진다 —
    #    3.9의 Lock.acquire()는 비경합이면 future를 안 만들어 죽은 루프여도
    #    그냥 통과한다(실사고 트레이스백도 `await fut` 줄이었다).
    async def twice():   # gather는 반드시 러닝 루프 안에서 — 밖에서 만들면
        await asyncio.gather(c.token(), c.token())   # 스레드 기본 루프에 묶인다

    loop2 = asyncio.new_event_loop()
    try:
        loop2.run_until_complete(twice())
    finally:
        loop2.close()
    assert len(issued) == 2                 # 죽은 루프의 락이면 여기 오기 전에 터진다


def test_token_issue_is_serialized_across_client_instances(tmp_path):
    """KisClient는 candles·engine(종목마다)·scanner·semi로 인스턴스가 여럿이다.

    락이 인스턴스별이면 만료 순간 각자 발급 → KIS 1분 1회 제한 → 403 →
    엔진이 데모로 강등된다(2026-08-25 실사고: 하루치 시세가 시뮬레이션으로).
    발급은 인스턴스가 아니라 프로세스 단위로 줄 세운다."""
    issued = []
    a = _counting_client(tmp_path, issued)
    b = _counting_client(tmp_path, issued)

    async def both():
        await asyncio.gather(a.token(), b.token())

    asyncio.new_event_loop().run_until_complete(both())
    assert len(issued) == 1                 # 뒤에 온 쪽은 이중검사에서 캐시를 본다


def test_no_key_refuses_even_with_valid_cached_token(tmp_path):
    """키가 비면 디스크에 **유효한** 토큰이 남아 있어도 호출을 막는다.

    하네스(harness/core/server.py)는 SM_KIS_APP_KEY를 비워 'KIS 미접촉'을 보장하는데,
    가드가 없으면 24시간짜리 캐시 토큰으로 인증이 통과해 실 KIS로 나간다
    (2026-08-12 실측: `harness verify`가 index-daily·overseas-chartprice를 실제로 때렸다).
    worldidx._index_group의 "키가 없으면 토큰 발급이 예외로 떨어진다"는 전제도 이 가드가
    있어야 참이 된다."""
    cache = {"token": "CACHED-AND-VALID", "expires_at": time.time() + 86400}
    (tmp_path / "kis_token.json").write_text(json.dumps(cache), encoding="utf-8")
    c = KisClient("", "", str(tmp_path))
    assert c._cached_token() == "CACHED-AND-VALID"      # 캐시 자체는 멀쩡하다
    loop = asyncio.get_event_loop()
    for coro in (c.token(), c.approval_key()):
        try:
            loop.run_until_complete(coro)
        except RuntimeError as e:
            assert "키 없음" in str(e)
        else:
            raise AssertionError("키가 없는데 통과했다 — 실 KIS로 나갈 수 있다")
