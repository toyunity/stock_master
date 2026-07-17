"""아이폰 위젯 — 토큰 설정·데이터 조립·응답 계약(화이트리스트).

설계: docs/superpowers/specs/2026-07-16-iphone-widget-design.md
⚠ Settings는 .env를 자동 로드하므로 '미설정' 시나리오는 widget_token=None을 명시한다.
"""
import pytest

from backend.config import Settings

TOKEN = "w" * 32   # 유효 토큰(20자 이상)


def _settings(tmp_path, **over):
    base = dict(cache_dir=str(tmp_path), flow_mode="demo",
                widget_token=TOKEN, kis_app_key=None, kis_app_secret=None,
                dart_api_key=None)
    base.update(over)
    return Settings(**base)


def test_short_widget_token_refuses_boot(tmp_path):
    """약한 토큰이 유일 방어선이 되는 것을 차단 — 20자 미만이면 기동 거부(fail-closed)."""
    from backend.api.app import create_app
    with pytest.raises(RuntimeError):
        create_app(_settings(tmp_path, widget_token="short"))


def test_valid_or_absent_widget_token_boots(tmp_path):
    from backend.api.app import create_app
    create_app(_settings(tmp_path))                       # 32자 → OK
    create_app(_settings(tmp_path, widget_token=None))    # 미설정 → OK(위젯만 꺼짐)


