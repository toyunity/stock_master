"""글로벌 지표(미국채·원자재·해외지수) — 전부 픽스처 오프라인.

원천 셋이 모두 네트워크라, 어떤 테스트도 실수로 밖에 나가지 못하게 autouse 픽스처가
세 원천 모두에 '반드시 터지는' 스텁을 먼저 깔아둔다(test_marketdata.py의 _nq_fail과
같은 관례 — 스텁 주입을 빼먹으면 라이브 호출이 아니라 RuntimeError가 난다).

픽스처: treasury_yield_202608.xml / kis_worldidx.json (둘 다 2026-08-11 실응답).
"""
import asyncio
import datetime as dt
import json
import pathlib
import time

import pandas as pd
import pytest

from backend.flow import candles
from backend.flow import worldidx as wi
from backend.flow.kst import KST

FIX = pathlib.Path(__file__).parent / "fixtures"

# 픽스처를 딴 시각(2026-08-11 21:40 KST = 08:40 ET) — 지수 기준일 폴백의 기준이 된다.
FIXTURE_NOW = dt.datetime(2026, 8, 11, 21, 40, tzinfo=KST)

# 재무부가 월초에 실제로 내려주는 모양 — 200 OK인데 entry가 하나도 없다(폴백 트리거).
_EMPTY_FEED = (
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
    '<feed xml:base="https://home.treasury.gov/x" '
    'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
    'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" '
    'xmlns="http://www.w3.org/2005/Atom">\n'
    '<title type="text">DailyTreasuryYieldCurveRateData</title>\n'
    '<updated>2026-09-01T00:00:00Z</updated>\n'
    '</feed>')

_ONE_ENTRY_FEED = _EMPTY_FEED.replace("</feed>", """<entry>
<content type="application/xml"><m:properties>
<d:NEW_DATE m:type="Edm.DateTime">2026-09-01T00:00:00</d:NEW_DATE>
<d:BC_2YEAR m:type="Edm.Double">4.30</d:BC_2YEAR>
<d:BC_10YEAR m:type="Edm.Double">4.80</d:BC_10YEAR>
<d:BC_30YEAR m:type="Edm.Double">5.30</d:BC_30YEAR>
</m:properties></content>
</entry>
</feed>""")


def _xml() -> str:
    return (FIX / "treasury_yield_202608.xml").read_text(encoding="utf-8")


def _kis_js() -> dict:
    return json.loads((FIX / "kis_worldidx.json").read_text(encoding="utf-8"))


def _df(rows) -> pd.DataFrame:
    """FDR 일봉 모양 — Close 컬럼 + DatetimeIndex면 파서엔 충분하다."""
    return pd.DataFrame({"Close": [c for _, c in rows]},
                        index=pd.to_datetime([d for d, _ in rows]))


_FDR_ROWS = {
    "CL=F": [("2026-08-07", 81.50), ("2026-08-10", 82.13)],
    # 금은 중간에 통째로 NaN인 행을 끼워 둔다 — FDR 실측 결측(futures.pick_latest_pair
    # 도크스트링 참조). 직전 유효 종가는 08-06의 4290.0이어야 한다.
    "GC=F": [("2026-08-06", 4290.00), ("2026-08-07", float("nan")),
             ("2026-08-10", 4361.80)],
}


class _FakeKis:
    """FHKST03030100만 답하는 가짜 KIS 클라이언트 — 요청 파라미터도 기록한다."""

    def __init__(self, js=None, boom=()):
        self.js = js if js is not None else _kis_js()
        self.boom = set(boom)
        self.calls = []

    async def _get(self, path, tr_id, params):
        iscd = params.get("FID_INPUT_ISCD")
        self.calls.append({"path": path, "tr_id": tr_id, "iscd": iscd,
                           "div": params.get("FID_COND_MRKT_DIV_CODE"),
                           "d1": params.get("FID_INPUT_DATE_1"),
                           "d2": params.get("FID_INPUT_DATE_2")})
        if iscd in self.boom:
            raise RuntimeError("KIS 실패 스텁")
        return self.js[iscd]


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """캐시 리셋 + 세 원천 기본 스텁(터짐) + KIS 호출 간격 0."""
    for slot in wi._cache.values():
        slot["ts"], slot["data"], slot["fail_ts"] = 0.0, None, 0.0
    wi._lock = None          # 락은 루프에 매인다 — asyncio.run을 여러 번 도는 테스트용

    def _boom_treasury(month):
        raise RuntimeError("재무부 스텁 미지정")

    def _boom_fdr(symbol, start):
        raise RuntimeError("FDR 스텁 미지정")

    def _boom_client():
        raise RuntimeError("KIS 스텁 미지정")

    def _boom_cnbc(symbol):
        raise RuntimeError("CNBC 스텁 미지정")

    monkeypatch.setattr(wi, "_fetch_cnbc", _boom_cnbc)
    monkeypatch.setattr(wi, "_fetch_treasury_xml", _boom_treasury)
    monkeypatch.setattr(wi, "_fetch_fdr", _boom_fdr)
    monkeypatch.setattr(candles, "_get_client", _boom_client)
    monkeypatch.setattr(wi, "_GAP", 0.0)   # 실호출 간격 슬립은 테스트 시간만 늘린다


def _treasury(monkeypatch, pages=None):
    """pages=None이면 어느 달을 물어도 8월 픽스처. 아니면 {'YYYYMM': xml} 매핑."""
    calls = []

    def fetch(month):
        calls.append(month)
        if pages is None:
            return _xml()
        if month not in pages:
            raise RuntimeError("해당 월 없음(404 스텁)")
        return pages[month]

    monkeypatch.setattr(wi, "_fetch_treasury_xml", fetch)
    return calls


