"""시장 스캐너 파서·픽 로직·캐시·라우트 테스트 (픽스처 = 2026-07-10 실응답 기반)."""
import asyncio

from backend.flow.scanner import (
    build_picks,
    fetch_scan,
    parse_fit_rank,
    parse_fluctuation,
    parse_volume_rank,
)


def _fit_row(code="005930", name="삼성전자"):
    return {"hts_kor_isnm": name, "mksc_shrn_iscd": code, "ntby_qty": "374000",
            "stck_prpr": "289500", "prdy_vrss_sign": "2", "prdy_vrss": "11500",
            "prdy_ctrt": "4.14", "acml_vol": "10286907",
            "frgn_ntby_qty": "374000", "orgn_ntby_qty": "1113000",
            "frgn_ntby_tr_pbmn": "108273", "orgn_ntby_tr_pbmn": "322214"}


def test_parse_fit_rank_units_and_filter():
    js = {"rt_cd": "0", "output": [
        _fit_row(),
        _fit_row(code="Q530107", name="ETN아티팩트"),  # 비 6자리 코드 방어(실측)
    ]}
    rows = parse_fit_rank(js)
    assert len(rows) == 1
    r = rows[0]
    assert r["code"] == "005930" and r["name"] == "삼성전자"
    assert r["price"] == 289500 and r["sign"] == "up" and r["rate"] == 4.14
    assert r["frgn_qty"] == 374000
    assert r["frgn_value"] == 108273 * 1_000_000  # 백만원 → 원 (실측 검증 단위)
    assert r["orgn_value"] == 322214 * 1_000_000


def test_parse_volume_rank():
    js = {"rt_cd": "0", "output": [
        {"hts_kor_isnm": "SK하이닉스", "mksc_shrn_iscd": "000660", "data_rank": "1",
         "stck_prpr": "2215000", "prdy_vrss_sign": "2", "prdy_vrss": "29000",
         "prdy_ctrt": "1.33", "acml_vol": "2786886", "vol_inrt": "44.51",
         "acml_tr_pbmn": "6190460093500"}]}
    rows = parse_volume_rank(js)
    assert rows[0]["code"] == "000660" and rows[0]["rank"] == 1
    assert rows[0]["value"] == 6190460093500  # acml_tr_pbmn은 raw 원(실측)
    assert rows[0]["vol_change"] == 44.51


def test_parse_fluctuation_uses_different_code_key():
    js = {"rt_cd": "0", "output": [
        {"stck_shrn_iscd": "073240", "data_rank": "1", "hts_kor_isnm": "금호타이어",
         "stck_prpr": "7800", "prdy_vrss": "1800", "prdy_vrss_sign": "1",
         "prdy_ctrt": "30.00", "acml_vol": "21485132", "cnnt_ascn_dynu": "1"}]}
    rows = parse_fluctuation(js)
    assert rows[0]["code"] == "073240" and rows[0]["rate"] == 30.0
    assert rows[0]["limit_up"] is True  # sign '1' = 상한가


def test_build_picks_cross_signals():
    frgn = [{"code": "000660", "name": "SK하이닉스", "frgn_value": 5} ,
            {"code": "111111", "name": "외인만", "frgn_value": 1}]
    orgn = [{"code": "000660", "name": "SK하이닉스"}, {"code": "222222", "name": "기관만"}]
    value_top = [{"code": "000660"}, {"code": "222222"}]
    gainers = [{"code": "333333"}]
    picks = build_picks(frgn, orgn, value_top, gainers)
    codes = {p["code"]: p for p in picks}
    assert "000660" in codes  # 외인+기관+거래대금 → 최우선
    assert set(codes["000660"]["reasons"]) == {"외인매수", "기관매수", "거래대금상위"}
    assert "222222" in codes and codes["222222"]["reasons"] == ["기관매수", "거래대금상위"]
    assert "111111" not in codes  # 모멘텀(거래대금/급등) 교차 없음 → 제외
    assert "333333" not in codes  # 수급 없음 → 제외


def test_fetch_scan_caches(monkeypatch):
    import backend.flow.scanner as sc
    monkeypatch.setattr(sc, "_cache", {"ts": 0.0, "data": None})
    calls = {"n": 0}

    class FakeClient:
        async def _get(self, path, tr_id, params):
            calls["n"] += 1
            if "fluctuation" in path:
                return {"rt_cd": "0", "output": []}
            return {"rt_cd": "0", "output": [_fit_row()]}

    loop = asyncio.new_event_loop()
    try:
        d1 = loop.run_until_complete(fetch_scan(client=FakeClient()))
        n1 = calls["n"]
        d2 = loop.run_until_complete(fetch_scan(client=FakeClient()))
    finally:
        loop.close()
    assert n1 == 5  # 외인매수/외인매도/기관매수/거래대금/급등 = 5콜
    assert calls["n"] == n1  # 60초 내 재호출은 캐시
    assert d1 is d2
    assert d1["sections"]["frgn_buy"][0]["code"] == "005930"
    assert "asof" in d1 and "picks" in d1


def test_scanner_routes(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.app import app
    from backend.config import settings
    client = TestClient(app)

    r = client.get("/scanner")
    assert r.status_code == 200 and "수급 스캐너" in r.text
    assert "/api/scanner" in r.text and "투자 유의" in r.text

    monkeypatch.setattr(settings, "kis_app_key", None)
    assert client.get("/api/scanner").status_code == 503  # 키 없으면 안내

    monkeypatch.setattr(settings, "kis_app_key", "k")
    monkeypatch.setattr(settings, "kis_app_secret", "s")
    import backend.api.app as appmod

    async def fake_scan(client=None):
        return {"asof": "11:30:00", "sections": {}, "picks": []}
    monkeypatch.setattr(appmod.flow_scanner, "fetch_scan", fake_scan)
    r = client.get("/api/scanner")
    assert r.status_code == 200 and r.json()["asof"] == "11:30:00"


def test_dashboard_links_scanner():
    from backend.report.dashboard import render_dashboard
    html = render_dashboard([], [], "2026-07-10", pwa=True)
    assert "/scanner" in html
