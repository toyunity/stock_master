"""대차잔고 수집(shortbal) 테스트 — 파서 픽스처는 실제 와이어 응답(2026-07-13 실측)."""
import asyncio
import datetime as dt
import json

from backend.flow import shortbal

# KOFIA getMetaDataList.do 실응답 축약 — 숫자는 JSON number로 내려온다(실측)
_KOFIA_JS = {"unit": "", "dsmHeader": "", "ds1": [
    {"TMPV1": "가온전선", "TMPV2": "000500", "TMPV3": 1758, "TMPV4": 42129,
     "TMPV5": 564952, "TMPV6": 143780284000},
    {"TMPV1": "SK하이닉스", "TMPV2": "000660", "TMPV3": 200821, "TMPV4": 480869,
     "TMPV5": 14140221, "TMPV6": 30825681780000},
]}

# SEIBro stksecnslbPList 실응답 축약 — <vector><data><result> 속성형, 최신순
_SEIBRO_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<vector beforeServletCall="1" beforeEJBCall="2" afterServletCall="3" afterEJBCall="4" result="2">
    <data vectorkey="0" type="Document">
        <result><STD_DT value="20260710"/><ISIN value="KR7000660001"/><MATC_QTY value="199499"/><RED_QTY value="474946"/><CPRI value="2180000"/><TR_QTY value="4827239"/><SHTSELL_TR_QTY value="0"/><REM_AMT value="11121198"/><TOT_ISSU_STKQTY value="712702365"/></result>
    </data>
    <data vectorkey="1" type="Document">
        <result><STD_DT value="20260709"/><ISIN value="KR7000660001"/><MATC_QTY value="856467"/><RED_QTY value="402577"/><CPRI value="2186000"/><TR_QTY value="6261504"/><SHTSELL_TR_QTY value="0"/><REM_AMT value="11396645"/><TOT_ISSU_STKQTY value="712702365"/></result>
    </data>