def _fdr(monkeypatch, boom=()):
    calls = []

    def fetch(symbol, start):
        calls.append(symbol)
        if symbol in boom:
            raise RuntimeError("FDR 실패 스텁")
        return _df(_FDR_ROWS[symbol])

    monkeypatch.setattr(wi, "_fetch_fdr", fetch)
    return calls


def _kis(monkeypatch, client=None):
    c = client or _FakeKis()
    monkeypatch.setattr(candles, "_get_client", lambda: c)
    return c


def _cnbc(monkeypatch, values=None, boom=()):
    """CNBC 단건 응답 스텁. values={'US10Y': ('4.69%', '4.684%')} 형태."""
    calls = []
    vals = values if values is not None else {
        "US2Y": ("4.22%", "4.218%"), "US10Y": ("4.69%", "4.684%"),
        "US30Y": ("5.24%", "5.237%")}

    def fetch(symbol):
        calls.append(symbol)
        if symbol in boom:
            raise RuntimeError("CNBC 실패 스텁")
        last, prev = vals[symbol]
        return {"FormattedQuoteResult": {"FormattedQuote": [{
            "symbol": symbol, "last": last, "previous_day_closing": prev,
            "last_time": "2026-08-11T21:03:06.000-0400",
            "exchange": "Tradeweb", "realTime": "true"}]}}

    monkeypatch.setattr(wi, "_fetch_cnbc", fetch)
    return calls


def _fix_now(monkeypatch, when):
    """KST 시계 고정 — 조회 월·지수 basis 폴백(ET 환산)이 '지금'에 매여 있다.
    러너 타임존/실행 날짜에 결과가 흔들리지 않게 now/today를 한 시점으로 묶는다."""
    monkeypatch.setattr(wi.kst, "now", lambda: when)
    monkeypatch.setattr(wi.kst, "today", lambda: when.date())


def _groups(d) -> dict:
    return {g["label"]: g for g in d["groups"]}


def _items(g) -> dict:
    return {i["key"]: i for i in g["items"]}


# ── 재무부 XML ────────────────────────────────────────────────────────────

def test_parse_treasury_last_entry_is_latest():
    rows = wi.parse_treasury(_xml())
    assert len(rows) == 6
    assert rows[-1]["date"] == dt.date(2026, 8, 10)          # 마지막 엔트리 = 최신
    assert rows[-1]["2Y"] == 4.25
    assert rows[-1]["10Y"] == 4.72
    assert rows[-1]["30Y"] == 5.25
    assert rows[-2]["date"] == dt.date(2026, 8, 7)           # 직전 영업일(등락률 기준)
    assert wi.parse_treasury(_EMPTY_FEED) == []


def test_treasury_group_carries_unit_basis_and_rate(monkeypatch):
    _treasury(monkeypatch)
    d = asyncio.run(wi.get_worldidx())
    g = _groups(d)["미국 금리"]
    assert [i["key"] for i in g["items"]] == ["ust2y", "ust10y", "ust30y"]
    it = _items(g)["ust10y"]
    assert set(it) == {"key", "label", "value", "unit", "rate", "rate_unit", "sign",
                       "basis", "src", "basis_kind"}
    assert it["value"] == 4.72 and it["unit"] == "%"
    assert it["basis"] == "08-10" and it["src"] == "treasury"
    # 금리 등락은 bp다: 4.65 → 4.72 = +0.07%p = +7bp. 상대변화율(1.51%)이 아니다 —
    # 값 자체가 %인 그룹이라 %로 내리면 "4.72% ▲1.51%"가 1.51%p 상승으로 읽힌다.
    assert it["rate"] == 7.0 and it["rate_unit"] == "bp" and it["sign"] == "up"
    assert _items(g)["ust2y"]["value"] == 4.25               # 4.19 → 4.25
    assert _items(g)["ust30y"]["value"] == 5.25


def test_treasury_falls_back_to_previous_month_when_empty(monkeypatch):
    # 월초: 이번 달 피드는 200인데 entry가 없다 → 전월을 다시 조회한다.
    _fix_now(monkeypatch, dt.datetime(2026, 9, 1, 9, 0, tzinfo=KST))
    calls = _treasury(monkeypatch, {"202609": _EMPTY_FEED, "202608": _xml()})
    d = asyncio.run(wi.get_worldidx())
    assert calls == ["202609", "202608"]
    assert _items(_groups(d)["미국 금리"])["ust10y"]["value"] == 4.72
    assert _items(_groups(d)["미국 금리"])["ust10y"]["basis"] == "08-10"


def test_treasury_falls_back_when_month_raises(monkeypatch):
    # 이번 달 URL이 404/타임아웃으로 예외를 던져도 폴백은 살아야 한다(빈 피드만이 아니다).
    _fix_now(monkeypatch, dt.datetime(2026, 9, 1, 9, 0, tzinfo=KST))
    calls = _treasury(monkeypatch, {"202608": _xml()})       # 202609는 예외
    d = asyncio.run(wi.get_worldidx())
    assert calls == ["202609", "202608"]
    assert _items(_groups(d)["미국 금리"])["ust10y"]["value"] == 4.72


def test_treasury_single_entry_has_no_rate(monkeypatch):
    # 직전 영업일이 없으면 등락률은 '모른다' — 0.00%로 꾸미지 않는다.
    _fix_now(monkeypatch, dt.datetime(2026, 9, 1, 9, 0, tzinfo=KST))
    _treasury(monkeypatch, {"202609": _ONE_ENTRY_FEED})
    d = asyncio.run(wi.get_worldidx())
    it = _items(_groups(d)["미국 금리"])["ust10y"]
    assert it["value"] == 4.80 and it["rate"] is None and it["sign"] == "flat"
    assert it["basis"] == "09-01"


# ── FDR 원자재 ────────────────────────────────────────────────────────────

