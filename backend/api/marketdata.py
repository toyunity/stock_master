from __future__ import annotations

"""대시보드용 시장 컨텍스트 — 지수(코스피·코스닥) + 관심종목 밸류지표. REST·읽기전용.

시세(빠름)와 달리 지수/밸류는 느리게 변하므로 TTL 캐시로 KIS 호출을 아낀다. 웹소켓
미사용(1키1세션 불가침) — 전부 KisClient REST. 키 없으면 None/빈맵(대시보드가 조용히 생략).
Python 3.9 호환."""

import asyncio
import time

from backend.config import settings

_IDX_TTL = 30.0            # 지수 30초
_FUN_TTL = 300.0          # 밸류 5분(일 단위로만 바뀜)
_SEM = 5                  # KIS 동시 호출 상한(kis.py 실측)
_idx_cache = {"ts": 0.0, "data": None}
_fun_cache: dict = {}     # code -> (ts, dict|None)


def _client():
    if not settings.kis_app_key:
        return None
    try:
        from backend.flow.candles import _get_client
        return _get_client()
    except Exception:
        return None


async def get_indices(client=None):
    """{'kospi':{price,change,rate,sign}, 'kosdaq':{...}} — 30초 캐시. 키없음/실패면 None."""
    client = client or _client()
    if client is None:
        return None
    if _idx_cache["data"] is not None and time.time() - _idx_cache["ts"] < _IDX_TTL:
        return _idx_cache["data"]
    try:
        kospi = await client.index("0001")
        kosdaq = await client.index("1001")
    except Exception:
        return _idx_cache["data"]
    if kospi or kosdaq:
        _idx_cache["ts"], _idx_cache["data"] = time.time(), {"kospi": kospi, "kosdaq": kosdaq}
    return _idx_cache["data"]


_DETAIL_TTL = 300.0
_detail_cache: dict = {}   # code -> (ts, dict)
_ASK_TTL = 2.0            # 호가 스냅샷 2초(빠르게 변함, 다중 뷰어 폭주만 방지)
_ask_cache: dict = {}     # code -> (ts, dict|None)


async def get_asking(code, client=None):
    """호가 사다리 스냅샷 — 2초 캐시. 키없음/실패면 {}(‌/live가 조용히 생략)."""
    client = client or _client()
    if client is None:
        return {}
    hit = _ask_cache.get(code)
    if hit and time.time() - hit[0] < _ASK_TTL:
        return hit[1] or {}
    try:
        a = await client.asking_price(code)
    except Exception:
        return (hit[1] if hit else {}) or {}
    _ask_cache[code] = (time.time(), a)
    return a or {}


async def get_stock_detail(code, client=None):
    """단일 종목 상세 — {'valuation':{per,pbr,...}, 'financials':[분기...]}. 5분 캐시.
    /live 상세용(재무 체력 + 밸류). 키없음/실패면 빈 dict."""
    client = client or _client()
    if client is None:
        return {}
    hit = _detail_cache.get(code)
    if hit and time.time() - hit[0] < _DETAIL_TTL:
        return hit[1]
    val, fin = None, []
    try:
        val = await client.fundamentals(code)
        fin = await client.financials(code)
    except Exception:
        return (hit[1] if hit else {})
    data = {"valuation": val, "financials": fin[:4]}   # 최근 4분기
    _detail_cache[code] = (time.time(), data)
    return data


async def get_fundamentals(codes, client=None):
    """{code: {per,pbr,eps,bps,w52_high,w52_low,w52_pos}} — 코드별 5분 캐시. 실패 코드는 생략."""
    client = client or _client()
    if client is None or not codes:
        return {}
    now = time.time()
    fresh, stale = {}, []
    for c in codes:
        hit = _fun_cache.get(c)
        if hit and now - hit[0] < _FUN_TTL:
            if hit[1]:
                fresh[c] = hit[1]
        else:
            stale.append(c)
    if stale:
        sem = asyncio.Semaphore(_SEM)

        async def one(code):
            async with sem:
                try:
                    return code, await client.fundamentals(code)
                except Exception:
                    return code, None
        for code, f in await asyncio.gather(*(one(c) for c in stale)):
            _fun_cache[code] = (now, f)
            if f:
                fresh[code] = f
    return fresh
