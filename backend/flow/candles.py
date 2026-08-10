from __future__ import annotations

"""봉 차트 데이터 — 당일 분봉(1/5/15분) + 일봉 + 주봉·월봉.

분봉: KIS FHKST03010200(호출당 30봉, 기준시각 역방향, 당일만 제공 — 실측)을
기준시각을 당기며 페이지네이션해 하루치를 조립(60s 캐시), 5/15분은 서버 집계.
일봉: 기존 FDR 캐시 어댑터(대시보드와 동일 경로, 120일).
주·월봉: 일봉 15년(FDR, 키 불필요)을 ISO 주/연-월로 서버 집계 — KIS TR을 안 쓰므로
국내·미국 티커 모두 같은 경로다.
키 없으면(데모) 시드 랜덤워크로 당일 분봉을 합성해 화면은 항상 동작한다.
"""

import asyncio
import datetime as dt
import logging
import random
import time

from backend.config import settings
from backend.flow import kst
from backend.flow.demo import lookup_stock
from backend.flow.kis import KisClient, parse_minute_candles

log = logging.getLogger(__name__)

_MIN_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
_TTL = 60.0
_GAP = 0.2          # 연속 호출 간헐 500 완화(실측)
_MAX_CALLS = 26     # UN(08:00~20:00) 최대 720분/30봉 = 24콜 + 여유
_min_cache: dict = {}   # code -> (ts, bars)
_krx_only: dict = {}    # code -> 'J' — 통합 조회가 빈 값이라 KRX 전용으로 확정된 종목
_daily_cache: dict = {}  # code -> (ts, candles)
_long_cache: dict = {}   # code -> (ts, 일봉 15년) — 주·월봉 공용 원료(네이버 호출 상한)
_client = None

# '1mo'인 이유: 월봉을 '1M'으로 적으면 1분봉 '1m'과 대소문자만 다르다 —
# 소문자 정규화 한 번이면 분봉이 월봉으로 둔갑하므로 처음부터 겹칠 수 없는 철자를 쓴다.
TIMEFRAMES = ("1m", "5m", "15m", "60m", "1d", "1w", "1mo")
_LONG_YEARS = 15    # 주봉 ma120(240주≈4.6년)은 다 차고, 월봉 ma120(240개월)은 표본 부족 안내로 처리


def _attach_ma(bars: list) -> list:
    """각 봉에 5/10/20/60/120봉 단순이동평균(ma5..ma120)을 부착.
    앞 구간이 부족하면 None(프런트가 그 지점부터 선을 그림). 종가 기준."""
    closes = [b["close"] for b in bars]
    csum = [0.0]
    for c in closes:
        csum.append(csum[-1] + c)          # 누적합으로 O(n) 이동평균
    for n in (5, 10, 20, 60, 120):
        key = "ma" + str(n)
        for i, b in enumerate(bars):
            b[key] = round((csum[i + 1] - csum[i + 1 - n]) / n, 2) if i + 1 >= n else None
    return bars


def _get_client() -> KisClient:
    global _client
    if _client is None:
        _client = KisClient(settings.kis_app_key, settings.kis_app_secret,
                            settings.cache_dir, market_div=settings.market_div)
    return _client


def _session_window() -> tuple:
    """(시작, 마감 캡) — NXT 포함(UN/NX)이면 프리 08:00 ~ 애프터 20:00까지.
    KIS 문자열 포맷(시작 'HH:MM:SS', 마감 'HHMMSS')은 session_minutes()(단일 정의 소스)에서 파생."""
    from backend.flow.session import session_minutes
    start, end = session_minutes(settings.market_div)
    return "%02d:%02d:00" % divmod(start, 60), "%02d%02d00" % divmod(end, 60)


def aggregate(bars: list, n: int) -> list:
    """1분봉 → n분봉. 버킷은 09:00 기준 정렬(09:00~09:04 → 09:00 봉)."""
    out: dict = {}
    for b in bars:
        hh, mm, _ = b["t"].split(":")
        m = int(hh) * 60 + int(mm)
        start = m - ((m - 540) % n if m >= 540 else m % n)
        c = out.get(start)
        if c is None:
            out[start] = {"t": f"{start // 60:02d}:{start % 60:02d}:00",
                          "open": b["open"], "high": b["high"],
                          "low": b["low"], "close": b["close"], "vol": b["vol"]}
        else:
            c["high"] = max(c["high"], b["high"])
            c["low"] = min(c["low"], b["low"])
            c["close"] = b["close"]
            c["vol"] += b["vol"]
    return [out[k] for k in sorted(out)]