def test_create_app_runs_migration_backward_compat(tmp_path, monkeypatch):
    """create_app이 migrate_globals를 실행해 env 토큰이 마스터 계정으로 매핑됨 — 마스터 아이폰
    위젯 하위호환(미배선 시 기존 env 토큰이 401로 파손, 2026-07-17 실사고)."""
    import json
    from backend.config import settings as _gs
    from backend.api.app import create_app
    from backend.flow import userstore
    monkeypatch.setattr(_gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(_gs, "default_account", "master@gmail.com")
    monkeypatch.setattr(_gs, "widget_token", TOKEN)   # migrate_globals는 모듈 settings 토큰을 읽음
    userstore._tok_cache["mtime"] = None              # 이전 테스트의 토큰맵 캐시 격리
    with open(tmp_path / "watchlist.json", "w", encoding="utf-8") as f:
        json.dump({"codes": ["005930"]}, f)
    create_app(_settings(tmp_path, default_account="master@gmail.com"))  # 여기서 마이그레이션
    assert userstore.email_for_token(TOKEN) == "master@gmail.com"        # env 토큰 → 마스터
    assert [i["code"] for i in userstore.get_watchlist("master@gmail.com")] == ["005930"]


# ── 거래일/장 상태 판정 ────────────────────────────────────────────
import asyncio
import datetime as dt

from backend.flow.kst import KST


def _kst(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=KST)


def test_parse_latest_trade_date():
    from backend.flow.kis import parse_latest_trade_date
    js = {"rt_cd": "0", "output": [{"stck_bsop_date": "20260716"},
                                   {"stck_bsop_date": "20260715"}]}
    assert parse_latest_trade_date(js) == "2026-07-16"
    assert parse_latest_trade_date({"rt_cd": "1"}) is None
    assert parse_latest_trade_date({"rt_cd": "0", "output": []}) is None
    assert parse_latest_trade_date({"rt_cd": "0", "output": [{"stck_bsop_date": "bad"}]}) is None


def test_wallclock_open_hours_and_weekend():
    from backend.flow import market_status as ms
    assert ms.wallclock_open(_kst(2026, 7, 16, 10, 30)) is True    # 목 장중
    assert ms.wallclock_open(_kst(2026, 7, 16, 8, 59)) is False    # 장전
    assert ms.wallclock_open(_kst(2026, 7, 16, 15, 31)) is False   # 장후
    assert ms.wallclock_open(_kst(2026, 7, 18, 10, 0)) is False    # 토


def test_refresh_after_sec_open_vs_closed():
    from backend.flow import market_status as ms
    assert ms.refresh_after_sec(True, _kst(2026, 7, 16, 10, 0)) == 900
    # 목 16:00 → 금 09:00 = 17시간 = 61200초 → 6h 캡
    assert ms.refresh_after_sec(False, _kst(2026, 7, 16, 16, 0)) == 21600
    # 금 08:00 → 당일 09:00 = 3600초(캡 미달)
    assert ms.refresh_after_sec(False, _kst(2026, 7, 17, 8, 0)) == 3600


class _FakeClient:
    def __init__(self, td):
        self._td = td

    async def latest_trade_date(self, code="005930"):
        return self._td


def test_get_status_holiday_demotes_open(monkeypatch):
    """평일 공휴일: 벽시계는 장중이지만 KIS 최신 거래일 ≠ 오늘 → open:false 강등."""
    from backend.flow import market_status as ms
    monkeypatch.setattr(ms, "_cache", {"ts": 0.0, "trade_date": None})
    now = _kst(2026, 7, 16, 10, 0)                       # 목요일 장중(공휴일 가정)
    st = asyncio.run(
        ms.get_status(_FakeClient("2026-07-15"), now=now))
    assert st["open"] is False and st["trade_date"] == "2026-07-15"


def test_get_status_trading_day_open(monkeypatch):
    from backend.flow import market_status as ms
    monkeypatch.setattr(ms, "_cache", {"ts": 0.0, "trade_date": None})
    now = _kst(2026, 7, 16, 10, 0)
    st = asyncio.run(
        ms.get_status(_FakeClient("2026-07-16"), now=now))
    assert st["open"] is True and st["refresh_after_sec"] == 900


def test_get_status_refetches_on_open_boundary(monkeypatch):
    """마감→장중 경계 전환 시 TTL 안 지나도 재조회 — 개장 직후 '마감' 오표시 방지(리뷰 2026-07-16)."""
    from backend.flow import market_status as ms
    monkeypatch.setattr(ms, "_cache", {"ts": 0.0, "trade_date": None, "wall": None})
    seq = iter(["2026-07-15", "2026-07-16"])   # 장전 조회는 전 거래일, 개장 후엔 당일

    class _Seq:
        async def latest_trade_date(self, code="005930"):
            return next(seq)

    c = _Seq()
    s1 = asyncio.run(ms.get_status(c, now=_kst(2026, 7, 16, 8, 55)))   # 장전(wall False)
    assert s1["open"] is False
    s2 = asyncio.run(ms.get_status(c, now=_kst(2026, 7, 16, 9, 0)))    # 개장 전환 → 재조회
    assert s2["open"] is True and s2["trade_date"] == "2026-07-16"


def test_get_status_without_client_falls_back_to_wallclock(monkeypatch):
    """TR 불가(키 없음) 폴백 — 주말엔 직전 금요일을 거래일로 추정."""
    from backend.flow import market_status as ms
    monkeypatch.setattr(ms, "_cache", {"ts": 0.0, "trade_date": None})
    st = asyncio.run(
        ms.get_status(None, now=_kst(2026, 7, 18, 10, 0)))          # 토요일
    assert st["open"] is False and st["trade_date"] == "2026-07-17"  # 금요일


# ── /api/widget 데이터 조립 · 응답 계약 ───────────────────────────
import json as _json
import os

CONTRACT_KEYS = {"open", "trade_date", "fetched_at", "refresh_after_sec", "items"}
# 계정 items 계약(§4): KR 항목은 아래 정확히, US는 여기에 us_open 추가.
ITEM_KEYS = {"code", "name", "market", "currency", "price", "change",
             "shares", "avg", "pnl", "pnl_pct"}


def _seed_universe(cache_dir, rows):
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "universe_v2.json"), "w", encoding="utf-8") as f:
        _json.dump(rows, f, ensure_ascii=False)


