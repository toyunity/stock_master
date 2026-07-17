from __future__ import annotations

"""위젯 데이터 조립 — 계정별 items(KR/US 분기) + 보유 수익. KIS 단일 소스.

응답 계약(설계 §4, 화이트리스트): open/trade_date/fetched_at/refresh_after_sec/
items[{code,name,market,currency,price,change,shares,avg,pnl,pnl_pct}] — US 항목은
여기에 us_open(장중/마감,ET) 추가. 이외 필드 추가 금지.
이 엔드포인트는 세션·2FA 없이 토큰 하나로 열리는 표면이므로 감시선(절대선·예약
매도 = 실매매 의도)·조언·타 계정 데이터는 절대 싣지 않는다.
계정 격리: 오직 인자로 받은 items만 조립(내부에서 get_watchlist/default 폴백 금지).
US 시세는 Task 13(usquote)에서 배선 — 그 전까지 US는 price:null(행 유지). Python 3.9 호환."""

import asyncio

from backend.config import settings
from backend.flow import kst, market_status
from backend.flow.pnl import compute as _pnl_compute
from backend.market import universe as _universe
from backend.news.names import resolve_name

_SEM = 5   # KIS 동시 호출 상한 — 연속 호출 간헐 500 완화(kis.py 실측 주석)


def _us_name(code):
    """US 티커 표시명 — semi.US_NAMES 우선, 없으면 티커 그대로(Task 12 usquote.us_name 예정)."""
    from backend.flow.semi import US_NAMES
    return US_NAMES.get(code, code)


async def widget_data(email, items):
    """위젯 응답 dict — items는 그 계정 get_watchlist(email) 결과(dict 배열).

    KR 코드만 KIS/universe로 시세 조회(US는 Task 13까지 null). KIS 불가/전멸 +
    캐시 없음이면 None(라우트가 503). 부분 실패는 행을 빼지 않고 price:null로 유지.
    email은 소유 계정 표식(격리 감사용) — 조립은 인자 items에만 의존한다."""
    kr_codes = [it["code"] for it in items if it.get("market") == "KR"]

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

        prices = dict(await asyncio.gather(*[one(c) for c in kr_codes]))

    if not any(v is not None for v in prices.values()):
        # 폴백: universe 캐시 stale 읽기 전용(설계 — KIS 실패 시에만, 수집 트리거 금지)
        pm = _universe.price_map(_universe.get_cached())
        prices = {c: ({"price": pm[c]["close"], "change": pm[c]["change"]}
                      if c in pm and pm[c].get("close") is not None else None)
                  for c in kr_codes}
        if not any(v is not None for v in prices.values()):
            return None

    st = await market_status.get_status(client)
    names = _universe.name_map(_universe.get_cached())   # stale 허용 읽기 전용(수집 금지)
    out = []
    for it in items:
        code = it["code"]
        market = "US" if it.get("market") == "US" else "KR"
        pr = prices.get(code) or {}
        price, change = pr.get("price"), pr.get("change")
        shares, avg = it.get("shares"), it.get("avg")
        pnl = _pnl_compute(price, avg, shares)
        row = {"code": code,
               "name": resolve_name(code, names) if market == "KR" else _us_name(code),
               "market": market,
               "currency": "KRW" if market == "KR" else "USD",
               "price": price, "change": change,
               "shares": shares, "avg": avg,
               "pnl": pnl["pnl"], "pnl_pct": pnl["pnl_pct"]}
        if market == "US":
            from backend.flow.adr import us_market_open
            row["us_open"] = us_market_open()   # ET 정규장 여부(US 행 신선도, 순수 함수)
        out.append(row)
    return {"open": st["open"], "trade_date": st["trade_date"],
            "fetched_at": kst.now().isoformat(timespec="seconds"),
            "refresh_after_sec": st["refresh_after_sec"], "items": out}
