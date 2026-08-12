"""GET /api/worldidx — 라우트 계약(전부 픽스처 오프라인).

라우트가 확인해야 할 것은 두 가지다.
1) 프런트 계약: Item은 정확히 8개 키, `unit`·`basis`가 **항목마다** 실린다. 단위를
   프런트가 추측하게 두면 설계 조사에서 걸러낸 프록시 사고(금 402달러)가 재발한다.
2) 실패해도 500이 아니다: 원천이 전부 죽어도 groups=[]인 200을 준다 — 화면은 섹션을
   통째로 감추면 되고, 대시보드 폴링이 에러 토스트로 시끄러워지지 않는다.

캐시(`worldidx._cache`)는 모듈 전역이고 재무부 TTL이 1시간이라, 리셋을 **앞뒤로 모두**
한다. 앞만 씻으면 test_worldidx.py가 남긴 캐시를 물려받아 실행 순서에 결과가 갈리고,
뒤를 안 씻으면 이 파일이 다음 파일(대시보드 렌더 테스트)을 오염시킨다.

autouse 스텁은 test_worldidx.py와 같은 관례로 세 원천 모두를 '반드시 터지는' 함수로
먼저 덮는다 — 주입을 빼먹은 테스트는 라이브 호출이 아니라 RuntimeError로 죽는다.
"""
import datetime as dt
import json
import pathlib

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.flow import candles
from backend.flow import worldidx as wi
from backend.flow.kst import KST

FIX = pathlib.Path(__file__).parent / "fixtures"

# 픽스처를 딴 시각(2026-08-11 21:40 KST = 08:40 ET) — 조회 월과 지수 기준일 폴백이
# '지금'에 매여 있어, 고정하지 않으면 러너 날짜에 따라 결과가 흔들린다.
FIXTURE_NOW = dt.datetime(2026, 8, 11, 21, 40, tzinfo=KST)

ITEM_KEYS = {"key", "label", "value", "unit", "rate", "rate_unit", "sign",
             "basis", "src", "basis_kind"}
# rate_unit: 국채는 bp, 나머지는 % / basis_kind: live냐 date냐 — 둘 다 프런트가 추측
# 하지 않게 서버가 실어 내린다.
UNITS = {"ust2y": "%", "ust10y": "%", "ust30y": "%",
         "wti": "$/bbl", "gold": "$/oz",
         "spx": "idx", "comp": "idx", "vix": "idx"}

_FDR_ROWS = {"CL=F": [("2026-08-07", 81.50), ("2026-08-10", 82.13)],
             "GC=F": [("2026-08-06", 4290.00), ("2026-08-10", 4361.80)]}


class _FakeKis:
    """FHKST03030100만 답하는 가짜 KIS 클라이언트(kis_worldidx.json 실응답)."""

    def __init__(self):
        self.js = json.loads((FIX / "kis_worldidx.json").read_text(encoding="utf-8"))

    async def _get(self, path, tr_id, params):
        return self.js[params["FID_INPUT_ISCD"]]


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """캐시 리셋(앞뒤) + 세 원천 기본 스텁(터짐) + KIS 호출 간격 0 + 시계 고정."""
    def clear():
        for slot in wi._cache.values():
            slot["ts"], slot["data"], slot["fail_ts"] = 0.0, None, 0.0
        wi._lock = None      # 락은 만들어진 루프에 매인다(TestClient는 요청마다 새 루프)

    clear()

    def _boom_treasury(month):
        raise RuntimeError("재무부 스텁 미지정")

    def _boom_fdr(symbol, start):
        raise RuntimeError("FDR 스텁 미지정")

    def _boom_client():
        raise RuntimeError("KIS 스텁 미지정")

    def _boom_cnbc(symbol):
        raise RuntimeError("CNBC 스텁 미지정")

    # CNBC도 반드시 막는다. 이 줄이 없으면 _treasury_group이 장중에 **실제 CNBC로
    # 나간다** — 남의 사설 API이고, '전부 실패' 테스트가 라이브 성공으로 통과해버린다.
    monkeypatch.setattr(wi, "_fetch_cnbc", _boom_cnbc)
    monkeypatch.setattr(wi, "_fetch_treasury_xml", _boom_treasury)
    monkeypatch.setattr(wi, "_fetch_fdr", _boom_fdr)
    monkeypatch.setattr(candles, "_get_client", _boom_client)
    monkeypatch.setattr(wi, "_GAP", 0.0)
    monkeypatch.setattr(wi.kst, "now", lambda: FIXTURE_NOW)
    monkeypatch.setattr(wi.kst, "today", lambda: FIXTURE_NOW.date())
    yield
    clear()


def _all_sources_ok(monkeypatch):
    """세 원천을 실응답 픽스처로 채운다."""
    monkeypatch.setattr(wi, "_fetch_treasury_xml",
                        lambda month: (FIX / "treasury_yield_202608.xml")
                        .read_text(encoding="utf-8"))
    monkeypatch.setattr(wi, "_fetch_fdr", lambda symbol, start: pd.DataFrame(
        {"Close": [c for _, c in _FDR_ROWS[symbol]]},
        index=pd.to_datetime([d for d, _ in _FDR_ROWS[symbol]])))
    monkeypatch.setattr(candles, "_get_client", _FakeKis)