def test_widget_data_contract_whitelist(tmp_path, monkeypatch):
    """응답 필드는 화이트리스트 그대로 — 감시선·조언 등 유입 시 여기가 먼저 깨진다."""
    from backend.config import settings
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)    # KIS 없음 → universe 폴백 경로
    _seed_universe(str(tmp_path), [
        {"code": "005930", "name": "삼성전자", "close": 71200.0, "change": 1.25}])
    d = asyncio.run(widget_data("m@x.com", [{"code": "005930", "market": "KR"},
                                            {"code": "000660", "market": "KR"}]))
    assert set(d.keys()) == CONTRACT_KEYS
    assert all(set(i.keys()) == ITEM_KEYS for i in d["items"])
    assert d["items"][0]["price"] == 71200.0
    assert d["items"][1]["price"] is None                 # 캐시에 없는 종목 = null(행 유지)


def test_widget_data_none_when_no_source(tmp_path, monkeypatch):
    """KIS 없음 + 캐시 없음 → None(라우트 503) — 조용한 빈 위젯 금지."""
    from backend.config import settings
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    assert asyncio.run(widget_data("m@x.com", [{"code": "005930", "market": "KR"}])) is None


def test_widget_api_route_503_without_source(tmp_path, monkeypatch):
    """auth 비활성(로컬) 라우트 스모크 — 소스 없음이면 503 + 사용자 메시지.

    ⚠ widget_data는 전역 settings를 읽는다(create_app 주입과 별개) — 마스터
    실기기 .env의 실제 KIS 키로 라이브 호출이 나가지 않게 전역을 격리한다."""
    from fastapi.testclient import TestClient
    from backend.config import settings
    from backend.api.app import create_app
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    c = TestClient(create_app(_settings(tmp_path)))
    r = c.get("/api/widget")
    assert r.status_code == 503 and "error" in r.json()


# ── 이름 해석: universe 우선, 하드코딩 폴백 ────────────────────────
def test_resolve_name_chain():
    from backend.news.names import resolve_name
    uni_names = {"035720": "카카오"}
    assert resolve_name("035720", uni_names) == "카카오"       # universe 히트
    assert resolve_name("005930", uni_names) == "삼성전자"     # 미스 → 하드코딩
    assert resolve_name("999999", uni_names) == "999999"       # 둘 다 미스 → 코드


def test_news_aliases_manual_first_then_universe():
    from backend.cli import _news_aliases
    a = _news_aliases(["005930", "035720"], {"035720": "카카오"})
    assert a["005930"] == ["삼성전자"]        # 수동 별칭 우선(STOCK_NAMES)
    assert a["035720"] == ["카카오"]          # 신규 종목 → universe 이름 1개
    assert _news_aliases(["035720"], None)["035720"] == []   # 이름 없으면 빈 별칭


def test_widget_data_resolves_new_stock_name(tmp_path, monkeypatch):
    """신규 종목이 '035720' 숫자가 아니라 universe 이름으로 표시(설계 major #6)."""
    from backend.config import settings
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    _seed_universe(str(tmp_path), [
        {"code": "035720", "name": "카카오", "close": 43000.0, "change": -0.5}])
    d = asyncio.run(widget_data("m@x.com", [{"code": "035720", "market": "KR"}]))
    assert d["items"][0]["name"] == "카카오"


def test_widget_includes_pnl_and_whitelist(tmp_path, monkeypatch):
    """계정 보유 종목의 pnl이 응답에 포함되고 화이트리스트(감시선 등 없음) 유지."""
    import asyncio
    from backend.config import settings
    from backend.flow import userstore
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    monkeypatch.setattr(settings, "default_account", "m@x.com")
    _seed_universe(str(tmp_path), [
        {"code": "005930", "name": "삼성전자", "close": 253500.0, "change": -9.3}])
    userstore.set_watchlist("m@x.com", [{"code": "005930", "market": "KR", "shares": 10, "avg": 230000}])
    d = asyncio.run(widget_data("m@x.com", userstore.get_watchlist("m@x.com")))
    it = d["items"][0]
    assert it["pnl"] == 235000 and it["market"] == "KR" and it["currency"] == "KRW"
    assert set(it.keys()) <= {"code", "name", "market", "currency", "price", "change",
                              "shares", "avg", "pnl", "pnl_pct", "us_open"}


