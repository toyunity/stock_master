from __future__ import annotations

"""코스피200 옵션 지표 — 순수 함수만. 네트워크·KIS 미접촉.

행 리스트 하나를 받아 화면이 쓸 숫자까지만 낸다. 여기 있는 규칙 대부분은
2026-08-05 전 종목 실조회가 만든 것이다 — 자세한 근거는 스펙 §왜 초안을 버렸나.
Python 3.9 호환."""

import datetime as dt
from typing import List, Optional

from backend.flow import kst

WALL_PCT = 20.0        # 벽을 재는 범위. 화면에 "지수 ±20% 안에서"로 반드시 병기한다.
OPEN_MIN, CLOSE_MIN = 9 * 60, 15 * 60 + 45      # 옵션 정규장 09:00~15:45(KST)


def _f(v) -> float:
    try:
        return float(str(v).strip().replace(",", ""))
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _i(v) -> int:
    try:
        return int(float(str(v).strip().replace(",", "")))
    except (TypeError, ValueError, AttributeError):
        return 0


def parse_quote(js) -> Optional[dict]:
    """단건 시세(FHMIF10000000) 응답 → 지표용 행. 실패·빈 본문이면 None.

    **본문은 output이 아니라 output1이다**(output2=코스피, output3=코스피200).
    output만 읽으면 rt_cd=0에 빈 dict가 와서 '스로틀 걸렸나'로 오진하기 딱 좋다 —
    2026-08-05에 실제로 그렇게 30분을 날렸다."""
    if not isinstance(js, dict) or js.get("rt_cd") != "0":
        return None
    o = js.get("output1") or {}
    if not o:
        return None
    return {"strike": _f(o.get("acpr")),
            "price": _f(o.get("futs_prpr")),
            "vol": _i(o.get("acml_vol")),
            "oi": _i(o.get("hts_otst_stpl_qty")),
            "oi_chg": _i(o.get("otst_stpl_qty_icdc")),   # 음수가 정상값이다
            "iv": _f(o.get("hts_ints_vltl")),
            "delta": _f(o.get("delta_val")),
            "remain_days": _i(o.get("hts_rmnn_dynu"))}


def session_of(now: Optional[dt.datetime] = None) -> str:
    """'live'|'closed' — 코스피200 옵션 정규장은 평일 09:00~15:45(KST).

    선물(08:45~15:45)과 개장이 다르다. 야간옵션은 이 앱의 비목표(스펙 §목표)라
    다루지 않는다. 공휴일은 보지 않는다 — 휴장일엔 직전 수집값이 그대로 남는다."""
    now = now or kst.now()
    if now.weekday() >= 5:
        return "closed"
    hm = now.hour * 60 + now.minute
    return "live" if OPEN_MIN <= hm < CLOSE_MIN else "closed"


def month_label(expiry: str) -> str:
    """'202608' → '8월물'. 형식이 아니면 빈 문자열."""
    if not expiry or len(expiry) < 6 or not expiry[:6].isdigit():
        return ""
    return "%d월물" % int(expiry[4:6])


def put_call_ratio(calls, puts) -> Optional[float]:
    """풋 거래량 합 ÷ 콜 거래량 합. 분모가 0이면 None — 0으로 나눈 값을 지어내지 않는다."""
    c = sum((r.get("vol") or 0) for r in (calls or []))
    if c <= 0:
        return None
    return sum((r.get("vol") or 0) for r in (puts or [])) / c


def wall(rows, spot, pct) -> Optional[dict]:
    """지수 ±pct% 안에서 미결제(oi)가 가장 큰 행. **범위는 필수 인자 — 기본값이 없다.**

    전 구간으로 재면 사다리 양 끝이 잡힌다(실측: 콜 최고행사가 1,597.5가 콜 미결제의
    16.2%, 풋 최저행사가 625.0이 풋의 14.0%). 가격은 각각 0.04원·0.44원 — 복권 같은
    초저가와 폭락 보험이 경계에 쌓인 것이지 '시장이 보는 저항선·지지선'이 아니다.
    범위를 강제해 그 함정을 구조적으로 막는다(기본값을 주면 호출부가 잊는다)."""
    if not rows or not spot or pct is None:
        return None
    lo, hi = spot * (1 - pct / 100.0), spot * (1 + pct / 100.0)
    band = [r for r in rows
            if lo <= (r.get("strike") or 0) <= hi and (r.get("oi") or 0) > 0]
    if not band:
        return None
    return max(band, key=lambda r: r.get("oi") or 0)


def atm_iv(calls, puts, spot) -> Optional[dict]:
    """ATM 내재변동성 — **오늘 거래된**(vol>0) 행사가 중 spot에 가장 가까운 행.

    거래가 없는 행사가는 시세가 낡아 IV도 낡는다(실측: 거래된 행사가 80~92% vs
    거래 0인 행사가 51~61%로 두 층이 지그재그). 안 거르면 조용히 틀린 값이 나온다."""
    if not spot:
        return None
    live = [r for r in list(calls or []) + list(puts or [])
            if (r.get("vol") or 0) > 0 and (r.get("iv") or 0) > 0 and r.get("strike")]
    if not live:
        return None
    r = min(live, key=lambda x: abs(x["strike"] - spot))
    return {"iv": r["iv"], "strike": r["strike"], "vol": r["vol"]}


def top_changes(rows, n: int = 1) -> dict:
    """당일 증감 상위 → {'up': [...], 'down': [...]} 각각 |증감| 큰 순 n개.
    증감 0은 어느 쪽도 아니다(늘지도 줄지도 않은 자리를 '최대'라 부르지 않는다)."""
    rows = rows or []
    up = sorted([r for r in rows if (r.get("oi_chg") or 0) > 0],
                key=lambda r: r["oi_chg"], reverse=True)[:n]
    down = sorted([r for r in rows if (r.get("oi_chg") or 0) < 0],
                  key=lambda r: r["oi_chg"])[:n]
    return {"up": up, "down": down}


def histogram(rows, field: str) -> List[dict]:
    """차트용 (행사가, 값) 배열 — 행사가 오름차순. **값이 0인 칸도 남긴다** —
    막대 없는 자리가 '데이터 없음'이 아니라 '정말 0'임을 차트가 그대로 보여야 한다."""
    return [{"k": r["strike"], "v": r.get(field) or 0}
            for r in sorted(rows or [], key=lambda r: r.get("strike") or 0.0)
            if r.get("strike")]


def summarize(calls, puts, spot) -> dict:
    """보드 → 화면이 쓰는 요약 숫자. 순수.

    **콜 벽은 일부러 넣지 않는다.** 범위에 따라 1,050~1,250으로 흔들려(±5%~±30%
    실측) 우리가 범위를 고르는 순간 답의 일부를 우리가 정하게 된다. 차트에서 눈으로
    보게 두고 숫자로 단정하지 않는다. 풋 벽은 어느 범위에서도 1,000으로 같아서 낸다."""
    pw = wall(puts, spot, WALL_PCT)
    a = atm_iv(calls, puts, spot)
    tc, tp = top_changes(calls or []), top_changes(puts or [])
    return {"pcr": put_call_ratio(calls, puts),
            "put_wall": (pw or {}).get("strike"),
            "wall_pct": WALL_PCT,
            "atm_iv": (a or {}).get("iv"),
            "atm_strike": (a or {}).get("strike"),
            "call_chg_sum": sum((r.get("oi_chg") or 0) for r in (calls or [])),
            "put_chg_sum": sum((r.get("oi_chg") or 0) for r in (puts or [])),
            "top_call": (tc["up"] or [None])[0],
            "top_put": (tp["up"] or [None])[0]}