def test_parse_fdr_last_skips_nan_rows():
    q = wi.parse_fdr_last(_df(_FDR_ROWS["GC=F"]))
    assert q["value"] == 4361.80
    assert q["basis"] == dt.date(2026, 8, 10)
    assert q["rate"] == 1.67                                 # 4290.0 → 4361.8
    # 마지막 행이 NaN이면 기준일도 그 앞의 유효 행이어야 한다(NaN 날짜를 찍지 않는다).
    q2 = wi.parse_fdr_last(_df([("2026-08-10", 82.13), ("2026-08-11", float("nan"))]))
    assert q2["value"] == 82.13 and q2["basis"] == dt.date(2026, 8, 10)
    assert q2["rate"] is None                                # 유효 행 하나 → 등락률 없음
    assert wi.parse_fdr_last(_df([("2026-08-10", float("nan"))])) is None


def test_parse_fdr_last_rounds_float32_noise():
    # FDR 실호출값(2026-08-11): float32에서 승격돼 81.9800033569336로 온다 —
    # 그대로 내리면 API 응답과 화면에 그 잡음이 그대로 나간다.
    q = wi.parse_fdr_last(_df([("2026-08-07", 82.13),
                               ("2026-08-10", 81.9800033569336)]))
    assert q["value"] == 81.98
    assert wi.parse_fdr_last(_df([("2026-08-10", 4455.2998046875)]))["value"] == 4455.3


def test_commodity_group_units_are_per_barrel_and_per_ounce(monkeypatch):
    _fdr(monkeypatch)
    d = asyncio.run(wi.get_worldidx())
    it = _items(_groups(d)["원자재"])
    assert it["wti"]["value"] == 82.13 and it["wti"]["unit"] == "$/bbl"
    assert it["wti"]["basis"] == "08-10" and it["wti"]["src"] == "fdr"
    assert it["wti"]["rate"] == 0.77 and it["wti"]["sign"] == "up"
    assert it["gold"]["value"] == 4361.80 and it["gold"]["unit"] == "$/oz"
    assert it["gold"]["basis"] == "08-10"


def test_commodity_group_survives_one_symbol_failure(monkeypatch):
    _fdr(monkeypatch, boom=("GC=F",))
    d = asyncio.run(wi.get_worldidx())
    it = _items(_groups(d)["원자재"])
    assert "wti" in it and "gold" not in it      # 종목 단위 격리 — 유가는 뜬다


# ── KIS 해외지수 ──────────────────────────────────────────────────────────

def test_parse_index_reads_output1_and_output2_date():
    js = _kis_js()
    q = wi.parse_index(js["VIX"])
    assert q["value"] == 15.54 and q["rate"] == 0.52 and q["sign"] == "up"
    assert q["basis"] == dt.date(2026, 8, 11)           # output2의 stck_bsop_date
    assert wi.parse_index(js["SPX"])["basis"] is None   # output2 비어 있음 → 폴백은 호출부
    assert wi.parse_index({"rt_cd": "1"}) is None
    assert wi.parse_index({"rt_cd": "0", "output1": {}}) is None
    # 등락률만 모르는 응답은 칩을 버리지 않는다 — 값은 있고 rate만 None이다.
    half = wi.parse_index({"rt_cd": "0", "output1": {"ovrs_nmix_prpr": "7753.11"}})
    assert half["value"] == 7753.11 and half["rate"] is None and half["sign"] == "flat"


def test_index_group_asks_only_three_indices(monkeypatch):
    _fix_now(monkeypatch, FIXTURE_NOW)
    c = _kis(monkeypatch)
    d = asyncio.run(wi.get_worldidx())
    # 이 TR은 주식 티커도 받는다(CL=콜게이트, XAU=금광주) — 코드를 늘리면 단위가 어긋난다.
    assert [x["iscd"] for x in c.calls] == ["SPX", "COMP", "VIX"]
    assert {x["div"] for x in c.calls} == {"N"}
    assert {x["tr_id"] for x in c.calls} == {"FHKST03030100"}
    it = _items(_groups(d)["해외지수"])
    assert it["spx"]["value"] == 7753.11 and it["spx"]["unit"] == "idx"
    assert it["spx"]["rate"] == -0.06 and it["spx"]["sign"] == "down"
    assert it["comp"]["value"] == 26605.36
    assert it["vix"]["value"] == 15.54 and it["vix"]["sign"] == "up"
    # 21:40 KST = 08:40 ET — 아직 개장(09:30 ET) 전이라 값은 직전 세션(08-10, 월)이다.
    assert it["vix"]["basis"] == "08-10"
    assert it["spx"]["basis"] == "08-10"
    assert it["spx"]["src"] == "kis"


# ── 지수 기준일: 직전 미국 정규장으로 되감기 ──────────────────────────────

# (id, KST 시각, 기대 기준일) — ET '오늘'이 실제 세션보다 앞서는 구간들.
_SESSION_CASES = [
    # 월요일 아침: ET로는 일요일이다. 값은 금요일(08-14) 종가.
    ("mon-morning", dt.datetime(2026, 8, 17, 9, 0, tzinfo=KST), "08-14"),
    # 주말 내내 금요일 종가다.
    ("saturday", dt.datetime(2026, 8, 15, 15, 0, tzinfo=KST), "08-14"),
    # 평일 오후: ET로는 오늘이지만 미국장은 22:30 KST에나 열린다 → 어제(08-11) 종가.
    ("weekday-afternoon", dt.datetime(2026, 8, 12, 15, 0, tzinfo=KST), "08-11"),
    # 장중(23:00 KST = 10:00 ET): 이때는 오늘이 맞다 — '무조건 하루 빼기'가 아니다.
    ("in-session", dt.datetime(2026, 8, 12, 23, 0, tzinfo=KST), "08-12"),
]


@pytest.mark.parametrize("when,expected", [c[1:] for c in _SESSION_CASES],
                         ids=[c[0] for c in _SESSION_CASES])