def test_widget_us_row_shape(tmp_path, monkeypatch):
    """US 행 shape(§4) — currency USD·us_open·price null(KIS client 없음 → US 시세 조회 불가).
    KR가 universe 폴백으로 소스를 제공해 전멸(503) 단락을 피하고 US 분기를 실제로 실행한다.
    (client 있을 때의 US 실시세는 test_widget_us_price_wired에서 검증.)"""
    import asyncio
    from backend.config import settings
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    _seed_universe(str(tmp_path), [
        {"code": "005930", "name": "삼성전자", "close": 71200.0, "change": 1.25}])
    d = asyncio.run(widget_data("m@x.com", [{"code": "005930", "market": "KR"},
                                            {"code": "NVDA", "market": "US", "shares": 5, "avg": 170.0}]))
    us = [i for i in d["items"] if i["market"] == "US"][0]
    assert us["currency"] == "USD" and us["price"] is None      # 시세는 Task 13까지 null
    assert us["pnl"] is None and us["pnl_pct"] is None          # price 없으면 수익 없음
    assert isinstance(us.get("us_open"), bool)                  # US 신선도 플래그(ET)
    assert us["name"] == "엔비디아"                             # semi.US_NAMES 우선
    assert set(us.keys()) == {"code", "name", "market", "currency", "price", "change",
                              "shares", "avg", "pnl", "pnl_pct", "us_open"}


# ── Task 13: US 시세 배선(usquote.price_us) + 전멸 판정 KR+US 합산 ──
class _FakeKis:
    """widget_data용 최소 KIS client 더블 — KR price()만(US는 usquote.price_us 모킹).
    비ASCII/실호출 방지: 넘긴 dict에 없는 코드는 None(부분 실패)."""

    def __init__(self, kr=None):
        self._kr = kr or {}

    async def price(self, code):
        return self._kr.get(code)


def _patch_us(monkeypatch, client, price_us):
    """widget_data의 client 빌더와 usquote.price_us를 모킹(실 KIS 호출 0)."""
    from backend.flow import candles, usquote
    monkeypatch.setattr(candles, "_get_client", lambda: client)
    monkeypatch.setattr(usquote, "price_us", price_us)


def test_widget_us_price_wired(tmp_path, monkeypatch):
    """US 항목이 usquote.price_us로 실제 시세를 받는다(client 있을 때) — USD·수익 계산."""
    from backend.config import settings
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", "dummy")

    async def _pu(client, sym):
        return {"price": 189.70, "change": -0.85, "currency": "USD", "exch": "NAS"}
    _patch_us(monkeypatch, _FakeKis({"005930": {"price": 71200, "rate": 1.25}}), _pu)
    d = asyncio.run(widget_data("m@x.com", [{"code": "005930", "market": "KR"},
                                            {"code": "NVDA", "market": "US",
                                             "shares": 5, "avg": 170.0}]))
    us = [i for i in d["items"] if i["market"] == "US"][0]
    assert us["price"] == 189.70 and us["currency"] == "USD" and us["change"] == -0.85
    assert abs(us["pnl"] - (189.70 - 170.0) * 5) < 1e-6      # US 소수 수익
    assert isinstance(us["us_open"], bool)


