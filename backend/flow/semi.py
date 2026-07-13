from __future__ import annotations

"""반도체 동향(메모리 중심) — 메인 대시보드 상단 섹션 데이터.

"간밤 미국 반도체(SOX·메모리)가 어땠고, 오늘 국내가 어떻게 반응하나"에 답한다.

소스(프로브 2026-07-13 실측 — 전부 KIS 네이티브):
- 미국 개별주: HHDFS00000300(EXCD=NAS). rate 필드에 선행 공백(strip 필수),
  sign '0'은 미국 프리오픈 일자 롤오버 상태(diff=0) — 보합 취급.
- SOX 지수: FHKST03030100(div=N, ISCD=SOX) output1.
- 국내: 기존 FHKST01010100(UN).
- 폴백(무키/실패): 네이버 월드스톡 polling API(sym.O) — 종목 단위 격리.
미국 장중 여부는 adr.us_market_open()(ET 시계) — 마감 시 '전일 종가 기준' 라벨.
"""

import asyncio
import logging
import time
from typing import Optional

from backend.config import settings
from backend.flow import adr, kst
from backend.flow.demo import lookup_stock
from backend.flow.kis import _SIGN, KisClient, _f, _i, parse_price

log = logging.getLogger(__name__)

_US_PATH = "/uapi/overseas-price/v1/quotations/price"
_IDX_PATH = "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
_TTL = 60.0
_GAP = 0.25  # 연속 호출 간헐 500 완화(실측 관례)
_cache: dict = {"ts": 0.0, "data": None}
_client = None
_lock: Optional[asyncio.Lock] = None  # 3.9 호환 — 루프 안에서 lazy 생성


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock

US_NAMES = {"SOX": "필라델피아 반도체지수", "NVDA": "엔비디아", "MU": "마이크론",
            "WDC": "웨스턴디지털", "SNDK": "샌디스크", "AMAT": "어플라이드 머티리얼즈",
            "LRCX": "램리서치", "KLAC": "KLA", "SKHYV": "SK하이닉스 DR",
            "SOXX": "SOXX ETF"}


def _get_client() -> KisClient:
    global _client
    if _client is None:
        _client = KisClient(settings.kis_app_key, settings.kis_app_secret,
                            settings.cache_dir, market_div=settings.market_div)
    return _client


def parse_us_quote(js: dict) -> Optional[dict]:
    """HHDFS00000300 → {last, base, rate, sign}. 미커버는 rt_cd=0+빈값 → None.

    rate 선행 공백 strip(실측). sign '0'은 프리오픈 일자 롤오버(diff=0, base==last)
    — 이때 0.00%를 보합으로 그리면 직전 세션 변동을 가리므로 rate=None(–)로 둔다
    (리뷰 확정). 진짜 보합은 sign '3'으로 온다."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output") or {}
    last = _f(str(o.get("last", "")).strip())
    if last <= 0:
        return None
    sign = str(o.get("sign", ""))
    rolled = sign == "0"
    return {"last": last, "base": _f(str(o.get("base", "")).strip()) or None,
            "rate": None if rolled else _f(str(o.get("rate", "")).strip()),
            "sign": "flat" if rolled else _SIGN.get(sign, "flat")}


def parse_sox(js: dict) -> Optional[dict]:
    """FHKST03030100(N, SOX) output1 → {last, rate, sign}."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output1") or {}
    last = _f(o.get("ovrs_nmix_prpr"))
    if last <= 0:
        return None
    return {"last": last, "base": _f(o.get("ovrs_nmix_prdy_clpr")) or None,
            "rate": _f(o.get("prdy_ctrt")),
            "sign": _SIGN.get(str(o.get("prdy_vrss_sign", "")), "flat")}


async def _us_quote(client, sym: str) -> Optional[dict]:
    if sym == "SOX":
        day = kst.today().strftime("%Y%m%d")
        js = await client._get(_IDX_PATH, "FHKST03030100",
                               {"FID_COND_MRKT_DIV_CODE": "N",
                                "FID_INPUT_ISCD": "SOX",
                                "FID_INPUT_DATE_1": day, "FID_INPUT_DATE_2": day,
                                "FID_PERIOD_DIV_CODE": "D"})
        return parse_sox(js)
    js = await client._get(_US_PATH, "HHDFS00000300",
                           {"AUTH": "", "EXCD": "NAS", "SYMB": sym})
    return parse_us_quote(js)


async def _us_quote_naver(sym: str) -> Optional[dict]:
    """무키 폴백 — 지수(SOX)는 미지원, 개별주만."""
    if sym == "SOX":
        return None
    d = adr.parse_naver_world(await adr._naver_json(
        adr._NAVER_WORLD.format(sym=sym)))
    if not d:
        return None
    base = d.get("base")
    rate = (d["last"] - base) / base * 100 if base else 0.0
    return {"last": d["last"], "base": base, "rate": round(rate, 2),
            "sign": "up" if rate > 0 else ("down" if rate < 0 else "flat")}


async def get_overview() -> dict:
    """미국+국내 반도체 시세 스냅샷 — 60초 캐시, 종목 단위 실패 격리(카드 '–').

    락 + 완료 시점 ts(리뷰 확정): 캐시 시각을 페치 시작으로 찍으면 루프 소요만큼
    TTL이 깎여 60초 폴링이 매번 콜드 미스가 되고, 락이 없으면 아이폰+맥 동시
    접속이 같은 KIS 키로 11콜 스윕을 겹쳐 돌린다."""
    if _cache["data"] is not None and time.time() - _cache["ts"] < _TTL:
        return _cache["data"]
    async with _get_lock():
        if _cache["data"] is not None and time.time() - _cache["ts"] < _TTL:
            return _cache["data"]  # 갱신 대기 중이던 요청은 방금 채워진 캐시 사용
        demo = settings.flow_mode == "demo"
        live = bool(settings.kis_app_key and settings.kis_app_secret and not demo)
        client = _get_client() if live else None

        us = []
        for i, sym in enumerate(settings.semi_us):
            if i:
                await asyncio.sleep(_GAP)
            q = None
            if client is not None:
                try:
                    q = await _us_quote(client, sym)
                except Exception:
                    log.warning("미국 시세 %s KIS 실패 — 네이버 폴백", sym,
                                exc_info=True)
            if q is None and not demo:  # 데모는 오프라인 유지(외부 I/O 금지)
                try:
                    q = await _us_quote_naver(sym)
                except Exception:
                    log.warning("미국 시세 %s 네이버 실패", sym, exc_info=True)
            us.append(dict(q or {}, sym=sym, name=US_NAMES.get(sym, sym),
                           ok=q is not None))

        kr = []
        for code in settings.semi_kr:
            await asyncio.sleep(_GAP)
            name, close = lookup_stock(code)
            row = {"code": code, "name": name, "ok": False}
            if client is not None:
                try:
                    p = await client.price(code)
                    if p:
                        row.update(price=p["price"], rate=p["rate"],
                                   sign=p["sign"], ok=True)
                except Exception:
                    log.warning("국내 시세 %s 실패", code, exc_info=True)
            if not row["ok"] and close:  # 무키/실패 — 유니버스 캐시 종가(전일)
                row.update(price=close, rate=None, sign="flat", ok=True,
                           stale=True)
            kr.append(row)

        data = {"us": us, "kr": kr,
                "us_open": adr.us_market_open(),
                "asof": kst.now().strftime("%H:%M:%S"),
                "kst_date": kst.today().isoformat()}
        _cache.update(ts=time.time(), data=data)  # 완료 시점 기준(TTL 온전)
        return data