def test_index_basis_rolls_back_to_the_last_us_session(monkeypatch, when, expected):
    """output2가 비어 오는 SPX·COMP의 폴백은 'ET 오늘'이 아니라 **직전 정규장**이다.

    ET 날짜도 실제 세션보다 앞선 날을 찍는 구간이 주중 대부분이다(주말 전체, 월요일
    아침, 매 평일 KST 13:00~22:30). 값은 직전 종가인데 날짜만 앞선 날이 박히면
    basis를 항목마다 실은 목적(신선도 착시 방지)이 정면으로 무너진다."""
    _fix_now(monkeypatch, when)
    _kis(monkeypatch)
    it = _items(_groups(asyncio.run(wi.get_worldidx()))["해외지수"])
    assert it["spx"]["basis"] == expected
    assert it["comp"]["basis"] == expected


def test_index_basis_never_runs_ahead_of_the_session(monkeypatch):
    """output2가 조회 날짜를 그대로 되비추는 경우가 있다 — 상한이 없으면 그게 그대로
    화면 기준일이 된다.

    픽스처 VIX의 output2 한 행은 OHLC(15.42/15.57/15.40)가 output1과 글자 그대로
    같은데 날짜만 조회일(20260811)이다. 같은 응답의 나스닥 누적거래량 79억주는
    '완료된 정규장 한 세션' 크기라(08:40 ET 프리마켓 물량이 아니다) output1은 직전
    세션 스냅샷이다 — 즉 그 행은 새 세션이 아니라 조회일이 덧씌워진 직전 세션이다.
    한 스냅샷이면 날짜도 하나여야 한다: 'VIX만 하루 더 최신'으로 읽히면 안 된다."""
    _fix_now(monkeypatch, dt.datetime(2026, 8, 11, 9, 0, tzinfo=KST))  # = 08-10 20:00 ET
    _kis(monkeypatch)
    it = _items(_groups(asyncio.run(wi.get_worldidx()))["해외지수"])
    assert {i["basis"] for i in it.values()} == {"08-10"}


def test_index_keeps_output2_date_when_it_is_older_than_the_session(monkeypatch):
    """상한이지 덮어쓰기가 아니다 — 원천이 더 이른 세션을 주면(휴장일 등) 그쪽이 옳다.

    미국 휴장일 달력이 없어(adr.py가 같은 한계를 기록해뒀다) 폴백은 휴장일을 모른다.
    output2가 실제 세션을 알려주는 자리라 그건 살려둔다."""
    js = _kis_js()
    js["VIX"]["output2"][0]["stck_bsop_date"] = "20260807"
    _fix_now(monkeypatch, FIXTURE_NOW)
    _kis(monkeypatch, _FakeKis(js=js))
    it = _items(_groups(asyncio.run(wi.get_worldidx()))["해외지수"])
    assert it["vix"]["basis"] == "08-07"        # 원천이 더 이르면 원천이 이긴다
    assert it["spx"]["basis"] == "08-10"        # 폴백은 그대로 직전 세션


def test_index_asks_kis_for_the_last_session_date(monkeypatch):
    """조회 날짜도 같은 함수에서 나온다 — 요청·상한·폴백이 한 시점을 가리켜야 한다.

    KST 오늘로 물으면 KST 00:00~13:00엔 ET로 아직 시작도 안 한 날짜를 묻는 셈이다."""
    _fix_now(monkeypatch, dt.datetime(2026, 8, 11, 9, 0, tzinfo=KST))
    c = _kis(monkeypatch)
    asyncio.run(wi.get_worldidx())
    assert {x["d1"] for x in c.calls} == {"20260810"}
    assert {x["d2"] for x in c.calls} == {"20260810"}


def test_index_rate_is_none_when_kis_omits_it(monkeypatch):
    """등락률을 모르면 None이다 — 0.00%(보합)로 꾸미지 않는다.

    kis._f는 빈 문자열·필드 누락을 전부 0.0으로 뭉갠다. 프런트는 rate==null일 때만
    대시를 찍으므로 0.0은 '보합'으로 그려진다 — 모르는 상태인데 화면이 '간밤 미국장
    보합'이라는 없는 사실을 단언하고, 같은 화면의 미국채·WTI는 '–'로 떠서 사용자는
    이 0.00%를 실제 관측값으로 믿는다."""
    js = _kis_js()
    js["SPX"]["output1"]["prdy_ctrt"] = ""          # 장 시작 전 필드 미채움(실측 모양)
    del js["COMP"]["output1"]["prdy_ctrt"]          # 필드 누락
    _fix_now(monkeypatch, FIXTURE_NOW)
    _kis(monkeypatch, _FakeKis(js=js))
    it = _items(_groups(asyncio.run(wi.get_worldidx()))["해외지수"])
    assert it["spx"]["rate"] is None and it["spx"]["sign"] == "flat"
    assert it["comp"]["rate"] is None and it["comp"]["sign"] == "flat"
    assert it["spx"]["value"] == 7753.11            # 값은 살아 있다 — 칩을 빼진 않는다
    assert it["vix"]["rate"] == 0.52                # 멀쩡한 칩은 그대로


def test_index_group_survives_one_symbol_failure(monkeypatch):
    c = _kis(monkeypatch, _FakeKis(boom=("COMP",)))
    d = asyncio.run(wi.get_worldidx())
    it = _items(_groups(d)["해외지수"])
    assert "spx" in it and "vix" in it and "comp" not in it


# ── 집계: 단위 보존·실패 격리·캐시 ────────────────────────────────────────

