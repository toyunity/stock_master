from __future__ import annotations

"""위젯 데이터 조립 — 계정별 items(KR/US 분기) + 보유 수익. KIS 단일 소스.

응답 계약(설계 §4, 화이트리스트): open/trade_date/fetched_at/refresh_after_sec/
items[{code,name,market,currency,price,change,shares,avg,pnl,pnl_pct}] — US 항목은
여기에 us_open(장중/마감,ET) 추가. 이외 필드 추가 금지.
이 엔드포인트는 세션·2FA 없이 토큰 하나로 열리는 표면이므로 감시선(절대선·예약
매도 = 실매매 의도)·조언·타 계정 데이터는 절대 싣지 않는다.
계정 격리: 오직 인자로 받은 items만 조립(내부에서 get_watchlist/default 폴백 금지).
US 시세는 usquote.price_us(거래소 순회 NAS→NYS→AMS)로 조회 — client 없으면 null(행 유지).
전멸(None→503) 판정은 KR+US 합산으로(US 전용 계정이 항상 503으로 죽지 않게). Python 3.9 호환."""

import asyncio

from backend.config import settings
from backend.flow import kst, market_status
from backend.flow.pnl import compute as _pnl_compute
from backend.market import universe as _universe
from backend.news.names import resolve_name

_SEM = 5   # KIS 동시 호출 상한 — 연속 호출 간헐 500 완화(kis.py 실측 주석)


def _universe_mtime():
    """universe 캐시 파일이 **쓰인** 시각(KST). 없으면 None.

    폴백값의 나이는 요청 시각이 아니라 이 시각이다 — get_cached는 나이를 보지 않아
    수집 배치가 며칠 멈춰도 같은 얼굴로 값을 준다."""
    import datetime as _dt
    import os
    try:
        mt = os.path.getmtime(_universe._cache_path(settings.cache_dir))
    except OSError:
        return None
    return _dt.datetime.fromtimestamp(mt, kst.KST)


def _us_name(code):
    """US 티커 표시명 — semi.US_NAMES 우선, 없으면 티커 그대로(Task 12 usquote.us_name 예정)."""
    from backend.flow.semi import US_NAMES
    return US_NAMES.get(code, code)


async def widget_data(email, items):
    """위젯 응답 dict — items는 그 계정 get_watchlist(email) 결과(dict 배열).

    KR은 KIS/universe로, US는 usquote.price_us(거래소 순회)로 시세 조회. KIS 불가/전멸 +
    캐시 없음이면 None(라우트가 503). 부분 실패는 행을 빼지 않고 price:null로 유지.
    email은 소유 계정 표식(격리 감사용) — 조립은 인자 items에만 의존한다."""
    kr_codes = [it["code"] for it in items if it.get("market") == "KR"]
    us_syms = [it["code"] for it in items if it.get("market") == "US"]

    client = None
    if settings.kis_app_key:
        try:
            from backend.flow.candles import _get_client
            client = _get_client()
        except Exception:
            client = None

    fetched = kst.now()
    prices = {}
    if client is not None:
        from backend.flow import usquote     # 모듈 경유(테스트가 price_us 모킹 가능)
        sem = asyncio.Semaphore(_SEM)

        async def one_kr(c):
            async with sem:
                try:
                    p = await client.price(c)
                except Exception:
                    return c, None
            if p and p.get("price"):
                return c, {"price": p["price"], "change": p.get("rate")}
            return c, None

        async def one_us(s):
            async with sem:
                try:
                    q = await usquote.price_us(client, s)
                except Exception:
                    return s, None
            if q and q.get("price"):
                return s, {"price": q["price"], "change": q.get("change")}
            return s, None

        tasks = [one_kr(c) for c in kr_codes] + [one_us(s) for s in us_syms]
        prices = dict(await asyncio.gather(*tasks))

    # 전멸 판정은 KR+US 합산 — US 성공이 하나라도 있으면 폴백/503으로 빠지지 않는다(advisor #1).
    if not any(v is not None for v in prices.values()):
        # 폴백: universe 캐시 stale 읽기 전용(설계 — KIS 실패 시에만, 수집 트리거 금지).
        # US는 universe 폴백 없음(개인용·개별 격리) → client 없으면 price:null.
        pm = _universe.price_map(_universe.get_cached())
        prices = {c: ({"price": pm[c]["close"], "change": pm[c]["change"]}
                      if c in pm and pm[c].get("close") is not None else None)
                  for c in kr_codes}
        if not any(v is not None for v in prices.values()):
            return None
        # 위젯은 fetched_at을 'HH:MM 갱신'으로 그대로 찍는다 — 폴백값에 '지금' 도장을
        # 찍으면 10:56 종가가 14:00 값으로 보이고 평가손익까지 그 값으로 계산된다.
        fetched = _universe_mtime() or fetched

    st = await market_status.get_status(client)
    from backend.flow.adr import us_market_open
    us_open_now = us_market_open()   # ET 정규장 여부(순수 함수) — US 행 신선도 + 갱신 힌트에 공유
    # 갱신 힌트 보정: refresh_after_sec는 KR 장 기준이라, 밤(KR 마감·US 개장) 구간에서 6h로
    # 늘어져 미국주식(하이닉스 ADR 등)이 최대 6시간 얼어붙었다. 계정에 US 종목 + 미국 정규장이면
    # 장중값(10분)으로 당긴다 — KR 장중값 재사용(refresh_after_sec(True) == _REFRESH_OPEN, 2026-07-17).
    refresh = st["refresh_after_sec"]
    if us_syms and us_open_now:
        refresh = min(refresh, market_status.refresh_after_sec(True))
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
            row["us_open"] = us_open_now   # ET 정규장 여부(US 행 신선도) — 갱신 힌트와 동일 값 공유
        out.append(row)
    return {"open": st["open"], "trade_date": st["trade_date"],
            "fetched_at": fetched.isoformat(timespec="seconds"),
            "refresh_after_sec": refresh, "items": out}
