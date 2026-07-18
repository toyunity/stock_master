from __future__ import annotations

"""대시보드용 시장 컨텍스트 — 지수(코스피·코스닥) + 관심종목 밸류지표. REST·읽기전용.

시세(빠름)와 달리 지수/밸류는 느리게 변하므로 TTL 캐시로 KIS 호출을 아낀다. 웹소켓
미사용(1키1세션 불가침) — 전부 KisClient REST. 키 없으면 None/빈맵(대시보드가 조용히 생략).
Python 3.9 호환."""

import asyncio
import time

from backend.config import settings
from backend.education import glossary
from backend.signals import nextday

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
    data = {"valuation": val, "financials": fin[:4],   # 최근 4분기
            "explains": _explains(val, fin)}           # 값 인식형 쉬운말(순수)
    _detail_cache[code] = (time.time(), data)
    return data


def _explains(val, fin) -> dict:
    """valuation+financials → 지표 쉬운말 맵(값 없으면 키 생략). 순수·네트워크 없음."""
    v = val or {}
    f = (fin or [{}])[0] if fin else {}
    out = {"per": glossary.read_per(v.get("per")),
           "pbr": glossary.read_pbr(v.get("pbr")),
           "w52": glossary.read_w52_pos(v.get("w52_pos")),
           "roe": glossary.read_roe(f.get("roe")),
           "debt": glossary.read_debt(f.get("debt"))}
    return {k: x for k, x in out.items() if x}


_OUTLOOK_TTL = 60.0
_outlook_cache: dict = {}   # code -> (ts, dict)


async def _gather_signals(code, client) -> dict:
    """내일 예상 신호 수집 — 미국(반도체)·ADR 오버나잇·오늘 수급·모멘텀. 부분 실패 허용.
    세션은 market_status/adr로 판정. 웹소켓 미사용(REST만)."""
    from backend.flow import semi, adr, market_status
    sig = {"us": None, "adr": None, "flow": None, "momentum": None}
    sig["is_semi"] = (code in getattr(settings, "semi_kr", [])
                      or code in getattr(settings, "adr_map", {}))
    us_open = adr.us_market_open()
    kr_open = market_status.wallclock_open()
    sig["session"] = ("kr_open" if kr_open else "us_live" if us_open else "us_closed")
    try:
        ov = await semi.get_overview()
        g = {x.get("sym"): x for x in (ov.get("us") or [])}
        sig["us"] = {"sox_rate": (g.get("SOX") or {}).get("rate"),
                     "nasdaq_rate": (g.get("SOXX") or {}).get("rate"),
                     "us_open": ov.get("us_open")}
    except Exception:
        pass
    try:
        q = await adr.get_quote(client, code)
        if q and q.get("usd") and q.get("base_usd"):
            sig["adr"] = {"overnight_rate": (q["usd"] / q["base_usd"] - 1) * 100}
    except Exception:
        pass
    try:
        rows = await client.daily_investor(code)
        if rows:
            sig["flow"] = {"frgn_net": rows[0].get("frgn"), "orgn_net": rows[0].get("orgn")}
    except Exception:
        pass
    try:
        p = await client.price(code)
        if p and p.get("rate") is not None:
            sig["momentum"] = {"rate": p["rate"], "overheated": p["rate"] >= 10}
    except Exception:
        pass
    return sig


async def get_outlook(code, client=None):
    """단일 종목 내일 예상(풀) — 신호 수집 후 규칙 엔진. 60초 캐시. 신호 전멸이면 None."""
    client = client or _client()
    if client is None:
        return None
    hit = _outlook_cache.get(code)
    if hit and time.time() - hit[0] < _OUTLOOK_TTL:
        return hit[1]
    sig = await _gather_signals(code, client)
    if not any(sig.get(k) for k in ("us", "adr", "flow", "momentum")):
        return None
    o = nextday.outlook(sig)
    _outlook_cache[code] = (time.time(), o)
    return o


async def get_outlook_brief(codes, client=None):
    """관심종목 경량 내일 예상 — code→{direction,reason}. get_outlook 캐시 공유."""
    client = client or _client()
    if client is None or not codes:
        return {}
    out = {}
    for c in codes[:12]:
        o = await get_outlook(c, client)
        if o:
            reason = o["reasons"][0]["text"] if o["reasons"] else o["framing"]
            out[c] = {"direction": o["direction"], "reason": reason}
    return out


_TOPVIEW_TTL = 60.0
_topview_cache = {"ts": 0.0, "data": None}


async def get_top_view(client=None):
    """조회상위(인기) — [{code,name}] 상위 10. 60초 캐시. 코드→이름은 universe 조인."""
    client = client or _client()
    if client is None:
        return []
    if _topview_cache["data"] is not None and time.time() - _topview_cache["ts"] < _TOPVIEW_TTL:
        return _topview_cache["data"]
    try:
        codes = await client.top_view()
    except Exception:
        return _topview_cache["data"] or []
    from backend.market import universe as _universe
    from backend.news.names import resolve_name
    names = _universe.name_map(_universe.get_cached())
    data = [{"code": c, "name": resolve_name(c, names)} for c in codes[:10]]
    if data:
        _topview_cache["ts"], _topview_cache["data"] = time.time(), data
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
