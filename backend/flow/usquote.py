from __future__ import annotations

"""미국 주식 시세 — 거래소 순회(NAS→NYS→AMS) 일반화 + 종목별 이름. 설계 2026-07-17 §3.

semi._us_quote(HHDFS00000300, EXCD=NAS 고정)를 거래소 순회로 일반화한다(엔진 불변 —
semi 로직/응답 shape은 건드리지 않고, 파싱·이름·경로만 import 재사용):

- price_us(client, sym) -> {price, change, currency:"USD", exch} | None
  EXCD를 NAS→NYS→AMS 순으로 시도, 첫 '유효' 응답 채택. 유효 판정 =
  last>0 AND (거래량>0 OR 기준가 존재) — 스테일·미상장 거래소 오채택 방지.
  순회 간 _GAP(0.25s) 유지(간헐 500 완화). 확정 거래소는 종목별 캐시(TTL 12h)해
  매 요청 재순회·호출폭주 방지(시세값 60s 캐시는 상위 위젯 조립에 위임).
- us_name(sym): semi.US_NAMES 우선, 없으면 티커 그대로
  (KIS 해외현재가 응답엔 한글 종목명 필드가 없음 — 자주 담는 종목은 US_NAMES 수동 보강).
"""

import asyncio
import time
from typing import Optional

from backend.flow import toss
from backend.flow.kis import _f
from backend.flow.semi import _GAP, _US_PATH, US_NAMES, parse_us_quote

_EXCHANGES = ("NAS", "NYS", "AMS")
_EXCH_TTL = 12 * 3600.0
_exch_cache: dict = {}  # sym -> (exch, ts) — 확정 거래소만, 실패는 캐시 안 함


def us_name(sym) -> str:
    return US_NAMES.get(sym, sym)


def _valid(js: dict) -> Optional[dict]:
    """last>0(parse_us_quote) AND 거래량/기준가 존재면 파싱결과, 아니면 None."""
    q = parse_us_quote(js)  # last<=0 또는 rt_cd!=0 이면 None
    if q is None:
        return None
    o = js.get("output") or {}
    tvol = _f(str(o.get("tvol", "")).strip())
    if tvol > 0 or q.get("base") is not None:
        return q
    return None  # 스테일(거래량0·기준가 없음) 배제


def _cached_exch(sym) -> Optional[str]:
    hit = _exch_cache.get(sym)
    if hit and time.time() - hit[1] < _EXCH_TTL:
        return hit[0]
    return None


def _order(sym) -> list:
    """확정 거래소가 캐시돼 있으면 그걸 먼저(스테일화 대비 나머지도 뒤에 순회)."""
    cached = _cached_exch(sym)
    if cached and cached in _EXCHANGES:
        return [cached] + [e for e in _EXCHANGES if e != cached]
    return list(_EXCHANGES)


async def _toss_quote(sym) -> Optional[dict]:
    """토스 **1콜 실시간** 미국 시세. 키가 없거나 못 만들면 None(KIS 순회로 폴백).

    2026-09-03 실측(KST 15:47, 미국 데이마켓): AAPL 최근 체결이 조회 대비 최소 4.2초 —
    15분 지연 피드가 아니다. KIS는 해외 실시간에 거래소 신청 권한이 필요해 막혀 있던
    자리다(worldidx 주석 EGW00551/EGW00553 참조).

    일봉 count=2 **한 콜**로 끝내는 이유: 최신 봉의 종가가 곧 실시간 현재가이고
    (같은 실측: 봉 close 324.56 = /prices lastPrice 324.56), [-2]가 전일 확정 종가라
    등락률까지 같은 응답에서 나온다. `/prices`만 부르면 lastPrice뿐이라 등락률이 없어
    콜이 두 배가 된다.

    미국장이 아직 안 열린 시간대면 [-1]이 직전 완료 세션이고 등락률도 그 세션 기준이
    된다 — 그게 맞는 값이다. 봉이 하나뿐이면 **None을 준다**: 한 봉으로 change=0을
    지어내면 '보합'이라는 틀린 판정이 화면에 나간다."""
    client = toss.get_client()
    if client is None:
        return None
    try:
        rows = await client.stock_candles(sym, "1d", 2)
    except Exception:
        return None
    if len(rows) < 2 or not rows[-2]["close"]:
        return None
    last, prev = rows[-1]["close"], rows[-2]["close"]
    return {"price": last, "change": round((last / prev - 1) * 100, 2),
            "currency": "USD", "exch": None, "src": "toss"}


async def price_us(client, sym) -> Optional[dict]:
    """미국 현재가 — 토스(1콜 실시간) 우선, 실패하면 KIS 거래소 순회.

    KIS를 지우지 않는 이유는 shortbal과 같다: 키 없음·허용 IP 어긋남(둘 다 403)에
    미국 시세가 통째로 사라지면 안 된다. `client`(KIS)가 None이어도 토스만으로 값이
    나온다 — 라우트의 'KIS 없으면 204' 가드가 더는 필요조건이 아니다."""
    q = await _toss_quote(sym)
    if q is not None:
        return q
    if client is None:
        return None
    for i, exch in enumerate(_order(sym)):
        if i:
            await asyncio.sleep(_GAP)  # 연속 호출 간헐 500 완화(실측 관례)
        try:
            js = await client._get(_US_PATH, "HHDFS00000300",
                                   {"AUTH": "", "EXCD": exch, "SYMB": sym})
        except Exception:
            continue
        q = _valid(js)
        if q is not None:
            _exch_cache[sym] = (exch, time.time())  # 성공만 캐시
            return {"price": q["last"], "change": q["rate"],
                    "currency": "USD", "exch": exch, "src": "kis"}
    return None
