from __future__ import annotations

"""위젯용 장 상태/거래일 판정 — KIS 일자별 TR 1회(TTL 캐시) + KST 벽시계.

open = 벽시계 장중 AND 최신 거래일 == 오늘. 평일 공휴일(연 10일+)에 벽시계만으로
'장중' 오표시가 나는 문제를 휴장일 캘린더 없이 해소한다(설계 §거래일 판별).
TR 실패/키 없음은 벽시계 단독 폴백(공휴일 한정 부정확 허용 — 고지된 제약).
Python 3.9 호환."""

import datetime as dt
import time

from backend.flow import kst

_TTL_OPEN, _TTL_CLOSED = 600.0, 3600.0      # TR 캐시: 장중 10분 / 장외 60분
_REFRESH_OPEN, _REFRESH_CAP = 600, 21600    # 위젯 갱신 힌트: 장중 10분 / 장외 6h 캡
# 장중 10분 = 09:00~15:30(390분) 최대 39회 — iOS 위젯 하루 예산(~40-70회) 한도 내 최소.
# 더 낮추면(예:5분=78회) iOS가 예산 초과분을 임의로 건너뛰어 오히려 불규칙해진다(2026-07-17).
_cache = {"ts": 0.0, "trade_date": None, "wall": None}
_TTL_HOL = 12 * 3600.0                       # 개장일 달력 캐시 12h(공휴일은 하루 단위라 넉넉)
_hol_cache = {"ts": 0.0, "days": None}       # {'YYYYMMDD': 개장여부}


def wallclock_open(now=None) -> bool:
    """주말·시간대만 보는 벽시계 장중(09:00~15:30 KST, KRX 정규장 고정 — market_div 무관).
    공휴일은 모른다. cli._kr_market_open()은 2026-08 NXT 애프터마켓 대응으로 market_div에
    따라 08:00~20:00까지 넓어졌으므로 더는 이 함수와 동일 정의가 아니다(의도적 분기 —
    위젯 장중 판정은 여기서 독립적으로 유지, cli는 대시보드 폴링/헤더 펄스용)."""
    now = now or kst.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 <= hm <= 15 * 60 + 30


def parse_holidays(js: dict) -> dict:
    """chk-holiday(CTCA0903R) output → {'YYYYMMDD': 개장여부 bool}. 실패 응답은 {}."""
    if js.get("rt_cd") != "0":
        return {}
    out = {}
    for row in js.get("output") or []:
        d = row.get("bass_dt")
        if d:
            out[d] = row.get("opnd_yn") == "Y"
    return out


def _is_open_day(day, open_days) -> bool:
    """day(date)가 개장일인가 — 달력(open_days)이 있으면 그걸, 없으면 주말만 보는 폴백."""
    if open_days is not None:
        key = day.strftime("%Y%m%d")
        if key in open_days:
            return open_days[key]
    return day.weekday() < 5


def next_open_sec(now=None, open_days=None) -> int:
    """다음 개장일 09:00 KST까지 남은 초. open_days(개장일 달력)가 있으면 공휴일도 스킵,
    없으면 주말만 스킵(기존 동작)."""
    now = now or kst.now()
    d = now.date()
    if not (_is_open_day(d, open_days) and now.hour < 9):
        d += dt.timedelta(days=1)
        while not _is_open_day(d, open_days):
            d += dt.timedelta(days=1)
    target = dt.datetime.combine(d, dt.time(9, 0), tzinfo=kst.KST)
    return max(60, int((target - now).total_seconds()))


def refresh_after_sec(open_: bool, now=None, open_days=None) -> int:
    """위젯 갱신 힌트 — 장중 600초, 장외 min(다음 개장까지, 6h 캡)."""
    return _REFRESH_OPEN if open_ else min(next_open_sec(now, open_days), _REFRESH_CAP)


def _estimate_trade_date(now) -> str:
    """TR 폴백 — 평일 09시 이후는 오늘, 그 외(장전·주말)는 직전 평일. 공휴일은 모른다."""
    d = now.date()
    if now.weekday() < 5 and now.hour >= 9:
        return d.isoformat()
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


async def _get_open_days(client, now) -> dict:
    """개장일 달력(chk-holiday) — 12h 캐시. 실패/키없음이면 이전 캐시(또는 None)."""
    if client is None:
        return _hol_cache["days"]
    if _hol_cache["days"] is not None and time.time() - _hol_cache["ts"] < _TTL_HOL:
        return _hol_cache["days"]
    try:
        days = await client.holidays(now.strftime("%Y%m%d"))
    except Exception:
        return _hol_cache["days"]           # 실패 시 이전 캐시 유지(있으면)
    if days:
        _hol_cache["ts"], _hol_cache["days"] = time.time(), days
    return _hol_cache["days"]


async def get_status(client=None, now=None) -> dict:
    """{'open','trade_date','refresh_after_sec'} — /api/widget 조립용.

    client는 KisClient(없으면 TR 생략). TR 결과는 모듈 캐시에 TTL 보관 —
    위젯 요청마다 KIS를 두드리지 않는다."""
    now = now or kst.now()
    wall = wallclock_open(now)
    ttl = _TTL_OPEN if wall else _TTL_CLOSED
    # TTL 만료 OR 개장/마감 경계 전환 시 재조회 — 08:55(장전)에 데운 캐시가 TTL 때문에
    # 09:00 개장 직후까지 '마감'으로 오표시되던 문제 방지(리뷰 2026-07-16).
    if time.time() - _cache["ts"] > ttl or _cache.get("wall") != wall:
        td = None
        if client is not None:
            try:
                td = await client.latest_trade_date()
            except Exception:
                td = None
        _cache["ts"], _cache["trade_date"], _cache["wall"] = time.time(), td, wall
    td = _cache["trade_date"]
    open_ = wall and (td is None or td == now.date().isoformat())
    # 개장일 달력이 있으면 오늘 개장여부로 재확인 — 공휴일을 latest_trade_date 휴리스틱보다
    # 정확히 강등하고, next_open_sec의 다음 개장일도 공휴일을 건너뛴다(2026-07-18).
    open_days = await _get_open_days(client, now)
    if open_days is not None and not _is_open_day(now.date(), open_days):
        open_ = False
    return {"open": open_,
            "trade_date": td or _estimate_trade_date(now),
            "refresh_after_sec": refresh_after_sec(open_, now, open_days)}
