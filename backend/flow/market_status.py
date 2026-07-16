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
_REFRESH_OPEN, _REFRESH_CAP = 900, 21600    # 위젯 갱신 힌트: 장중 15분 / 장외 6h 캡
_cache = {"ts": 0.0, "trade_date": None}


def wallclock_open(now=None) -> bool:
    """주말·시간대만 보는 벽시계 장중(09:00~15:30 KST). 공휴일은 모른다(cli._kr_market_open과
    동일 정의 — cli는 대시보드 폴링용이라 의존을 만들지 않고 여기 재정의)."""
    now = now or kst.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 <= hm <= 15 * 60 + 30


def next_open_sec(now=None) -> int:
    """다음 평일 09:00 KST까지 남은 초(공휴일 무시 — 깨어나면 open:false로 다시 잠듦)."""
    now = now or kst.now()
    d = now.date()
    if not (now.weekday() < 5 and now.hour < 9):
        d += dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
    target = dt.datetime.combine(d, dt.time(9, 0), tzinfo=kst.KST)
    return max(60, int((target - now).total_seconds()))


def refresh_after_sec(open_: bool, now=None) -> int:
    """위젯 갱신 힌트 — 장중 900초, 장외 min(다음 개장까지, 6h 캡)."""
    return _REFRESH_OPEN if open_ else min(next_open_sec(now), _REFRESH_CAP)


def _estimate_trade_date(now) -> str:
    """TR 폴백 — 평일 09시 이후는 오늘, 그 외(장전·주말)는 직전 평일. 공휴일은 모른다."""
    d = now.date()
    if now.weekday() < 5 and now.hour >= 9:
        return d.isoformat()
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


async def get_status(client=None, now=None) -> dict:
    """{'open','trade_date','refresh_after_sec'} — /api/widget 조립용.

    client는 KisClient(없으면 TR 생략). TR 결과는 모듈 캐시에 TTL 보관 —
    위젯 요청마다 KIS를 두드리지 않는다."""
    now = now or kst.now()
    wall = wallclock_open(now)
    ttl = _TTL_OPEN if wall else _TTL_CLOSED
    if time.time() - _cache["ts"] > ttl:
        td = None
        if client is not None:
            try:
                td = await client.latest_trade_date()
            except Exception:
                td = None
        _cache["ts"], _cache["trade_date"] = time.time(), td
    td = _cache["trade_date"]
    open_ = wall and (td is None or td == now.date().isoformat())
    return {"open": open_,
            "trade_date": td or _estimate_trade_date(now),
            "refresh_after_sec": refresh_after_sec(open_, now)}