def test_worldidx_route_returns_full_item_shape(monkeypatch):
    """200 + {asof, groups} — 그룹 순서 고정, Item은 정확히 8개 키."""
    _all_sources_ok(monkeypatch)
    with TestClient(app) as c:
        r = c.get("/api/worldidx")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    d = r.json()
    assert set(d) == {"asof", "groups"}
    assert d["asof"] == "2026-08-11T21:40:00+09:00"       # kst.now(), 초 단위 ISO
    assert [g["label"] for g in d["groups"]] == ["미국 금리", "원자재", "해외지수"]

    items = [i for g in d["groups"] for i in g["items"]]
    assert [i["key"] for i in items] == ["ust2y", "ust10y", "ust30y",
                                         "wti", "gold", "spx", "comp", "vix"]
    for it in items:
        # 집합 동등 — '추가 키 없음'이 프런트 계약이라 부분집합 검사로는 못 잡는다.
        assert set(it) == ITEM_KEYS, it["key"]
        assert isinstance(it["value"], float) and it["value"] > 0
        assert it["unit"] == UNITS[it["key"]]
        assert it["rate"] is None or isinstance(it["rate"], float)
        assert it["sign"] in ("up", "down", "flat")
        assert len(it["basis"]) == 5 and it["basis"][2] == "-"   # 'MM-DD'
        assert it["src"] in ("treasury", "fdr", "kis")

    by_key = {i["key"]: i for i in items}
    assert by_key["ust10y"]["value"] == 4.72 and by_key["ust10y"]["src"] == "treasury"
    assert by_key["gold"]["value"] == 4361.80 and by_key["gold"]["src"] == "fdr"
    assert by_key["spx"]["value"] == 7753.11 and by_key["spx"]["src"] == "kis"
    # 지수 기준일은 '직전 미국 정규장'이다. 21:40 KST = 08:40 ET로 아직 개장(09:30 ET)
    # 전이라 값은 08-10(월) 세션 것이다 — 이 줄이 없으면 라우트 계약은 KST 오늘로
    # 되돌아가도(또는 output2 상한이 빠져도) 그대로 통과한다(len(basis)==5만 보므로).
    assert by_key["spx"]["basis"] == "08-10" and by_key["vix"]["basis"] == "08-10"


def test_worldidx_route_is_200_with_empty_groups_when_every_source_dies(monkeypatch):
    """전부 실패해도 500이 아니다 — groups=[]로 200(화면이 섹션을 감춘다).

    스텁 호출 횟수까지 본다. 쿨다운(_cooling)에 걸려 원천을 **아예 안 부른 채**
    빈 groups를 준 것도 이 단언 없이는 통과해버려, 실패 격리를 검증한 게 아니게 된다."""
    calls = {"treasury": 0, "fdr": 0, "kis": 0}

    def boom_treasury(month):
        calls["treasury"] += 1
        raise RuntimeError("재무부 500 스텁")

    def boom_fdr(symbol, start):
        calls["fdr"] += 1
        raise RuntimeError("FDR 스텁")

    def boom_client():
        calls["kis"] += 1
        raise RuntimeError("KIS 키 없음 스텁")

    monkeypatch.setattr(wi, "_fetch_treasury_xml", boom_treasury)
    monkeypatch.setattr(wi, "_fetch_fdr", boom_fdr)
    monkeypatch.setattr(candles, "_get_client", boom_client)
    with TestClient(app) as c:
        r = c.get("/api/worldidx")
    assert r.status_code == 200
    d = r.json()
    assert d["groups"] == [] and d["asof"]
    assert calls == {"treasury": 2, "fdr": 2, "kis": 1}   # 이번 달+전월, 두 심볼, 클라이언트 1


def test_worldidx_route_keeps_other_groups_when_one_source_dies(monkeypatch):
    """재무부만 죽인다(autouse 스텁 그대로) — 나머지 두 그룹은 그대로 200으로 나간다."""
    _all_sources_ok(monkeypatch)
    monkeypatch.setattr(wi, "_fetch_treasury_xml",
                        lambda month: (_ for _ in ()).throw(RuntimeError("재무부 다운")))
    with TestClient(app) as c:
        r = c.get("/api/worldidx")
    assert r.status_code == 200
    assert [g["label"] for g in r.json()["groups"]] == ["원자재", "해외지수"]


def test_route_calls_worldidx_through_the_module(monkeypatch):
    """라우트는 `worldidx.get_worldidx()`를 **모듈 경유로** 부른다.

    `from backend.flow.worldidx import get_worldidx`로 심볼을 박아두면 이 스텁이
    우회된다 — 이 프로젝트의 모킹 관행(app.py 상단 주석)이 그 지점에서 깨진다."""
    async def fake():
        return {"asof": "2026-08-11T21:40:00+09:00", "groups": [{"label": "스텁", "items": []}]}

    monkeypatch.setattr(wi, "get_worldidx", fake)
    with TestClient(app) as c:
        r = c.get("/api/worldidx")
    assert r.status_code == 200
    assert r.json()["groups"] == [{"label": "스텁", "items": []}]