def test_units_never_mix_across_groups(monkeypatch):
    _fix_now(monkeypatch, FIXTURE_NOW)
    _treasury(monkeypatch)
    _fdr(monkeypatch)
    _kis(monkeypatch)
    d = asyncio.run(wi.get_worldidx())
    assert [g["label"] for g in d["groups"]] == ["미국 금리", "원자재", "해외지수"]
    units = {i["key"]: i["unit"] for g in d["groups"] for i in g["items"]}
    assert units == {"ust2y": "%", "ust10y": "%", "ust30y": "%",
                     "wti": "$/bbl", "gold": "$/oz",
                     "spx": "idx", "comp": "idx", "vix": "idx"}
    # basis(기준일)는 항목마다 실린다 — 살아 있는 코스피 칩 옆에서 값이 신선해 보이므로.
    for g in d["groups"]:
        for i in g["items"]:
            assert i["basis"] and len(i["basis"]) == 5
    assert d["asof"].endswith("+09:00")


def test_one_source_failure_keeps_other_groups(monkeypatch):
    # 재무부만 죽인다(autouse 스텁이 그대로 예외) → 나머지 두 그룹은 그대로 뜬다.
    _fdr(monkeypatch)
    _kis(monkeypatch)
    d = asyncio.run(wi.get_worldidx())
    assert [g["label"] for g in d["groups"]] == ["원자재", "해외지수"]


def test_all_sources_failing_returns_empty_groups():
    d = asyncio.run(wi.get_worldidx())      # autouse 스텁 3개 전부 예외
    assert d["groups"] == []
    assert d["asof"]


def test_cache_skips_refetch_within_ttl(monkeypatch):
    _fix_now(monkeypatch, FIXTURE_NOW)
    tcalls = _treasury(monkeypatch)
    fcalls = _fdr(monkeypatch)
    c = _kis(monkeypatch)
    d1 = asyncio.run(wi.get_worldidx())
    assert (len(tcalls), len(fcalls), len(c.calls)) == (1, 2, 3)
    d2 = asyncio.run(wi.get_worldidx())     # TTL 안 — 원천을 다시 부르지 않는다
    assert (len(tcalls), len(fcalls), len(c.calls)) == (1, 2, 3)
    assert d2["groups"] == d1["groups"]


def test_cache_refetches_after_ttl(monkeypatch):
    _fix_now(monkeypatch, FIXTURE_NOW)
    tcalls = _treasury(monkeypatch)
    fcalls = _fdr(monkeypatch)
    c = _kis(monkeypatch)
    asyncio.run(wi.get_worldidx())
    for name, slot in wi._cache.items():    # TTL 경과 흉내(원천별 TTL이 다르다)
        slot["ts"] -= wi._TTL[name] + 1
    asyncio.run(wi.get_worldidx())
    assert (len(tcalls), len(fcalls), len(c.calls)) == (2, 4, 6)