</vector>"""


def _run(coro, timeout=10.0):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(coro, timeout))
    finally:
        loop.close()


# ── 파서 ──────────────────────────────────────────────

def test_parse_kofia_extracts_target_row():
    got = shortbal.parse_kofia(_KOFIA_JS, "000660")
    assert got == {"qty": 14140221, "value": 30825681780000}


def test_parse_kofia_missing_code_returns_none():
    assert shortbal.parse_kofia(_KOFIA_JS, "005930") is None
    assert shortbal.parse_kofia({}, "000660") is None


def test_parse_seibro_ascending_with_derived_value():
    rows = shortbal.parse_seibro(_SEIBRO_XML)
    assert [r["date"] for r in rows] == ["2026-07-09", "2026-07-10"]  # 최신순→오름차순
    assert rows[1]["qty"] == 11121198  # REM_AMT = 잔고 '주수'(이름과 달리)
    assert rows[1]["value"] == 11121198 * 2180000  # 금액 컬럼 없음 → 주수×종가


# ── 증감/시그널 ───────────────────────────────────────

def test_with_changes_same_source_only():
    rows = shortbal.with_changes([
        {"date": "2026-07-10", "qty": 120, "value": 1, "src": "seibro"},
        {"date": "2026-07-08", "qty": 100, "value": 1, "src": "kofia"},
        {"date": "2026-07-09", "qty": 110, "value": 1, "src": "kofia"},
    ])
    assert [r["date"] for r in rows] == ["2026-07-08", "2026-07-09", "2026-07-10"]
    assert rows[0]["chg"] is None          # 첫 행은 비교 대상 없음
    assert rows[1]["chg"] == 10
    assert rows[2]["chg"] is None          # 이종 소스(집계 범위 다름) 간 비교 금지


def test_short_signal_four_quadrants_and_edges():
    assert shortbal.short_signal(1.5, -1000)["text"] == "건강한 상승 (숏 이탈)"
    assert shortbal.short_signal(1.5, 1000)["text"] == "상승 중 숏 축적 (경계)"
    assert shortbal.short_signal(-1.5, 1000)["text"] == "하락 베팅 강화 (경계)"
    assert shortbal.short_signal(-1.5, -1000)["text"] == "숏커버링 가능 구간"
    assert shortbal.short_signal(0.0, 1000)["tone"] == "flat"   # 보합은 중립
    assert shortbal.short_signal(1.5, 0)["tone"] == "flat"
    assert shortbal.short_signal(None, 1000) is None            # 미확보 시 판정 안 함
    assert shortbal.short_signal(1.5, None) is None


def test_expected_latest_skips_weekend():
    assert shortbal.expected_latest(dt.date(2026, 7, 13)) == dt.date(2026, 7, 10)  # 월→금
    assert shortbal.expected_latest(dt.date(2026, 7, 12)) == dt.date(2026, 7, 10)  # 일→금
    assert shortbal.expected_latest(dt.date(2026, 7, 14)) == dt.date(2026, 7, 13)  # 화→월


# ── get_history 시나리오 (원격 조회는 monkeypatch) ─────

def _kofia_fake_factory(calls):
    async def fake(cli, date, market):
        calls.append((date, market))
        qty = 14_000_000 + date.toordinal()  # 날짜마다 다른 잔고
        return {"ds1": [{"TMPV2": "000660", "TMPV5": qty, "TMPV6": qty * 2_000_000}]}
    return fake


def test_backfill_then_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(shortbal, "_last_try", {})
    calls = []
    monkeypatch.setattr(shortbal, "_SPACING_SEC", 0)
    monkeypatch.setattr(shortbal, "_kofia_day", _kofia_fake_factory(calls))
    d = _run(shortbal.get_history("000660", str(tmp_path), days=20))
    assert len(d["rows"]) == 20 and d["source"] == "kofia"
    assert d["asof"] == shortbal.expected_latest(dt.date.today()).isoformat()
    assert d["rows"][1]["chg"] == d["rows"][1]["qty"] - d["rows"][0]["qty"]
    assert (tmp_path / "shortbal_000660.json").exists()
    assert len(calls) >= 20  # 백필은 여러 날 조회

    calls.clear()
    d2 = _run(shortbal.get_history("000660", str(tmp_path), days=20))
    assert d2["rows"] == d["rows"]
    assert calls == []  # 같은 날 재호출은 캐시로만(원격 조회 없음)


def test_kofia_market_discovery_kosdaq(tmp_path, monkeypatch):
    monkeypatch.setattr(shortbal, "_last_try", {})
    calls = []

    async def kosdaq_only(cli, date, market):
        calls.append(market)
        if market != "2":
            return {"ds1": []}
        return {"ds1": [{"TMPV2": "247540", "TMPV5": 500, "TMPV6": 1000}]}
    monkeypatch.setattr(shortbal, "_SPACING_SEC", 0)
    monkeypatch.setattr(shortbal, "_kofia_day", kosdaq_only)
    d = _run(shortbal.get_history("247540", str(tmp_path), days=5))
    assert d["rows"] and d["rows"][-1]["qty"] == 500
    assert calls[0] == "1" and calls[1] == "2"  # KOSPI 먼저 → KOSDAQ 발견
    assert calls[2:] == ["2"] * len(calls[2:])  # 이후엔 발견한 시장만 조회
    cache = json.loads((tmp_path / "shortbal_247540.json").read_text())
    assert cache["market"] == "2"


def test_kofia_failure_falls_back_to_seibro(tmp_path, monkeypatch):
    monkeypatch.setattr(shortbal, "_last_try", {})
    async def kofia_down(cli, date, market):
        raise RuntimeError("HTTP 503")

    async def seibro_ok(cli, code, start, end):
        return _SEIBRO_XML
    monkeypatch.setattr(shortbal, "_SPACING_SEC", 0)
    monkeypatch.setattr(shortbal, "_kofia_day", kofia_down)
    monkeypatch.setattr(shortbal, "_seibro_range", seibro_ok)
    d = _run(shortbal.get_history("000660", str(tmp_path), days=20))
    assert d["source"] == "seibro"
    assert d["rows"][-1]["qty"] == 11121198


def test_total_failure_keeps_previous_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(shortbal, "_last_try", {})
    old = {"fetched": "2026-07-10T18:00:00", "market": "1",
           "rows": [{"date": "2026-07-09", "qty": 14420269,
                     "value": 31522708034000, "chg": None, "src": "kofia"}]}
    p = tmp_path / "shortbal_000660.json"
    p.write_text(json.dumps(old), encoding="utf-8")

    async def down(*a, **k):
        raise RuntimeError("죽음")
    monkeypatch.setattr(shortbal, "_SPACING_SEC", 0)
    monkeypatch.setattr(shortbal, "_kofia_day", down)
    monkeypatch.setattr(shortbal, "_seibro_range", down)
    d = _run(shortbal.get_history("000660", str(tmp_path)))
    assert d["rows"][0]["qty"] == 14420269  # 화면은 이전 캐시로 유지
    assert d["updated"] == "2026-07-10T18:00:00"  # 갱신 시각도 정직하게 과거


def test_retry_throttled_within_hour(tmp_path, monkeypatch):
    monkeypatch.setattr(shortbal, "_last_try", {})
    # 최신 공시가 아직 없어도 원격 재시도는 시간당 1회 — 30분 엔진 주기에 안전
    p = tmp_path / "shortbal_000660.json"
    p.write_text(json.dumps({
        "fetched": dt.datetime.now().isoformat(timespec="seconds"),
        "market": "1",
        "rows": [{"date": "2026-07-09", "qty": 1, "value": 1,
                  "chg": None, "src": "kofia"}]}), encoding="utf-8")

    called = []

    async def rec(*a, **k):
        called.append(1)
        raise RuntimeError("호출되면 안 됨")
    monkeypatch.setattr(shortbal, "_kofia_day", rec)
    monkeypatch.setattr(shortbal, "_seibro_range", rec)
    d = _run(shortbal.get_history("000660", str(tmp_path)))
    assert d["rows"][0]["qty"] == 1
    assert called == []  # 스로틀 내엔 원격 조회 자체가 없어야 함


def test_throttle_arms_even_on_total_failure(tmp_path, monkeypatch):
    # 리뷰 확정: fetched는 성공 전용이라 총실패 시 스로틀이 안 걸려
    # 엔진 매분 주기마다 원격 재시도가 됐다 — 실패 포함 _last_try로 차단
    monkeypatch.setattr(shortbal, "_last_try", {})
    calls = []

    async def down(*a, **k):
        calls.append(1)
        raise RuntimeError("outage")
    monkeypatch.setattr(shortbal, "_SPACING_SEC", 0)
    monkeypatch.setattr(shortbal, "_kofia_day", down)
    monkeypatch.setattr(shortbal, "_seibro_range", down)
    _run(shortbal.get_history("000660", str(tmp_path)))
    n1 = len(calls)
    assert n1 >= 2  # KOFIA + SEIBro 각 1회는 시도
    _run(shortbal.get_history("000660", str(tmp_path)))
    assert len(calls) == n1  # 1시간 내 재호출은 원격 시도 없음


def test_small_days_does_not_shrink_shared_cache(tmp_path, monkeypatch):
    # 리뷰 확정: CLI --days 3이 서버(20일)와 공유하는 캐시를 13행으로 줄이고
    # 되돌릴 방법이 없었다 — 보존 하한 _CACHE_KEEP으로 방지
    monkeypatch.setattr(shortbal, "_SPACING_SEC", 0)
    calls = []
    monkeypatch.setattr(shortbal, "_last_try", {})
    monkeypatch.setattr(shortbal, "_kofia_day", _kofia_fake_factory(calls))
    _run(shortbal.get_history("000660", str(tmp_path), days=20))
    n_before = len(json.loads(
        (tmp_path / "shortbal_000660.json").read_text())["rows"])
    # 스로틀·완비 캐시 우회해 재수집 경로 강제(최신 행 하나 지움 + 시도기록 초기화)
    cache = json.loads((tmp_path / "shortbal_000660.json").read_text())
    cache["rows"] = cache["rows"][:-1]
    cache["fetched"] = "2020-01-01T00:00:00"
    (tmp_path / "shortbal_000660.json").write_text(json.dumps(cache))
    monkeypatch.setattr(shortbal, "_last_try", {})
    d = _run(shortbal.get_history("000660", str(tmp_path), days=3))
    assert len(d["rows"]) == 3  # 반환은 요청한 만큼
    n_after = len(json.loads(
        (tmp_path / "shortbal_000660.json").read_text())["rows"])
    assert n_after >= min(n_before, shortbal._CACHE_KEEP)  # 캐시는 안 줄어듦


def test_partial_backfill_preserved_on_midway_failure(tmp_path, monkeypatch):
    # 리뷰 확정: 백필 중간 실패가 기수집 KOFIA 행까지 버리고 전체를 SEIBro로
    # 대체했다 — 부분 보존 후 다음 주기에 이어가도록 수정
    monkeypatch.setattr(shortbal, "_last_try", {})
    monkeypatch.setattr(shortbal, "_SPACING_SEC", 0)
    calls = []

    async def flaky(cli, date, market):
        calls.append(date)
        if len(calls) > 5:
            raise RuntimeError("HTTP 503")
        qty = 14_000_000 + date.toordinal()
        return {"ds1": [{"TMPV2": "000660", "TMPV5": qty, "TMPV6": qty * 2}]}

    async def seibro_boom(*a, **k):
        raise AssertionError("부분 수집이 있으면 SEIBro 폴백 금지")
    monkeypatch.setattr(shortbal, "_kofia_day", flaky)
    monkeypatch.setattr(shortbal, "_seibro_range", seibro_boom)
    d = _run(shortbal.get_history("000660", str(tmp_path), days=20))
    assert len(d["rows"]) == 5  # 실패 전까지 수집분 보존
    assert all(r["src"] == "kofia" for r in d["rows"])