def aggregate_daily(bars: list, tf: str) -> list:
    """일봉 → 주봉('1w', ISO 주)·월봉('1mo', 연-월). 시가=첫 거래일, 종가=마지막 거래일,
    고저=구간 극값, 거래량=합. 시간 라벨은 버킷의 마지막 거래일(형성 중인 봉은 오늘)."""
    out: dict = {}
    order: list = []
    for b in bars:
        d = dt.date.fromisoformat(b["t"])
        key = d.isocalendar()[:2] if tf == "1w" else (d.year, d.month)
        c = out.get(key)
        if c is None:
            out[key] = {"t": b["t"], "open": b["open"], "high": b["high"],
                        "low": b["low"], "close": b["close"], "vol": b.get("vol", 0)}
            order.append(key)
        else:
            c["high"] = max(c["high"], b["high"])
            c["low"] = min(c["low"], b["low"])
            c["close"] = b["close"]
            c["vol"] += b.get("vol", 0)
            c["t"] = b["t"]
    return [out[k] for k in order]


def _need_refetch(cached, start) -> bool:
    """PriceAdapter는 end 커버리지만 본다 — 대시보드가 만든 400일짜리 캐시도 end만
    덮으면 그대로 반환되므로, 장기 조회는 시작 커버리지를 여기서 직접 확인한다.
    상장이 늦어 이력이 원래 짧은 종목은 구분할 수 없어 매번 재조회가 되는데,
    _long_cache(1시간)가 상한을 걸어 네이버 부담은 종목당 시간당 1회다."""
    import pandas as pd
    return not (cached is not None and len(cached)
                and cached.index.min() <= pd.Timestamp(start) + pd.Timedelta(days=31))


def _long_daily_bars(code: str) -> list:
    """주·월봉 원료 — 일봉 15년(FDR 경로, 키 불필요). 1시간 메모리 캐시."""
    now = time.time()
    hit = _long_cache.get(code)
    if hit and now - hit[0] < 3600:
        return hit[1]
    from backend.adapters.cache import OHLCVCache
    from backend.adapters.prices import PriceAdapter
    from backend.report.dashboard import to_candles
    end = dt.date.today()
    start = end - dt.timedelta(days=_LONG_YEARS * 365)
    cache = OHLCVCache(settings.cache_dir)
    df = PriceAdapter(cache).get_ohlcv(code, start.isoformat(), end.isoformat(),
                                       force=_need_refetch(cache.get(code), start))
    bars = [{"t": c["time"], "open": c["open"], "high": c["high"],
             "low": c["low"], "close": c["close"], "vol": c.get("vol", 0)}
            for c in to_candles(df, 10 ** 6)]
    _long_cache[code] = (now, bars)
    return bars


def _wm_candles(code: str, tf: str) -> list:
    """주봉/월봉 120개 — 전체 구간에서 이동평균을 계산한 뒤 최근 120봉만 노출."""
    try:
        return _attach_ma(aggregate_daily(_long_daily_bars(code), tf))[-120:]
    except Exception:
        log.warning("주·월봉 조회 실패(%s %s)", code, tf, exc_info=True)
        return []


def _clip(bars: list, latest_t: str, earliest_t: str = "09:00:00") -> list:
    """조회 기준시각 이후로 찍힌 봉 제거 — 마지막 페이지가 장 시작 이전을 채우려고
    전일 잔재 행(미래 시각 라벨)을 되감아 반환한다(실측 2026-07-10)."""
    return [b for b in bars if earliest_t <= b["t"] <= latest_t]


async def _fetch_minutes(client: KisClient, code: str, div: str) -> list:
    """한 시장구분으로 당일 1분봉 전체 — 기준시각을 30분씩 당기며 조립."""
    earliest, cap = _session_window()
    bars, hour = [], min(kst.now().strftime("%H%M%S"), cap)
    latest_t = f"{hour[0:2]}:{hour[2:4]}:{hour[4:6]}"
    kdate = kst.today().strftime("%Y%m%d")  # 전일 봉 혼입 필터(간헐 실측)
    for _ in range(_MAX_CALLS):
        js = await client._get(_MIN_PATH, "FHKST03010200",
                               {"FID_ETC_CLS_CODE": "",
                                "FID_COND_MRKT_DIV_CODE": div,
                                "FID_INPUT_ISCD": code,
                                "FID_INPUT_HOUR_1": hour,
                                "FID_PW_DATA_INCU_YN": "Y"})
        chunk = parse_minute_candles(js, kdate)
        if not chunk:
            break
        bars = chunk + bars
        oldest = chunk[0]["t"]
        if oldest <= earliest or len(chunk) < 30:
            break
        hh, mm, _ = oldest.split(":")
        m = int(hh) * 60 + int(mm) - 1
        hour = f"{m // 60:02d}{m % 60:02d}00"
        await asyncio.sleep(_GAP)
    seen, out = set(), []
    for b in bars:  # 페이지 경계 중복 제거
        if b["t"] not in seen:
            seen.add(b["t"])
            out.append(b)
    out = _clip(out, latest_t, earliest)
    out.sort(key=lambda b: b["t"])
    return out


