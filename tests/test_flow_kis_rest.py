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
