from __future__ import annotations

"""ADR/DR 환산가·괴리율 — SK하이닉스 나스닥 DR(SKHY, 실거래 티커) 대응.

소스(실측 프로브 2026-07-13):
- 1차 KIS 해외주식 현재가상세 HHDFS76200200(EXCD=NAS) — 기존 국내 키로 동작.
  미커버 심볼은 rt_cd=0인데 output 필드가 전부 빈 문자열(무증상 실패) → 빈값 검사 필수.
  응답에 체결 시각이 없어 '전일 종가 기준' 라벨은 미국 정규장 시계(America/New_York,
  09:30~16:00)로 판정한다. 미국 휴장일은 달력이 없어 '장중'으로 보일 수 있으나
  가격은 마지막 체결가라 값 자체는 옳다.
- 폴백(무키) 네이버 월드스톡 polling.finance.naver.com — marketStatus·localTradedAt 제공,
  안내 폴링 간격 70초(우리 폴링은 60초 TTL이라 사실상 준수).
- 환율 1차 KIS FHKST03030100(시장구분 X, FX@KRW) output1.ovrs_nmix_prpr — 장중 실시간.
  폴백 네이버 marketIndex(하나은행 고시가; cashBuy/cashSell은 현찰 환율이라 쓰지 않는다).
※ 야후 파이낸스는 이 환경에서 IP 단위 429 확인 — 사용 금지. 구 OTC 'HXSCL'은
  2014년 이후 거래 없음 — SKHY만 사용(SKHYV는 상장일 값에 얼어붙은 스테일 — 금지).
"""

import datetime as dt
import logging
import time
from typing import Optional
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.flow import kst
from backend.flow.kis import _f

log = logging.getLogger(__name__)

_DETAIL_PATH = "/uapi/overseas-price/v1/quotations/price-detail"
_FX_PATH = "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
_NAVER_WORLD = "https://polling.finance.naver.com/api/realtime/worldstock/stock/{sym}.O"
_NAVER_FX = ("https://m.stock.naver.com/front-api/marketIndex/productDetail"
             "?category=exchange&reutersCode=FX_USDKRW")
_UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/126.0.0.0 Safari/537.36")}

_TTL = 60.0
_cache: dict = {}  # code -> (ts, dict|None) — 실패도 캐시해 원격 재시도를 TTL로 제한

_ET = ZoneInfo("America/New_York")


# ── 순수 파서/계산 (픽스처만으로 테스트) ──────────────────────