def test_failed_source_is_not_retried_during_cooldown(monkeypatch):
    """죽은 원천을 폴링마다 다시 두드리면 타임아웃이 매번 쌓인다(재무부는 두 달치).

    쿨다운 동안엔 호출 없이 그 그룹만 빠지고, 지난 뒤엔 다시 시도한다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    tcalls = _treasury(monkeypatch, {})     # 어느 달을 물어도 예외
    _fdr(monkeypatch)
    d = asyncio.run(wi.get_worldidx())
    assert len(tcalls) == 2                 # 이번 달 + 전월 폴백
    assert [g["label"] for g in d["groups"]] == ["원자재"]
    asyncio.run(wi.get_worldidx())          # 쿨다운 중 — 재무부는 건드리지 않는다
    assert len(tcalls) == 2
    # 슬롯 둘 다 되감는다. 그룹(treasury)은 CNBC 배려로 600초를 쓰고, 재무부 원본
    # (treasury_rows)은 기본 60초다 — 한쪽만 풀면 다른 쪽이 계속 막아 재시도가 안 온다.
    wi._cache["treasury"]["fail_ts"] -= wi._COOLDOWN["treasury"] + 1
    wi._cache["treasury_rows"]["fail_ts"] -= wi._FAIL_COOLDOWN + 1
    asyncio.run(wi.get_worldidx())
    assert len(tcalls) == 4                 # 쿨다운 만료 → 다시 시도


# ── 행(hang) 격리 ─────────────────────────────────────────────────────────
#
# 예외·빈응답만 덮는 실패 격리로는 '한 원천이 죽어도 나머지는 뜬다'가 성립하지 않는다.
# 야후가 RST 없이 무응답이 되는(TCP 블랙홀) 흔한 장애에서 원천은 예외를 던지지 않고
# **그냥 매달린다**. 아래 테스트들은 그 상태를 짧은 상한(_CALL_TIMEOUT)으로 재현한다.
# 진짜 무한대기를 쓰지 않는 이유: 3.9의 asyncio.run은 종료할 때
# shutdown_default_executor로 스레드를 join하므로 테스트가 같이 멈춘다.

def test_hung_fdr_symbol_does_not_swallow_the_other(monkeypatch):
    """FDR엔 타임아웃 인자가 없다 — fdr.DataReader → requests.get(url, headers=...)에
    timeout이 빠져 있어 기본값(무한)이다.

    게다가 WTI를 **먼저 await**하므로 CL=F 하나가 매달리면 금은 시도조차 못 한다
    ('금이 죽어도 유가는 뜬다'의 역방향이 깨진다). 핵심 단언은 '금을 시도했다'다."""
    monkeypatch.setattr(wi, "_CALL_TIMEOUT", 0.05)
    calls = []

    def fetch(symbol, start):
        calls.append(symbol)
        if symbol == "CL=F":
            time.sleep(0.3)          # 상한의 6배 — 하드 월이 먼저 끊어야 한다
        return _df(_FDR_ROWS[symbol])

    monkeypatch.setattr(wi, "_fetch_fdr", fetch)
    _fix_now(monkeypatch, FIXTURE_NOW)
    it = _items(_groups(asyncio.run(wi.get_worldidx()))["원자재"])
    assert calls == ["CL=F", "GC=F"]
    assert "wti" not in it and it["gold"]["value"] == 4361.80


def test_hung_source_does_not_hold_the_lock(monkeypatch):
    """매달린 스레드가 락을 붙잡으면 이후 폴링(아이폰+맥)이 줄서서 같이 멈춘다.

    그러면 멀쩡히 살아 있는 재무부·KIS까지 갱신이 끊겨, 화면이 몇 시간 전 스냅샷을
    무기한 붙들고 있는다. wait_for가 스레드를 죽이지는 못하지만 락을 풀고 응답을
    돌려주게는 한다 — 필요한 건 그쪽이다."""
    monkeypatch.setattr(wi, "_CALL_TIMEOUT", 0.05)

    def hang(symbol, start):
        time.sleep(0.3)
        return _df(_FDR_ROWS[symbol])

    monkeypatch.setattr(wi, "_fetch_fdr", hang)
    _fix_now(monkeypatch, FIXTURE_NOW)
    _treasury(monkeypatch)
    _kis(monkeypatch)

    async def go():
        d = await wi.get_worldidx()
        return d, wi._get_lock().locked()

    d, locked = asyncio.run(go())
    assert not locked
    assert [g["label"] for g in d["groups"]] == ["미국 금리", "해외지수"]


def test_hung_treasury_month_falls_back_like_a_404(monkeypatch):
    """재무부는 requests에 timeout=5를 걸었지만 그건 connect/read에 **각각** 적용되는
    값이라 상한이 아니다. 매달린 달은 404와 똑같이 전월 폴백을 타야 한다."""
    monkeypatch.setattr(wi, "_CALL_TIMEOUT", 0.05)
    _fix_now(monkeypatch, dt.datetime(2026, 9, 1, 9, 0, tzinfo=KST))
    calls = []

    def fetch(month):
        calls.append(month)
        if month == "202609":
            time.sleep(0.3)
            return _ONE_ENTRY_FEED   # 매달린 끝에 값을 줘도 이미 늦다 — 안 기다린다
        return _xml()

    monkeypatch.setattr(wi, "_fetch_treasury_xml", fetch)
    d = asyncio.run(wi.get_worldidx())
    assert calls == ["202609", "202608"]
    assert _items(_groups(d)["미국 금리"])["ust10y"]["basis"] == "08-10"


def test_hung_index_call_drops_only_that_chip(monkeypatch):
    """KIS도 같다 — httpx timeout=10에 재시도·백오프까지 겹치면 지수 하나가 그룹
    전체를 늘린다. 매달린 지수만 빠지고 나머지 둘은 뜬다."""
    monkeypatch.setattr(wi, "_CALL_TIMEOUT", 0.05)
    _fix_now(monkeypatch, FIXTURE_NOW)

    class _SlowKis(_FakeKis):
        async def _get(self, path, tr_id, params):
            if params.get("FID_INPUT_ISCD") == "SPX":
                await asyncio.sleep(0.3)
            return await super()._get(path, tr_id, params)

    _kis(monkeypatch, _SlowKis())
    it = _items(_groups(asyncio.run(wi.get_worldidx()))["해외지수"])
    assert "spx" not in it and "comp" in it and "vix" in it


def test_group_wall_stops_a_slow_group_from_holding_the_lock(monkeypatch):
    """호출 단위 상한이 못 잡는 지연(재시도·슬립이 겹치는 경우)의 백스톱.

    그룹 벽이 끊은 것도 '실패'로 쳐 쿨다운에 태운다 — 안 그러면 다음 폴링이 곧바로
    같은 벽에 다시 걸린다."""
    monkeypatch.setattr(wi, "_GROUP_TIMEOUT", 0.05)
    _fix_now(monkeypatch, FIXTURE_NOW)

    def slow(month):
        time.sleep(0.3)              # 호출 상한(_CALL_TIMEOUT)엔 안 걸리는 지연
        return _xml()

    monkeypatch.setattr(wi, "_fetch_treasury_xml", slow)

    async def go():
        d = await wi.get_worldidx()
        return d, wi._get_lock().locked()

    d, locked = asyncio.run(go())
    assert not locked and d["groups"] == []
    assert wi._cooling("treasury")


def test_group_wall_leaves_room_for_every_call_in_the_group():
    """벽의 크기 관계가 계약이다 — 그룹 벽이 먼저 터지면 이미 모은 칩을 통째로 버린다.

    그룹 벽 > (그룹 안 호출 수 x 호출 상한) + 호출 간 슬립 합.
    **재무부 그룹은 CNBC 단계와 재무부 폴백이 연달아 돈다** — 그 합이 벽 안에 들어와야
    CNBC가 매달려도 전월 폴백까지 갈 수 있다. 항의 개수를 하드코딩하지 않는다:
    만기나 조회 달이 하나 늘면 이 테스트가 먼저 빨개져야 한다(하드코딩한 '2'가 바로
    이 결함을 조용히 통과시켰다)."""
    idx = len(wi._INDICES) * wi._CALL_TIMEOUT + (len(wi._INDICES) - 1) * wi._GAP
    assert wi._GROUP_TIMEOUT > idx
    assert wi._GROUP_TIMEOUT > len(wi._COMMODITIES) * wi._CALL_TIMEOUT
    months = wi._treasury_month_codes(dt.date(2026, 8, 12))
    treasury = wi._CNBC_PHASE_TIMEOUT + len(months) * wi._CALL_TIMEOUT
    assert wi._GROUP_TIMEOUT > treasury, (
        "재무부 그룹 최악값 %.1f초가 벽 %.1f초를 넘는다" % (treasury, wi._GROUP_TIMEOUT))
    # 여유를 주석이 아니라 테스트가 지킨다 — 1초 남기고 통과하는 건 통과가 아니다.
    assert wi._GROUP_TIMEOUT - treasury >= 2.0, "여유 2초 미만 — 상수를 다시 잡아라"


# ── CME/현금국채 세션 판정 ────────────────────────────────────────────────

def _et(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=wi.adr._ET)


def test_cme_open_covers_the_globex_window():
    """일 18:00 ET 개장 → 금 17:00 ET 마감, 매일 17:00~18:00 ET 휴식."""
    assert wi.cme_open(_et(2026, 8, 12, 21, 0)) is True    # 수 저녁 = 한국 목 오전
    assert wi.cme_open(_et(2026, 8, 12, 17, 30)) is False  # 일일 휴식
    assert wi.cme_open(_et(2026, 8, 12, 18, 0)) is True    # 휴식 끝, 재개장
    assert wi.cme_open(_et(2026, 8, 14, 17, 0)) is False   # 금 17:00 마감 직후
    assert wi.cme_open(_et(2026, 8, 14, 16, 59)) is True   # 마감 직전
    assert wi.cme_open(_et(2026, 8, 16, 18, 0)) is True    # 일 18:00 재개장
    assert wi.cme_open(_et(2026, 8, 16, 17, 59)) is False  # 그 직전


def test_cme_open_says_closed_on_the_saturday_trap():
    """토요일 10:00 KST — 설계 문서가 경고한 구멍.

    그 시각 마지막 호가는 토 06:00 KST(= 금 17:00 ET 정산)라 '값의 시각이 오늘(KST)'
    판정을 쓰면 정산된 값에 live가 붙고, 일요일엔 같은 숫자가 마감으로 뒤집힌다.
    판정 기준은 달력 날짜가 아니라 세션이다."""
    sat_10_kst = dt.datetime(2026, 8, 15, 10, 0, tzinfo=KST)
    assert wi.cme_open(sat_10_kst.astimezone(wi.adr._ET)) is False
    sun_10_kst = dt.datetime(2026, 8, 16, 10, 0, tzinfo=KST)
    assert wi.cme_open(sun_10_kst.astimezone(wi.adr._ET)) is False


# ── basis_kind — 신선도를 데이터에 실어 내린다 ────────────────────────────

def test_basis_kind_rides_on_every_item(monkeypatch):
    """재무부는 항상 date(일 1회 확정치), 원자재는 세션, 해외지수는 미국장 개장 여부.

    프런트가 basis 문자열 모양이나 그룹 이름으로 신선도를 추측하기 시작하면 이 모듈이
    unit·rate_unit을 실어 막으려던 추측 사고가 렌더러에서 재발한다."""
    _fix_now(monkeypatch, FIXTURE_NOW)             # 2026-08-11 21:40 KST = 08:40 ET
    _treasury(monkeypatch)
    _fdr(monkeypatch)
    _kis(monkeypatch)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    monkeypatch.setattr(wi.adr, "us_market_open", lambda now_et=None: False)
    g = _groups(asyncio.run(wi.get_worldidx()))
    assert {i["basis_kind"] for i in g["미국 금리"]["items"]} == {"date"}
    assert {i["basis_kind"] for i in g["원자재"]["items"]} == {"live"}
    assert {i["basis_kind"] for i in g["해외지수"]["items"]} == {"date"}


def test_basis_kind_flips_with_the_sessions(monkeypatch):
    """세션이 닫히면 원자재는 date, 미국장이 열리면 해외지수는 live."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    _treasury(monkeypatch)
    _fdr(monkeypatch)
    _kis(monkeypatch)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: False)
    monkeypatch.setattr(wi.adr, "us_market_open", lambda now_et=None: True)
    g = _groups(asyncio.run(wi.get_worldidx()))
    assert {i["basis_kind"] for i in g["원자재"]["items"]} == {"date"}
    assert {i["basis_kind"] for i in g["해외지수"]["items"]} == {"live"}


