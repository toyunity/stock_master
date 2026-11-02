"""market_status.next_trade_date — 판정 장부의 outlook 목표일(다음 개장일) 걸음."""
from __future__ import annotations

import datetime as dt

from backend.flow import market_status as ms
from backend.flow.kst import KST


def _at(y, m, d, h):
    return dt.datetime(y, m, d, h, 0, tzinfo=KST)


def test_next_trade_date_before_open_is_today():
    assert ms.next_trade_date(_at(2026, 11, 3, 8), None) == "2026-11-03"   # 화


def test_next_trade_date_after_open_is_tomorrow():
    assert ms.next_trade_date(_at(2026, 11, 3, 18), None) == "2026-11-04"


def test_next_trade_date_skips_weekend():
    assert ms.next_trade_date(_at(2026, 11, 6, 18), None) == "2026-11-09"   # 금 → 월


def test_next_trade_date_skips_holiday_from_calendar():
    cal = {"20261104": False, "20261105": True}
    assert ms.next_trade_date(_at(2026, 11, 3, 18), cal) == "2026-11-05"


def test_next_open_sec_still_uses_same_walk():
    assert ms.next_open_sec(_at(2026, 11, 6, 18), None) == int(
        (_at(2026, 11, 9, 9) - _at(2026, 11, 6, 18)).total_seconds())
