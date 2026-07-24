from __future__ import annotations

"""공매도 일별 체결량 — KIS 국내주식 공매도일별추이 FHPST04830000.

원래 계획은 KRX 공매도통계(data.krx.co.kr)였으나 재검증(2026-07-13) 결과
KRX 정보데이터시스템·공매도종합포털(short.krx.co.kr) 모두 로그인 월(400 'LOGOUT',
302→로그인)이 유지 중 — KIS TR이 기간 조회 1콜로 일별 체결량·비중을 제공한다.

주의(실측):
- T+1 트랩: 장중엔 당일 행이 '누락'이 아니라 공매도 필드 0으로 내려온다 — 장중에는
  날짜가 오늘(KST)인 행을 잠정으로 보고 버린다.
- 다만 마감 후에는 당일 확정치가 채워진다(2026-07-23 증권사 화면 실측: 272,237주
  4.30%). 날짜만 보고 무조건 버리면 오늘 공매도는 다음 날 아침에야 뜬다 —
  _CLOSE_HM 이후에는 당일 행을 허용하고, 미공표(0)는 꼬리 0 제거가 걸러낸다.
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
_TTL_PENDING = 300.0  # 마감 후 당일 확정치 공표 대기 중 — 1시간이면 최대 1시간 늦다
_CLOSE_HM = "16:00"   # 이 시각(KST) 이후 당일 확정 공매도가 채워진다(실측)
_SCAN_DAYS = 45  # 달력일 기준 조회 폭(휴일 감안, 거래일 ~30일 확보)
_cache: dict = {}  # code -> (ts, data)


def parse_short_sale(js: dict, today_iso: str, allow_today: bool = False) -> list:
    """FHPST04830000 output2 → [{date,qty,vol,ratio,value,close}] 날짜 오름차순.

    미래 행은 항상, 당일 행은 allow_today=False(장중)일 때 제외한다. 허용해도
    미공표 당일 행(공매도 0)은 아래 꼬리 0 제거가 걸러낸다 — 기본값은 안전측."""
    if js.get("rt_cd") != "0":
        return []
    rows = []
    for r in js.get("output2") or []:
        d = str(r.get("stck_bsop_date", ""))
        if len(d) != 8:
            continue
        date = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        if date > today_iso or (date == today_iso and not allow_today):
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
    today = kst.today()
    today_iso = today.isoformat()
    # 마감 후 당일 확정치가 아직이면 짧은 TTL로 다시 두드린다(공표는 분 단위로 늦다).
    # 주말은 당일 행이 영원히 안 차므로 제외 — 5분마다 헛조회한다.
    allow_today = (kst.now().strftime("%H:%M") >= _CLOSE_HM
                   and today.weekday() < 5)
    hit = _cache.get(code)
    if hit:
        ttl = (_TTL_PENDING if allow_today and hit[1].get("asof") != today_iso
               else _TTL)
        if now - hit[0] < ttl:
            return hit[1]
    js = await client._get(_PATH, _TR,
                           {"FID_COND_MRKT_DIV_CODE": "J",
                            "FID_INPUT_ISCD": code,
                            "FID_INPUT_DATE_1":
                                (today - dt.timedelta(days=_SCAN_DAYS)).strftime("%Y%m%d"),
                            "FID_INPUT_DATE_2": today.strftime("%Y%m%d")})
    if js.get("rt_cd") != "0":
        # 소프트 오류(HTTP 200 + rt_cd≠0)를 빈 성공으로 캐시하지 않는다(리뷰 확정)
        raise RuntimeError(f"KIS {_TR} rt_cd={js.get('rt_cd')} {js.get('msg1', '')}")
    rows = parse_short_sale(js, today_iso, allow_today=allow_today)[-days:]
    data = {"rows": rows, "asof": rows[-1]["date"] if rows else None}
    _cache[code] = (now, data)
    return data
