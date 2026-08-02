from __future__ import annotations

"""지수 선물 순수 파서 + 세션 판정 — 네트워크·KIS 미접촉.

선물은 주식과 여는 시간이 다르고(주간 08:45~15:45 / 야간 18:00~익일 06:00) 월물이
롤오버되므로, "지금 어느 세션인가"와 "어느 월물인가"를 여기서만 판단한다.
kis.py에 넣지 않은 이유: kis가 이 모듈의 파서를 부르므로 반대 임포트는 순환이 된다.
Python 3.9 호환."""

import datetime as dt
import re
from typing import Optional

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


# ffcode.mst 고정폭 레이아웃 — KIS 공개 헤더(해외선물정보.h) 기준:
# 종목코드 32 + 자동주문플래그 3 + 필러 47 = 82부터 시리즈명 50
_FF_CODE, _FF_NAME = slice(0, 32), slice(82, 132)
_NQ_PREFIX = "E-mini Nasdaq100-"
_EXPIRY_RE = re.compile(r"-(\d{6})$")


def parse_ff_master(text: str) -> list:
    """해외선물 종목마스터(ffcode.mst) 원문 → [{'code','name'}]."""
    out = []
    for row in text.splitlines():
        if len(row) < _FF_NAME.stop:
            continue
        code, name = row[_FF_CODE].strip(), row[_FF_NAME].strip()
        if code and name:
            out.append({"code": code, "name": name})
    return out


def pick_nq_series(rows: list, now: Optional[dt.datetime] = None) -> Optional[str]:
    """나스닥 E-mini 최근월물 SRS_CD.

    만기는 시리즈명 접미사('-YYYYMM')에서 읽는다. 코드 접두로 고르면 안 된다 —
    MND*는 나스닥이 아니라 MSCI Indonesia다(2026-07-31 마스터 실측).
    마이크로(Micro E-mini)와 스프레드(코드에 '-')는 제외한다."""
    now = now or kst.now()
    ym = now.strftime("%Y%m")
    best = None
    for r in rows:
        if "-" in r["code"] or not r["name"].startswith(_NQ_PREFIX):
            continue
        m = _EXPIRY_RE.search(r["name"])
        if not m or m.group(1) < ym:
            continue
        if best is None or m.group(1) < best[0]:
            best = (m.group(1), r["code"])
    return best[1] if best else None


# 해외선물 현재가 응답 키 — G3 실측에서 확인되는 대로 하나로 좁힌다.
_OVS_PRICE_KEYS = ("last", "ovrs_prpr", "prpr", "futs_prpr")
_OVS_RATE_KEYS = ("prdy_ctrt", "prdy_rate", "rate")


def _first(d: dict, keys) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def parse_overseas(js: dict) -> Optional[dict]:
    """해외선물 현재가(HHDFC55010000) → {price, rate}. 실패/빈 응답이면 None."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output1") or js.get("output") or js.get("output2") or {}
    px = _first(o, _OVS_PRICE_KEYS)
    if px is None:
        return None
    return {"price": _f(px), "rate": _f(_first(o, _OVS_RATE_KEYS) or 0)}
