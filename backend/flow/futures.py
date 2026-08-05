from __future__ import annotations

"""지수 선물 순수 파서 + 세션 판정 — 네트워크·KIS 미접촉.

선물은 주식과 여는 시간이 다르고(주간 08:45~15:45 / 야간 18:00~익일 06:00) 월물이
롤오버되므로, "지금 어느 세션인가"와 "어느 월물인가"를 여기서만 판단한다.
kis.py에 넣지 않은 이유: kis가 이 모듈의 파서를 부르므로 반대 임포트는 순환이 된다.
Python 3.9 호환."""

import datetime as dt
import math
from typing import Optional, Tuple

from backend.flow import kst

DAY_OPEN, DAY_CLOSE = 8 * 60 + 45, 15 * 60 + 45      # 08:45 / 15:45
NIGHT_OPEN, NIGHT_CLOSE = 18 * 60, 6 * 60            # 18:00 / 익일 06:00
BOARD_CLS = ""       # 전광판 시장구분 — ""=정규(대형) 코스피200 선물
                     # (2026-07-31 장중 실측: A01609 F 202609). "MKI"는 미니.

_SIGN = {"1": "up", "2": "up", "3": "flat", "4": "down", "5": "down"}


def _f(v) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


def _i(v) -> int:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def session_of(now: Optional[dt.datetime] = None) -> str:
    """'day'|'gap'|'night'|'closed' — KST 벽시계 기준.

    공휴일은 보지 않는다(휴장일엔 마지막 성공값이 '마감'으로 남는다 — 지수 칩과 같은 관행)."""
    now = now or kst.now()
    hm, wd = now.hour * 60 + now.minute, now.weekday()   # 월=0 … 일=6
    if hm < NIGHT_CLOSE:              # 00:00~05:59 = 전날 18:00에 열린 야간장의 연장
        return "night" if 1 <= wd <= 5 else "closed"     # 화~토 새벽 = 월~금 야간
    if wd >= 5:                       # 토·일 06:00 이후는 전부 휴장
        return "closed"
    if hm < DAY_OPEN:                 # 06:00~08:44
        return "closed"
    if hm < DAY_CLOSE:                # 08:45~15:44
        return "day"
    if hm < NIGHT_OPEN:               # 15:45~17:59
        return "gap"
    return "night"                    # 18:00~23:59


def parse_board(js: dict) -> list:
    """display-board-futures(FHPIF05030200) → 월물 행 리스트.

    한 콜에 목록+시세가 같이 온다(2026-07-19 라이브 실측) → 개별 inquire-price 불필요."""
    if js.get("rt_cd") != "0":
        return []
    rows = js.get("output") or js.get("output1") or js.get("output2") or []
    out = []
    for r in rows:
        code = (r.get("futs_shrn_iscd") or "").strip()
        if not code:
            continue
        out.append({"code": code,
                    "name": (r.get("hts_kor_isnm") or "").strip(),
                    "price": _f(r.get("futs_prpr")),
                    "rate": _f(r.get("futs_prdy_ctrt")),
                    "sign": _SIGN.get(str(r.get("prdy_vrss_sign", "")), ""),
                    "volume": _i(r.get("acml_vol"))})
    return out


def pick_front_month(rows: list) -> Optional[dict]:
    """최근월물 = 거래량 최다 행. 만기가 다가오면 거래가 다음 월물로 옮겨가므로
    코드를 하드코딩하지 않고 매번 여기서 다시 고른다(롤오버 자동 대응)."""
    live = [r for r in rows if r.get("price")]
    if not live:
        return None
    return max(live, key=lambda r: r.get("volume", 0))


# H0MFCNT0(KRX 야간선물 실시간체결) 레코드 인덱스 — KIS 공식 예제의 COLUMN_MAPPING 순서.
# 주식 H0STCNT0과 순서가 다르므로 kis.parse_ccnl을 재사용하면 안 된다(가격도 소수다 —
# 정수 파서로 읽으면 883.40이 883으로 잘린다).
_NGT_CHANGE, _NGT_SIGN, _NGT_RATE, _NGT_PRICE = 2, 3, 4, 5
_NGT_VOL, _NGT_OI = 10, 18


def parse_ngt_ccnl(rec: list) -> Optional[dict]:
    """야간선물 실시간체결 레코드 → {price, rate, change, sign, acml_vol, oi}.
    필드가 모자란 레코드(핑퐁·잘린 프레임)는 None — 호출부가 조용히 무시한다."""
    if not rec or len(rec) <= _NGT_OI:
        return None
    return {"price": _f(rec[_NGT_PRICE]),
            "rate": _f(rec[_NGT_RATE]),
            "change": _f(rec[_NGT_CHANGE]),
            "sign": _SIGN.get(str(rec[_NGT_SIGN]), ""),
            "acml_vol": _i(rec[_NGT_VOL]),
            "oi": _i(rec[_NGT_OI])}


def pick_latest_pair(closes) -> Tuple[Optional[float], Optional[float]]:
    """종가 시퀀스(과거→현재, 항목은 None/NaN일 수 있음) → (현재가, 직전 유효종가).

    FinanceDataReader(NQ=F)는 거래일인데도 통째로 NaN인 행을 실제로 내보낸다(휴장이
    아니라 결측) — 그 행을 건너뛰고 유효값만 골라 마지막 두 개를 취한다. 숫자로 변환
    가능한 값(문자열 포함)이면 받아들이고, None·NaN·변환 불가 값은 결측으로 취급한다.

    현재가가 없으면 (None, None) — 호출부가 칩 자체를 생략한다. 현재가는 있는데 그
    직전 유효값이 없으면 (price, None) — 등락률을 0.00%로 꾸며내지 말고 rate:None으로
    넘기라는 신호다(dashboard.py의 fxchip()이 이미 None을 대시로 표시한다)."""
    valid = []
    for c in closes:
        if c is None:
            continue
        try:
            v = float(c)
        except (TypeError, ValueError):
            continue
        if math.isnan(v):
            continue
        valid.append(v)
    if not valid:
        return None, None
    if len(valid) == 1:
        return valid[0], None
    return valid[-1], valid[-2]