def test_nasdaq_composite_label_is_unambiguous(monkeypatch):
    """'나스닥'은 섹션 안에서 '나스닥 선물' 칩과 나란히 뜬다 — COMP는 종합지수다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    _treasury(monkeypatch)
    _fdr(monkeypatch)
    _kis(monkeypatch)
    g = _groups(asyncio.run(wi.get_worldidx()))
    assert _items(g["해외지수"])["comp"]["label"] == "나스닥 종합"


# ── CNBC 장중 미국금리 ────────────────────────────────────────────────────

def _cnbc_js(**over):
    q = {"symbol": "US10Y", "last": "4.69%", "previous_day_closing": "4.684%",
         "last_time": "2026-08-11T21:03:06.000-0400"}
    q.update(over)
    return {"FormattedQuoteResult": {"FormattedQuote": [q]}}


def test_parse_cnbc_reads_the_percent_string():
    """last는 '4.69%' 문자열이다 — %를 떼고 읽는다. last_time에서 기준일도 나온다."""
    q = wi.parse_cnbc_yield(_cnbc_js())
    assert q["value"] == 4.69
    assert q["prev"] == 4.684
    assert q["basis"] == dt.date(2026, 8, 11)


def test_parse_cnbc_rejects_the_silent_empty_response():
    """심볼을 여러 개 붙이면 에러가 아니라 last=null인 빈 응답이 온다(2026-08-12 실측).

    사설 API는 조용히 깨진다 — 값이 없으면 '모른다'이지 0이 아니다."""
    assert wi.parse_cnbc_yield(_cnbc_js(last=None)) is None
    assert wi.parse_cnbc_yield({"FormattedQuoteResult": {"FormattedQuote": []}}) is None
    assert wi.parse_cnbc_yield({}) is None


def test_parse_cnbc_range_guard_drops_impossible_yields():
    """미국 국채 수익률이 0 이하나 15% 이상일 리 없다 — 스키마가 조용히 바뀌어
    엉뚱한 필드가 들어앉는 실패 모드를 막는다(marketdata._NGT_SANE와 같은 관례)."""
    assert wi.parse_cnbc_yield(_cnbc_js(last="0%")) is None
    assert wi.parse_cnbc_yield(_cnbc_js(last="97.5469")) is None   # 채권 가격이 들어옴
    assert wi.parse_cnbc_yield(_cnbc_js(last="4.69")) is not None  # %가 없어도 읽는다


def test_parse_cnbc_missing_prev_means_unknown_not_zero():
    """직전 종가를 모르면 rate=None이다 — 0.0bp(보합)로 꾸미지 않는다."""
    q = wi.parse_cnbc_yield(_cnbc_js(previous_day_closing=None))
    assert q["value"] == 4.69 and q["prev"] is None
    assert wi._bp_sign(q["value"], q["prev"]) == (None, "flat")


def test_treasury_group_prefers_cnbc_when_the_market_is_open(monkeypatch):
    """장중이면 CNBC — src=cnbc, basis_kind=live, 등락 단위는 bp."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    calls = _cnbc(monkeypatch)
    g = asyncio.run(wi._treasury_group())
    it = {i["key"]: i for i in g["items"]}
    assert calls == ["US2Y", "US10Y", "US30Y"]      # 순차, 세 만기 전부
    assert it["ust10y"]["value"] == 4.69
    assert it["ust10y"]["src"] == "cnbc"
    assert it["ust10y"]["basis_kind"] == "live"
    assert it["ust10y"]["rate_unit"] == "bp"
    assert it["ust10y"]["rate"] == 0.6              # (4.69-4.684)*100


