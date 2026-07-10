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


def test_parse_estimate_maps_hour_gb():
    js = {"rt_cd": "0", "output2": [
        {"bsop_hour_gb": "1", "frgn_fake_ntby_qty": "-50000",
         "orgn_fake_ntby_qty": "0", "sum_fake_ntby_qty": "-50000"},
        {"bsop_hour_gb": "2", "frgn_fake_ntby_qty": "-70000",
         "orgn_fake_ntby_qty": "30000", "sum_fake_ntby_qty": "-40000"},
    ]}
    rows = parse_estimate(js)
    assert rows[0] == {"asof": "09:30", "frgn": -50000, "orgn": 0, "sum": -50000}
    assert rows[1]["asof"] == "10:00" and rows[1]["orgn"] == 30000


def test_parse_estimate_empty_output():
    assert parse_estimate({"rt_cd": "0", "output2": []}) == []
    assert parse_estimate({"rt_cd": "1"}) == []


def test_parse_program_trend():
    js = {"rt_cd": "0", "output": [
        {"bsop_hour": "093000", "whol_smtn_ntby_qty": "500",
         "whol_smtn_ntby_tr_pbmn": "1093500000"},
        {"bsop_hour": "094000", "whol_smtn_ntby_qty": "800",
         "whol_smtn_ntby_tr_pbmn": "1750000000"},
    ]}
    pts = parse_program_trend(js)
    assert pts[0] == {"t": "09:30:00", "net_qty": 500, "net_value": 1093500000}
    assert pts[-1]["net_value"] == 1750000000


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
