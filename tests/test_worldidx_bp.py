"""국채 등락은 bp다 — %가 아니라.

10년물이 4.65 → 4.72로 움직이면 채권시장은 **+7bp**라고 말한다. 상대변화율
(+1.51%)도 틀린 계산은 아니지만, 화면에 "4.72% ▲1.51%"로 나가면 금리가
1.51%p 뛰었다는 뜻으로 읽힌다 — 값 자체가 %인 유일한 그룹이라 유독 위험하다.
등락의 단위를 항목에 실어(`rate_unit`) 프런트가 추측하지 않게 한다.
"""
import datetime as dt

import pytest

from backend.flow import worldidx


def _treasury_items(monkeypatch):
    """재무부 그룹만 실제 조립 경로로 만든다(네트워크 없음)."""
    rows = [{"date": dt.date(2026, 8, 7), "2Y": 4.19, "10Y": 4.65, "30Y": 5.19},
            {"date": dt.date(2026, 8, 10), "2Y": 4.25, "10Y": 4.72, "30Y": 5.25}]

    async def fake_rows():
        return rows

    monkeypatch.setattr(worldidx, "_treasury_rows", fake_rows)
    worldidx._cache["treasury"].update(ts=0.0, data=None, fail_ts=0.0)
    import asyncio
    g = asyncio.run(worldidx._treasury_group())
    worldidx._cache["treasury"].update(ts=0.0, data=None, fail_ts=0.0)
    return {it["key"]: it for it in g["items"]}


def test_국채_등락은_bp로_내려온다(monkeypatch):
    items = _treasury_items(monkeypatch)
    ten = items["ust10y"]
    assert ten["value"] == 4.72
    assert ten["rate_unit"] == "bp"
    # 4.72 - 4.65 = 0.07%p = 7bp. 상대변화율 1.51이 아니다.
    assert ten["rate"] == pytest.approx(7.0, abs=0.05)
    assert ten["sign"] == "up"


def test_2년물도_같은_규칙(monkeypatch):
    two = _treasury_items(monkeypatch)["ust2y"]
    assert two["rate_unit"] == "bp"
    assert two["rate"] == pytest.approx(6.0, abs=0.05)   # 4.25 - 4.19


def test_직전값_없으면_bp도_None(monkeypatch):
    rows = [{"date": dt.date(2026, 8, 10), "2Y": 4.25, "10Y": 4.72, "30Y": 5.25}]

    async def fake_rows():
        return rows

    monkeypatch.setattr(worldidx, "_treasury_rows", fake_rows)
    worldidx._cache["treasury"].update(ts=0.0, data=None, fail_ts=0.0)
    import asyncio
    g = asyncio.run(worldidx._treasury_group())
    worldidx._cache["treasury"].update(ts=0.0, data=None, fail_ts=0.0)
    it = g["items"][0]
    assert it["rate"] is None and it["sign"] == "flat"
    assert it["rate_unit"] == "bp"      # 값이 없어도 단위는 고정이다


def test_원자재와_지수는_여전히_퍼센트():
    """bp는 채권에만. 다른 그룹까지 번지면 그게 새 단위 사고다."""
    it = worldidx._item("wti", "WTI", 82.13, "$/bbl", -0.07, "down", "08-11", "fdr")
    assert it["rate_unit"] == "%"
    ix = worldidx._item("spx", "S&P500", 7753.11, "idx", 0.09, "up", "08-11", "kis")
    assert ix["rate_unit"] == "%"


def test_화면에_bp가_찍히고_퍼센트_오독이_없다():
    """렌더러가 rate_unit을 실제로 쓰는지 — 서버만 고치고 프런트가 %를 붙이면 헛일이다."""
    import backend.report.dashboard as dash
    src = open(dash.__file__, encoding="utf-8").read()
    i = src.index("function gchip(")
    gchip = src[i:src.index("\n}", i)]
    assert "rate_unit" in gchip, "gchip이 rate_unit을 안 본다 — 단위를 프런트가 추측 중"
