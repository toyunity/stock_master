from __future__ import annotations

"""공매도 일별 체결량 — KIS 국내주식 공매도일별추이 FHPST04830000.

원래 계획은 KRX 공매도통계(data.krx.co.kr)였으나 재검증(2026-07-13) 결과
KRX 정보데이터시스템·공매도종합포털(short.krx.co.kr) 모두 로그인 월(400 'LOGOUT',
302→로그인)이 유지 중 — KIS TR이 기간 조회 1콜로 일별 체결량·비중을 제공한다.

주의(실측):
- T+1 트랩: 당일 행이 '누락'이 아니라 공매도 필드 0으로 내려온다 — 날짜가 오늘(KST)인
  행은 잠정으로 보고 버린다(확정 최신 = 직전 거래일).
- ssts_vol_rlim(비중 %)은 서버 계산값(체결량/거래량 일치 검증됨) 그대로 사용.
- acml_ssts_*/stnd_* 필드는 조회 구간 누적치라 일별 시계열에 쓰면 안 된다.
"""

import datetime as dt
import logging
import time

from backend.flow import kst
from backend.flow.kis import _f, _i

log = logging.getLogger(__name__)

_PATH = "/uapi/domestic-stock/v1/quotations/daily-short-sale"
_TR = "FHPST04830000"
_TTL = 3600.0    # T+1 확정치 — 1시간 캐시로 충분
_SCAN_DAYS = 45  # 달력일 기준 조회 폭(휴일 감안, 거래일 ~30일 확보)
_cache: dict = {}  # code -> (ts, data)


def parse_short_sale(js: dict, today_iso: str) -> list:
    """FHPST04830000 output2 → [{date,qty,vol,ratio,value,close}] 날짜 오름차순.

    date >= today(KST)인 행은 T+1 미확정(공매도 필드 0) — 제외한다."""
    if js.get("rt_cd") != "0":
        return []
    rows = []
    for r in js.get("output2") or []:
        d = str(r.get("stck_bsop_date", ""))
        if len(d) != 8:
            continue
        date = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        if date >= today_iso:
            continue
        rows.append({"date": date,
                     "qty": _i(r.get("ssts_cntg_qty")),
                     "vol": _i(r.get("acml_vol")),
                     "ratio": _f(r.get("ssts_vol_rlim")),
                     "value": _i(r.get("ssts_tr_pbmn")),
                     "close": _i(r.get("stck_clpr"))})
    rows.sort(key=lambda r: r["date"])
    # 미공시 잠정 행은 날짜가 오늘이 아닐 수도 있다(주말·자정~발표 전의 직전
    # 거래일 행이 0으로 잔존, 리뷰 확정) — 꼬리의 0행은 '확정 0주'로 오인되므로
    # 제거한다. 중간의 0행(진짜 공매도 없던 날)은 보존.
    while rows and rows[-1]["qty"] == 0:
        rows.pop()
    return rows


async def get_history(client, code: str, days: int = 20) -> dict:
    """최근 N거래일 공매도 체결 — 기간 조회 1콜, 1시간 메모리 캐시.

    반환 {rows, asof}. 실패는 예외로 위임(엔진이 격리 처리)."""
    now = time.time()
    hit = _cache.get(code)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    today = kst.today()
    js = await client._get(_PATH, _TR,
                           {"FID_COND_MRKT_DIV_CODE": "J",
                            "FID_INPUT_ISCD": code,
                            "FID_INPUT_DATE_1":
                                (today - dt.timedelta(days=_SCAN_DAYS)).strftime("%Y%m%d"),
                            "FID_INPUT_DATE_2": today.strftime("%Y%m%d")})
    if js.get("rt_cd") != "0":
        # 소프트 오류(HTTP 200 + rt_cd≠0)를 빈 성공으로 캐시하지 않는다(리뷰 확정)
        raise RuntimeError(f"KIS {_TR} rt_cd={js.get('rt_cd')} {js.get('msg1', '')}")
    rows = parse_short_sale(js, today.isoformat())[-days:]
    data = {"rows": rows, "asof": rows[-1]["date"] if rows else None}
    _cache[code] = (now, data)
    return data
