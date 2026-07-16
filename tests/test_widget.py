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
ITEM_KEYS = {"code", "name", "price", "change"}


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
    d = asyncio.run(widget_data(["005930", "000660"]))
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
    assert asyncio.run(widget_data(["005930"])) is None


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
    d = asyncio.run(widget_data(["035720"]))
    assert d["items"][0]["name"] == "카카오"