def test_treasury_group_never_calls_cnbc_when_the_market_is_closed(monkeypatch):
    """휴장이면 **호출이 0건**이고 재무부로 간다.

    절약이기 전에 더 정확하다 — 시장이 닫혀 있으면 확정치가 애초에 맞는 값이다.
    이 테스트가 없으면 세션 게이트가 조용히 무력화돼도 아무도 모른다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: False)
    calls = _cnbc(monkeypatch)
    _treasury(monkeypatch)
    g = asyncio.run(wi._treasury_group())
    assert calls == []
    assert {i["src"] for i in g["items"]} == {"treasury"}
    assert {i["basis_kind"] for i in g["items"]} == {"date"}


def test_treasury_group_falls_back_when_every_tenor_fails(monkeypatch):
    """CNBC 3만기가 전부 죽으면 재무부 확정치로 조용히 강등된다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    _cnbc(monkeypatch, boom=("US2Y", "US10Y", "US30Y"))
    _treasury(monkeypatch)
    g = asyncio.run(wi._treasury_group())
    assert {i["src"] for i in g["items"]} == {"treasury"}
    assert {i["basis_kind"] for i in g["items"]} == {"date"}


def test_partial_cnbc_success_never_mixes_live_and_date(monkeypatch):
    """일부만 성공하면 성공분만 live로 낸다 — 한 그룹에 live/date를 섞지 않는다.

    기준이 섞이면 '10년만 더 최신'으로 읽히고, 금리 곡선은 만기 간 관계를 보는
    값이라 그 순간 곡선 자체가 거짓이 된다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    _cnbc(monkeypatch, boom=("US2Y",))
    _treasury(monkeypatch)
    g = asyncio.run(wi._treasury_group())
    keys = {i["key"] for i in g["items"]}
    assert keys == {"ust10y", "ust30y"}             # 2년물은 빠진다
    assert {i["basis_kind"] for i in g["items"]} == {"live"}


def test_cnbc_failure_does_not_get_hammered_while_cached(monkeypatch):
    """거절당하는 중에 1분마다 다시 두드리는 건 최악의 행동이다 — 물러선다.

    CNBC가 죽어도 재무부 폴백이 **성공하므로** 그룹은 None이 아니고 600초 캐시에
    들어간다. 그 사이 CNBC를 다시 부르지 않는 것이 back-off의 실체다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    ccalls = _cnbc(monkeypatch, boom=("US2Y", "US10Y", "US30Y"))
    tcalls = _treasury(monkeypatch)
    assert asyncio.run(wi._treasury_group()) is not None
    assert len(ccalls) == 3 and len(tcalls) == 1
    asyncio.run(wi._treasury_group())               # TTL 안이면 캐시 히트
    assert len(ccalls) == 3, "TTL 안인데 CNBC를 또 불렀다"
    assert wi._TTL["treasury"] == 600.0
    assert wi._COOLDOWN["treasury"] == 600.0


def test_both_sources_dead_backs_off_without_hammering(monkeypatch):
    """CNBC도 재무부도 죽으면 그룹을 생략하고 쿨다운에 들어간다 — 재호출 0건."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    ccalls = _cnbc(monkeypatch, boom=("US2Y", "US10Y", "US30Y"))
    tcalls = _treasury(monkeypatch, pages={})       # 어느 달을 물어도 404
    assert asyncio.run(wi._treasury_group()) is None
    n_c, n_t = len(ccalls), len(tcalls)
    assert asyncio.run(wi._treasury_group()) is None
    assert len(ccalls) == n_c and len(tcalls) == n_t, "쿨다운인데 다시 두드렸다"


def test_treasury_rows_are_cached_separately_from_the_group(monkeypatch):
    """rows를 그룹과 같이 캐시하면 CNBC가 죽어 있는 동안 재무부를 10분마다 새로
    두드리게 된다 — 하루 한 번 갱신되는 값에 대고 할 짓이 아니다."""
    _fix_now(monkeypatch, FIXTURE_NOW)
    monkeypatch.setattr(wi, "cme_open", lambda now_et=None: True)
    _cnbc(monkeypatch, boom=("US2Y", "US10Y", "US30Y"))
    tcalls = _treasury(monkeypatch)
    assert asyncio.run(wi._treasury_group()) is not None
    wi._cache["treasury"]["ts"] = 0.0               # 그룹 TTL만 만료(rows는 1시간)
    assert asyncio.run(wi._treasury_group()) is not None
    assert len(tcalls) == 1, "rows 캐시를 안 타고 재무부를 다시 불렀다"
    assert wi._TTL["treasury_rows"] == 3600.0