def test_widget_us_only_account_not_503(tmp_path, monkeypatch):
    """US 전용 계정 — KR 소스가 없어도 US 시세가 있으면 None(503) 아님(회귀 방지).
    전멸 판정이 KR 코드만 보면 US-only 계정이 항상 503으로 죽는다(advisor #1)."""
    from backend.config import settings
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", "dummy")

    async def _pu(client, sym):
        return {"price": 189.70, "change": -0.85, "currency": "USD", "exch": "NAS"}
    _patch_us(monkeypatch, _FakeKis(), _pu)
    d = asyncio.run(widget_data("m@x.com", [{"code": "NVDA", "market": "US"}]))
    assert d is not None and d["items"][0]["price"] == 189.70


def test_widget_kr_fail_us_succeed(tmp_path, monkeypatch):
    """KR 전멸 + US 성공 → 데이터 반환(전멸 판정은 KR+US 합산). KR은 부분실패 null 유지."""
    from backend.config import settings
    from backend.api.widget import widget_data
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", "dummy")

    async def _pu(client, sym):
        return {"price": 100.0, "change": 1.0, "currency": "USD", "exch": "NYS"}
    _patch_us(monkeypatch, _FakeKis(), _pu)     # KR price() → None(전멸)
    d = asyncio.run(widget_data("m@x.com", [{"code": "005930", "market": "KR"},
                                            {"code": "NVDA", "market": "US"}]))
    assert d is not None
    kr = [i for i in d["items"] if i["market"] == "KR"][0]
    us = [i for i in d["items"] if i["market"] == "US"][0]
    assert kr["price"] is None and us["price"] == 100.0


# ── /api/watchlist 편집 API + 소비자 공유 ─────────────────────────
def _client_local(tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    return TestClient(create_app(_settings(tmp_path)))


def test_watchlist_api_roundtrip_and_validation(tmp_path, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "default_account", "master@gmail.com")
    c = _client_local(tmp_path)
    r = c.get("/api/watchlist")
    assert r.status_code == 200 and len(r.json()["items"]) >= 5      # 마스터 시드
    r = c.post("/api/watchlist", json={"items": [{"code": "035720", "market": "KR"},
                                                 {"code": "005930", "market": "KR"}]})
    assert r.status_code == 200
    assert [i["code"] for i in c.get("/api/watchlist").json()["items"]] == ["035720", "005930"]
    assert c.post("/api/watchlist", json={"items": []}).status_code == 400        # 최소 1
    assert c.post("/api/watchlist", json={"items": [{"code": "12", "market": "KR"}]}).status_code == 400
    assert c.post("/api/watchlist", json={}).status_code == 400                    # items 없음
    assert c.post("/api/watchlist", json={"codes": ["005930"]}).status_code == 400  # 구 계약 거부


def test_watchlist_api_items_contract(tmp_path, monkeypatch):
    """items 계약(계정별) — 보유(shares/avg) 왕복 + 구 codes 계약 거부."""
    from backend.config import settings
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "default_account", "master@gmail.com")
    c = TestClient(create_app(_settings(tmp_path, default_account="master@gmail.com")))
    r = c.post("/api/watchlist",
               json={"items": [{"code": "005930", "market": "KR", "shares": 10, "avg": 230000}]})
    assert r.status_code == 200
    got = c.get("/api/watchlist").json()["items"]
    assert got[0]["code"] == "005930" and got[0]["shares"] == 10 and got[0]["avg"] == 230000
    assert c.post("/api/watchlist", json={"codes": ["005930"]}).status_code == 400  # 구 계약 거부


def test_widget_follows_edited_watchlist(tmp_path, monkeypatch):
    """앱에서 편집 → 위젯이 따라감(확정 결정 3)."""
    from backend.config import settings
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "kis_app_key", None)
    monkeypatch.setattr(settings, "default_account", "master@gmail.com")
    _seed_universe(str(tmp_path), [
        {"code": "035720", "name": "카카오", "close": 43000.0, "change": -0.5}])
    c = _client_local(tmp_path)
    assert c.post("/api/watchlist",
                  json={"items": [{"code": "035720", "market": "KR"}]}).status_code == 200
    d = c.get("/api/widget").json()
    assert [i["code"] for i in d["items"]] == ["035720"]


