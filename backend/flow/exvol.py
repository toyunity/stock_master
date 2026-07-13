from __future__ import annotations

"""거래소별(KRX/NXT) 거래량 분리 + 세션별 집계 — NXT 시간외 유동성 판정용.

실측(프로브 2026-07-13, 장후 검증):
- FHKST01010100(현재가)을 div J/NX로 각각 조회하면 거래소별 누적이 분리된다.
  J+NX ≈ UN(초 단위 시차 오차뿐). 15:30 이후 J는 동결 → J의 현재가가
  '정규장 종가' 기준점(응답에 당일 정규 종가 필드는 미지원 — stck_sdpr은 전일 기준가).
- 세션별 NXT 누적은 FHPST01060000(당일시간대별체결, div NX)의 경계 시각 조회로
  도출: 08:59:59 시점 acml_vol = 장전(08:00~08:50) 총량, 15:29:59 시점 = 장전+본장.
  경계가 지난 뒤에는 값이 불변이라 하루 단위 캐시.
- 세션별 거래량을 직접 주는 TR은 미지원(공식 레지스트리 전수 확인).
"""

import logging
import time
from typing import Optional

from backend.flow import kst
from backend.flow.kis import _i

log = logging.getLogger(__name__)

_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
_TIME_CCNL_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-itemconclusion"
_TTL = 60.0
_cache: dict = {}       # code -> (ts, data)
_boundary: dict = {}    # (code, date, hour) -> acml_vol — 경계 통과 후 불변


def parse_vol(js: dict) -> Optional[dict]:
    """FHKST01010100 → {price, vol, pbmn}. rt_cd≠0이면 None."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output") or {}
    return {"price": _i(o.get("stck_prpr")), "vol": _i(o.get("acml_vol")),
            "pbmn": _i(o.get("acml_tr_pbmn"))}


def parse_time_acml(js: dict) -> Optional[int]:
    """FHPST01060000 output2 첫 행(조회 시각 이하 최신 틱)의 누적 거래량.

    ⚠ 체결량 필드명은 cnqn — 여기서는 acml_vol(누적)만 쓴다.
    rt_cd=0인데 행이 없으면 '그 시각까지 체결 0건' = 0 (리뷰 확정: None으로 두면
    한산한 종목의 장전 0거래일에 본장 집계가 하루 종일 막힌다). NX는 전일
    랩어라운드가 없음을 실측으로 확인(J와 다름)."""
    if js.get("rt_cd") != "0":
        return None
    rows = js.get("output2") or []
    if not rows:
        return 0
    return _i(rows[0].get("acml_vol"))


def distortion(nxt_after_price: Optional[int], krx_close: Optional[int],
               after_vol: Optional[int], total_vol: Optional[int]) -> Optional[dict]:
    """시간외 가격 변동 대비 거래량 판정 — 얇은 시장의 가격 왜곡 경고(스펙).

    |시간외 등락| ≥ 1% 인데 장후 거래량이 당일 총량의 1% 미만이면 경고."""
    if not nxt_after_price or not krx_close or total_vol is None or after_vol is None:
        return None
    move = (nxt_after_price - krx_close) / krx_close * 100
    share = after_vol / total_vol * 100 if total_vol else 0.0
    d = {"move_pct": round(move, 2), "after_share_pct": round(share, 2)}
    if abs(move) >= 1.0 and share < 1.0:
        return dict(d, text="유동성 부족 — 가격 왜곡 가능성(표본 극소)", tone="warn")
    if abs(move) >= 1.0:
        return dict(d, text="시간외 유의미한 변동 — 거래량 동반", tone="info")
    return dict(d, text="시간외 변동 미미", tone="flat")


async def _price(client, code: str, div: str) -> Optional[dict]:
    js = await client._get(_PRICE_PATH, "FHKST01010100",
                           {"FID_COND_MRKT_DIV_CODE": div, "FID_INPUT_ISCD": code})
    return parse_vol(js)


async def _acml_at(client, code: str, hhmmss: str) -> Optional[int]:
    """오늘 NXT 누적 거래량 @ 경계 시각 — 통과한 경계는 하루 캐시(불변)."""
    key = (code, kst.today().isoformat(), hhmmss)
    if key in _boundary:
        return _boundary[key]
    js = await client._get(_TIME_CCNL_PATH, "FHPST01060000",
                           {"FID_COND_MRKT_DIV_CODE": "NX",
                            "FID_INPUT_ISCD": code,
                            "FID_INPUT_HOUR_1": hhmmss})
    v = parse_time_acml(js)
    if v is not None:
        _boundary[key] = v
    return v


async def get_split(client, code: str) -> dict:
    """거래소·세션별 거래량 스냅샷 — 60초 TTL.

    반환 {krx:{price,vol,pbmn}, nxt:{...}, nxt_share_pct,
          sessions:{pre,main,after}(NXT, 미집계=None), warn, asof}."""
    now = time.time()
    hit = _cache.get(code)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    krx = await _price(client, code, "J")
    nxt = await _price(client, code, "NX")
    if krx is None or nxt is None:
        # 소프트 오류(HTTP 200 + rt_cd≠0)를 캐시하면: 반쪽 데이터가 정상 스냅샷을
        # 덮어 패널이 60초+ 비고, NXT 비중이 100%로 계산된다(리뷰 확정).
        # 예외로 위임 — 엔진이 격리하고 이전 패널을 유지한다.
        raise RuntimeError(f"KIS FHKST01010100 소프트 오류 (J={krx is not None}, "
                           f"NX={nxt is not None})")
    hm = kst.now().strftime("%H:%M:%S")
    pre = main = after = None
    # 지난 경계만 조회(진행 중 세션은 '진행 중' 표시용 None 유지)
    if hm >= "09:00:00":
        pre = await _acml_at(client, code, "085959")
    if hm >= "15:30:00":
        upto = await _acml_at(client, code, "152959")
        if upto is not None and pre is not None:
            main = upto - pre
        if upto is not None:
            after = nxt["vol"] - upto
    elif hm >= "09:00:00" and pre is not None:
        main = nxt["vol"] - pre  # 본장 진행 중 — 현재까지
    total = krx["vol"] + nxt["vol"]
    data = {
        "krx": krx, "nxt": nxt,
        "nxt_share_pct": round(nxt["vol"] / total * 100, 1) if total else None,
        "sessions": {"pre": pre, "main": main, "after": after},
        "warn": distortion(nxt["price"], krx["price"],
                           after, total or None) if hm >= "15:30:00" else None,
        "asof": kst.now().strftime("%H:%M:%S"),
    }
    _cache[code] = (now, data)
    return data