def _has_prices(bars: list) -> bool:
    """가격이 하나라도 실린 봉이 있나.

    NXT 미상장 종목을 통합(UN)으로 물으면 KIS는 **오류를 안 낸다** — rt_cd=0
    '정상처리'에 시각만 있고 가격·거래량이 전부 0인 행을 30개씩 준다
    (2026-08-10 실측, 411060 금현물 ETF: UN 0/30 vs J 30/30). 그래서 로그에도
    흔적이 안 남고 화면만 조용히 빈다. 값의 유무로 직접 판정할 수밖에 없다."""
    return any(b["close"] for b in bars)


async def _day_minutes(client: KisClient, code: str) -> list:
    """당일 1분봉 전체. 통합 조회가 빈 값이면 KRX 전용(J)으로 한 번 되묻는다."""
    now = time.time()
    hit = _min_cache.get(code)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    div = _krx_only.get(code, client.div)
    out = await _fetch_minutes(client, code, div)
    if not _has_prices(out) and div != "J":
        alt = await _fetch_minutes(client, code, "J")
        if _has_prices(alt):
            # 한 번 확인되면 기억한다 — 매 갱신마다 빈 UN 조회를 되풀이하지 않게
            _krx_only[code] = "J"
            log.info("%s 분봉: 통합(%s) 빈 값 → KRX 전용(J)로 전환", code, div)
            out = alt
    _min_cache[code] = (now, out)
    return out


def _demo_minutes(code: str) -> list:
    """데모: 시드 랜덤워크 당일 분봉(09:00~15:30, 391봉)."""
    rng = random.Random(int(code) if code.isdigit() else 42)
    price = float(lookup_stock(code)[1] or 100_000)
    bars = []
    for m in range(540, 931):  # 09:00 ~ 15:30
        o = price
        price = max(1.0, price * (1 + rng.uniform(-0.003, 0.003)))
        hi, lo = max(o, price) * (1 + rng.uniform(0, 0.001)), \
            min(o, price) * (1 - rng.uniform(0, 0.001))
        bars.append({"t": f"{m // 60:02d}:{m % 60:02d}:00",
                     "open": int(o), "high": int(hi), "low": int(lo),
                     "close": int(price), "vol": rng.randint(100, 20_000)})
    return bars


def _daily_candles(code: str) -> list:
    """일봉 120개 — 대시보드와 동일한 FDR 캐시 경로(키 불필요)."""
    now = time.time()
    hit = _daily_cache.get(code)
    if hit and now - hit[0] < 3600:  # 일봉은 하루 단위라 1시간 캐시
        return hit[1]
    try:
        from backend.adapters.cache import OHLCVCache
        from backend.adapters.prices import PriceAdapter
        from backend.report.dashboard import to_candles
        end = dt.date.today()
        start = end - dt.timedelta(days=400)   # 120봉 이동평균이 채워지도록 넉넉히
        df = PriceAdapter(OHLCVCache(settings.cache_dir)).get_ohlcv(
            code, start.isoformat(), end.isoformat())
        # 260봉으로 이동평균을 계산한 뒤 최근 120봉만 노출(선행 구간이 ma120을 채움)
        full = [{"t": c["time"], "open": c["open"], "high": c["high"],
                 "low": c["low"], "close": c["close"], "vol": c.get("vol", 0)}
                for c in to_candles(df, 260)]
        candles = _attach_ma(full)[-120:]
    except Exception:
        log.warning("일봉 조회 실패(%s)", code, exc_info=True)
        candles = []
    _daily_cache[code] = (now, candles)
    return candles


async def get_candles(code: str, tf: str) -> dict:
    # date: 분봉의 KST 기준일 — 프런트 시간축이 클라이언트 로컬 날짜/시계 없이
    # 서버 기준으로 epoch을 만들도록 항상 내려준다(P0-3).
    kdate = kst.today().isoformat()
    if tf == "1d":
        return {"tf": tf, "date": kdate,
                "candles": await asyncio.to_thread(_daily_candles, code)}
    if tf in ("1w", "1mo"):
        return {"tf": tf, "date": kdate,
                "candles": await asyncio.to_thread(_wm_candles, code, tf)}
    live = (settings.kis_app_key and settings.kis_app_secret
            and settings.flow_mode != "demo")
    if live:
        try:
            bars = await _day_minutes(_get_client(), code)
        except Exception:
            log.warning("분봉 조회 실패(%s) — 빈 결과", code, exc_info=True)
            bars = []
    else:
        bars = _demo_minutes(code)
    if tf == "5m":
        bars = aggregate(bars, 5)
    elif tf == "15m":
        bars = aggregate(bars, 15)
    elif tf == "60m":
        bars = aggregate(bars, 60)
    return {"tf": tf, "date": kdate, "candles": _attach_ma(bars)}
