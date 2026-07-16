from __future__ import annotations

"""위젯 데이터 조립 — KIS 단일 소스(시간대 불문), 실패 종목은 price:null 유지.

응답 계약(설계 §응답 계약, 화이트리스트): open/trade_date/fetched_at/
refresh_after_sec/items[{code,name,price,change}] — 이외 필드 추가 금지.
이 엔드포인트는 세션·2FA 없이 정적 토큰 하나로 열리는 표면이므로 감시선
(절대선·예약매도 = 실매매 의도)·조언·계좌성 정보는 절대 싣지 않는다.
Python 3.9 호환."""

import asyncio

from backend.config import settings
from backend.flow import kst, market_status
from backend.market import universe as _universe
from backend.news.names import display_name

_SEM = 5   # KIS 동시 호출 상한 — 연속 호출 간헐 500 완화(kis.py 실측 주석)


async def widget_data(codes):
    """위젯 응답 dict — KIS 불가/전멸 + 캐시 없음이면 None(라우트가 503).

    부분 실패는 행을 빼지 않고 price:null로 유지(조용한 누락 금지 — 위젯이 '—' 표시)."""
    client = None
    if settings.kis_app_key:
        try:
            from backend.flow.candles import _get_client
            client = _get_client()
        except Exception:
            client = None

    prices = {}
    if client is not None:
        sem = asyncio.Semaphore(_SEM)

        async def one(c):
            async with sem:
                try:
                    p = await client.price(c)
                except Exception:
                    return c, None
            if p and p.get("price"):
                return c, {"price": p["price"], "change": p.get("rate")}
            return c, None

        prices = dict(await asyncio.gather(*[one(c) for c in codes]))

    if not any(v is not None for v in prices.values()):
        # 폴백: universe 캐시 stale 읽기 전용(설계 — KIS 실패 시에만, 수집 트리거 금지)
        pm = _universe.price_map(_universe.get_cached())
        prices = {c: ({"price": pm[c]["close"], "change": pm[c]["change"]}
                      if c in pm and pm[c].get("close") is not None else None)
                  for c in codes}
        if not any(v is not None for v in prices.values()):
            return None

    st = await market_status.get_status(client)
    items = [{"code": c, "name": display_name(c),
              "price": (prices.get(c) or {}).get("price"),
              "change": (prices.get(c) or {}).get("change")} for c in codes]
    return {"open": st["open"], "trade_date": st["trade_date"],
            "fetched_at": kst.now().isoformat(timespec="seconds"),
            "refresh_after_sec": st["refresh_after_sec"], "items": items}