# ── Task 13: /api/watchlist 신규 US 티커 존재확인(price_us) ─────────
def _us_client(tmp_path, monkeypatch, price_us):
    """kis_app_key 주입 + client/price_us 모킹된 로컬 앱(실 KIS 호출 0)."""
    from backend.config import settings
    from backend.flow import candles, usquote
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "default_account", "master@gmail.com")
    monkeypatch.setattr(settings, "kis_app_key", "dummy")
    monkeypatch.setattr(candles, "_get_client", lambda: object())
    monkeypatch.setattr(usquote, "price_us", price_us)
    return TestClient(create_app(_settings(tmp_path, default_account="master@gmail.com")))


def test_watchlist_post_rejects_unknown_us_ticker(tmp_path, monkeypatch):
    """신규 US 티커는 price_us 존재확인 — 없으면 400(NAS/NYS/AMS·티커 포함)."""
    async def _none(client, sym):
        return None
    c = _us_client(tmp_path, monkeypatch, _none)
    r = c.post("/api/watchlist", json={"items": [{"code": "005930", "market": "KR"},
                                                 {"code": "ZZZZ", "market": "US"}]})
    assert r.status_code == 400 and "ZZZZ" in r.json()["error"]
    # 거부됐으니 저장 안 됨(마스터 시드 그대로)
    assert "ZZZZ" not in [i["code"] for i in c.get("/api/watchlist").json()["items"]]


def test_watchlist_post_accepts_valid_us_ticker(tmp_path, monkeypatch):
    """price_us가 유효 응답이면 신규 US 티커 저장 200."""
    async def _ok(client, sym):
        return {"price": 189.70, "change": -0.85, "currency": "USD", "exch": "NAS"}
    c = _us_client(tmp_path, monkeypatch, _ok)
    r = c.post("/api/watchlist", json={"items": [{"code": "005930", "market": "KR"},
                                                 {"code": "NVDA", "market": "US"}]})
    assert r.status_code == 200
    assert "NVDA" in [i["code"] for i in r.json()["items"]]


def test_watchlist_post_reorder_skips_us_verification(tmp_path, monkeypatch):
    """기존 US 티커는 재검증 안 함 — price_us가 이후 실패해도 재정렬/삭제 저장은 통과.
    (매 저장마다 KIS 재호출·outage 시 재정렬 불가를 방지.)"""
    from backend.flow import usquote

    async def _ok(client, sym):
        return {"price": 1.0, "change": 0.0, "currency": "USD", "exch": "NAS"}
    c = _us_client(tmp_path, monkeypatch, _ok)
    assert c.post("/api/watchlist",
                  json={"items": [{"code": "NVDA", "market": "US"},
                                  {"code": "005930", "market": "KR"}]}).status_code == 200

    async def _fail(client, sym):   # 이제 price_us 전멸
        return None
    monkeypatch.setattr(usquote, "price_us", _fail)
    r = c.post("/api/watchlist", json={"items": [{"code": "005930", "market": "KR"},
                                                 {"code": "NVDA", "market": "US"}]})
    assert r.status_code == 200      # 기존 NVDA는 재검증 없이 통과


def test_watchlist_post_us_skipped_without_kis(tmp_path, monkeypatch):
    """KIS 미설정(로컬/데모)이면 US 존재확인 생략 — 담기 허용(프로덕션 KIS에서만 강제)."""
    from backend.config import settings
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "default_account", "master@gmail.com")
    monkeypatch.setattr(settings, "kis_app_key", None)
    c = TestClient(create_app(_settings(tmp_path, default_account="master@gmail.com")))
    r = c.post("/api/watchlist", json={"items": [{"code": "005930", "market": "KR"},
                                                 {"code": "NVDA", "market": "US"}]})
    assert r.status_code == 200 and "NVDA" in [i["code"] for i in r.json()["items"]]
