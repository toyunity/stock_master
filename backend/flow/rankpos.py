from __future__ import annotations

"""시장 순위 속 종목 위치 — 공매도 상위(FHPST04820000)·신용잔고 상위(FHKST17010000).

마스터 결정(2026-09-08): 스캐너 탭이 아니라 **종목 상세**에서 "이 종목이 시장 순위 어디에
있나"로 보여준다. 목록은 시장 전체라 종목과 무관하게 1시간 캐시를 공유한다(2콜/시간).

실측(2026-09-08): 공매도 상위는 output(30행, ssts_vol_rlim 내림차순, stnd_date1이 기준일 —
일부 행은 '0'), 신용잔고 상위는 output2(100행, whol_loan_rmnd_rate 내림차순)."""

import logging
import time

from backend.flow.kis import _f

log = logging.getLogger(__name__)

_SHORT = ("/uapi/domestic-stock/v1/ranking/short-sale", "FHPST04820000",
          {"FID_APLY_RANG_VOL": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20482",
           "FID_INPUT_ISCD": "0000", "FID_PERIOD_DIV_CODE": "D", "FID_INPUT_CNT_1": "0",
           "FID_TRGT_EXLS_CLS_CODE": "", "FID_TRGT_CLS_CODE": "", "FID_APLY_RANG_PRC_1": "0",
           "FID_APLY_RANG_PRC_2": "1000000"})
_CREDIT = ("/uapi/domestic-stock/v1/ranking/credit-balance", "FHKST17010000",
           {"FID_COND_SCR_DIV_CODE": "11701", "FID_INPUT_ISCD": "0000", "FID_OPTION": "2",
            "FID_COND_MRKT_DIV_CODE": "J", "FID_RANK_SORT_CLS_CODE": "0"})
_TTL = 3600.0
_cache: dict = {}   # 'short'|'credit' -> (ts, rows, asof)


def _d8(s):
    s = str(s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def parse_short_rank(js) -> list:
    if not isinstance(js, dict) or js.get("rt_cd") != "0":
        return []
    return [{"code": str(r.get("mksc_shrn_iscd") or "").strip(),
             "name": str(r.get("hts_kor_isnm") or "").strip(),
             "ratio": _f(r.get("ssts_vol_rlim"))} for r in js.get("output") or []]


def parse_credit_rank(js) -> list:
    if not isinstance(js, dict) or js.get("rt_cd") != "0":
        return []
    return [{"code": str(r.get("mksc_shrn_iscd") or "").strip(),
             "name": str(r.get("hts_kor_isnm") or "").strip(),
             "rate": _f(r.get("whol_loan_rmnd_rate"))} for r in js.get("output2") or []]


async def _list(client, key: str):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1], hit[2]
    path, tr, params = _SHORT if key == "short" else _CREDIT
    js = await client._get(path, tr, params)
    if key == "short":
        rows = parse_short_rank(js)
        asof = next((_d8(r.get("stnd_date1")) for r in js.get("output") or []
                     if _d8(r.get("stnd_date1"))), None)
    else:
        rows = parse_credit_rank(js)
        asof = None
    if not rows:
        raise RuntimeError(f"KIS {tr} 빈 순위 목록")   # 빈 성공을 1시간 캐시하지 않는다
    _cache[key] = (now, rows, asof)
    return rows, asof


def _pos(rows: list, code: str, valkey: str) -> dict:
    for i, r in enumerate(rows):
        if r["code"] == code:
            return {"rank": i + 1, "n": len(rows), valkey: r[valkey]}
    return {"rank": None, "n": len(rows), valkey: None}


async def get_position(client, code: str) -> dict:
    """{short:{rank,n,ratio}|None, credit:{rank,n,rate}|None, asof} — 목록 밖이면 rank None."""
    out = {"short": None, "credit": None, "asof": None}
    try:
        rows, asof = await _list(client, "short")
        out["short"], out["asof"] = _pos(rows, code, "ratio"), asof
    except Exception:
        log.warning("공매도 상위 조회 실패", exc_info=True)
    try:
        rows, _ = await _list(client, "credit")
        out["credit"] = _pos(rows, code, "rate")
    except Exception:
        log.warning("신용잔고 상위 조회 실패", exc_info=True)
    return out