def parse_overseas_detail(js: dict) -> Optional[dict]:
    """HHDFS76200200 → {last(현재/최근 체결가 USD), base(전일 종가 USD|None)}."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output") or {}
    last = _f(o.get("last"))
    if last <= 0:  # 미커버 심볼: rt_cd=0 + 빈 문자열(실측)
        return None
    base = _f(o.get("base"))
    return {"last": last, "base": base if base > 0 else None}


def parse_fx_chart(js: dict) -> Optional[float]:
    """FHKST03030100(X, FX@KRW) → 현재 USD/KRW. 4자리 소수 문자열(실측)."""
    if js.get("rt_cd") != "0":
        return None
    v = _f((js.get("output1") or {}).get("ovrs_nmix_prpr"))
    return v if v > 0 else None


def parse_naver_world(js: dict) -> Optional[dict]:
    """polling.finance.naver.com 월드스톡 → {last, base, market_status,
    (정규장 마감 후 시간외가 있으면) over_price, over_status, over_session}.

    KIS HHDFS76200200에는 애프터장 필드가 없어(last=정규장 종가), 시간외 체결가는
    네이버 overMarketPriceInfo.overPrice로만 확보된다(2026-07-15 프로브 실측)."""
    rows = js.get("datas") if isinstance(js.get("datas"), list) else [js]
    for r in rows or []:
        last = _f(str(r.get("closePrice", "")).replace(",", ""))
        if last <= 0:
            continue
        chg = _f(str(r.get("compareToPreviousClosePrice", "")).replace(",", ""))
        out = {"last": last, "base": (last - chg) if chg else None,
               "market_status": r.get("marketStatus")}
        om = r.get("overMarketPriceInfo") or {}
        over = _f(str(om.get("overPrice", "")).replace(",", ""))
        if over > 0:  # 애프터/프리마켓 체결가(정규장 종가와 별개)
            out["over_price"] = over
            out["over_status"] = om.get("overMarketStatus")      # OPEN(진행)/CLOSE(마감)
            out["over_session"] = om.get("tradingSessionType")   # AFTER_MARKET/PRE_MARKET
        return out
    return None


def parse_naver_fx(js: dict) -> Optional[float]:
    v = _f(str((js.get("result") or {}).get("closePrice", "")).replace(",", ""))
    return v if v > 0 else None


def us_market_open(now_et: Optional[dt.datetime] = None) -> bool:
    """미국 정규장(09:30~16:00 ET) 여부 — DST는 zoneinfo가 처리."""
    n = now_et or dt.datetime.now(_ET)
    if n.weekday() >= 5:
        return False
    hm = n.strftime("%H:%M")
    return "09:30" <= hm < "16:00"


# ── 원격 조회 (엔진에서만 호출; 테스트는 monkeypatch) ──────────

async def _naver_json(url: str) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=10) as cli:
        r = await cli.get(url, headers=_UA)
        r.raise_for_status()
        return r.json()


async def get_quote(client, code: str) -> Optional[dict]:
    """DR 시세+환율 스냅샷 — 60초 TTL, DR 미상장 종목이나 총실패면 None.

    환산가·괴리율 계산은 FlowState 스냅샷에서(원주 현재가가 틱마다 변하므로)."""
    sym = settings.adr_map.get(code)
    if not sym:
        return None
    now = time.time()
    hit = _cache.get(code)
    if hit and now - hit[0] < _TTL:
        return hit[1]

    reg_open = us_market_open()
    quote, src = None, "kis"
    try:
        js = await client._get(_DETAIL_PATH, "HHDFS76200200",
                               {"AUTH": "", "EXCD": "NAS", "SYMB": sym})
        quote = parse_overseas_detail(js)   # 정규장 last/base(시간외 미포함)
    except Exception:
        log.warning("KIS 해외시세(%s) 실패 — 네이버 폴백", sym, exc_info=True)

    # KIS 실패거나 미국 정규장 마감이면 네이버 조회 — 시간외(애프터/프리마켓) 가격 확보.
    # 정규장 중엔 KIS last가 실시간이라 네이버를 건너뛴다(호출 절약).
    naver = None
    if quote is None or not reg_open:
        try:
            naver = parse_naver_world(await _naver_json(_NAVER_WORLD.format(sym=sym)))
        except Exception:
            log.warning("네이버 월드스톡(%s) 실패", sym, exc_info=True)
    if quote is None and naver:               # KIS 실패 → 네이버 정규장 종가로 폴백
        quote, src = {"last": naver["last"], "base": naver.get("base")}, "naver"

    session = "regular" if reg_open else "closed"
    # 정규장 마감 후 네이버 시간외 체결가가 있으면 그걸 우선 반영(사용자 요청: 애프터장 가격).
    # base는 정규장 종가로 둬서 괴리율/환산은 시간외가 기준으로 계산된다.
    if not reg_open and naver and naver.get("over_price"):
        quote = {"last": naver["over_price"], "base": naver.get("last")}
        session = "pre" if naver.get("over_session") == "PRE_MARKET" else "after"
        src = "naver-ext"

    fx = None
    try:
        day = kst.today().strftime("%Y%m%d")
        js = await client._get(_FX_PATH, "FHKST03030100",
                               {"FID_COND_MRKT_DIV_CODE": "X",
                                "FID_INPUT_ISCD": "FX@KRW",
                                "FID_INPUT_DATE_1": day, "FID_INPUT_DATE_2": day,
                                "FID_PERIOD_DIV_CODE": "D"})
        fx = parse_fx_chart(js)
    except Exception:
        log.warning("KIS 환율 실패 — 네이버 폴백", exc_info=True)
    if fx is None:
        try:
            fx = parse_naver_fx(await _naver_json(_NAVER_FX))
        except Exception:
            log.warning("네이버 환율 실패", exc_info=True)

    result = None
    if quote and fx:
        result = {"sym": sym, "usd": quote["last"], "base_usd": quote.get("base"),
                  "fx": fx, "ratio": settings.adr_ratio,
                  "us_open": reg_open, "session": session, "src": src,
                  "fetched": kst.now().strftime("%H:%M:%S")}
    _cache[code] = (now, result)
    return result
