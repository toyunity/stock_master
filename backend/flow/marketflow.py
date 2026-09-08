from __future__ import annotations

"""홈 '시장 수급·자금' 섹션 — `/api/market-flow`(60초 폴링) 한 번에 내려가는 6묶음.

"내 종목이 빠질 때 시장 전체 외국인이 팔고 있으면 종목 탓이 아니라 시장 탓"을 한 줄로
보여주기 위한 통로. 원천마다 try/except로 격리하고 TTL 캐시로 원격 호출을 제한한다.

실측(2026-09-08):
- 시장별 투자자 일별 FHPTJ04040000: output(list, 최신순 300행). **DATE_1이 끝(최신), DATE_2가
  시작**이다(반대로 주면 DATE_1 이전 300행만 온다). *_ntby_tr_pbmn은 **백만원** → 억으로 /100.
  마감 후엔 당일 행이 들어온다(17:10에 20260908 행 확인). 장중 당일 행은 잠정치로 표시.
- 증시자금 FHKST649100C0: output(list, 최신순 100행). 예탁금·신용융자·미수·MMF 전부 **억원**
  (예탁금 935,500억 = 93.6조로 검산). 집계는 T+1~2일 늦다.
- 업종별 시세 FHPUP02140000: output1(dict)에 상승/하락/보합 종목 수(시장 폭), output2(list)에
  업종 38행. **코스닥(1001,Q)의 output2는 선물 ETF 목록이 섞여 못 쓴다** — 폭(output1)만 쓴다.
  '종합·대형주·중형주·소형주·코스피 TR·고배당50·VKOSPI'는 업종이 아니라 뺀다.
- 예상체결 지수 FHKUP11750000: output2의 '0001' 행. 동시호가(08:30~09:00) 밖에선 값이 신뢰
  불가(17시에 7061 vs 실제 6954) → 그 시간대에만 조회한다.
- 코스피200 현물 FHPUP02100000(2001): 베이시스 = 선물(대시보드 선물 칩과 같은 값) − 현물.
  선물 기초자산 전광판(FHPIF05030000)은 빈 응답이라 버렸다.
"""

import datetime as dt
import logging
import random
import time
from typing import Optional

from backend.flow import kst
from backend.flow.kis import _f, _i

log = logging.getLogger(__name__)

_Q = "/uapi/domestic-stock/v1/quotations/"
_TTL = {"investors": 300.0, "funds": 3600.0, "breadth": 60.0, "expected": 30.0, "spot": 60.0}
_caches: dict = {}
_NOT_SECTOR = ("종합", "대형주", "중형주", "소형주", "코스피", "TR", "50", "우선주", "VKOSPI", "ESG", "제외")
_EXP_FROM, _EXP_TO = dt.time(8, 30), dt.time(9, 0)   # 예상체결지수가 뜻이 있는 시간대(동시호가)


def _d8(s):
    s = str(s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def _ok(js) -> bool:
    return isinstance(js, dict) and js.get("rt_cd") == "0"


def parse_investor_daily(js) -> list:
    """→ [{date, frgn, prsn, orgn(억원), close}] 오름차순."""
    if not _ok(js):
        return []
    rows = []
    for r in js.get("output") or []:
        d = _d8(r.get("stck_bsop_date"))
        if d:
            rows.append({"date": d, "frgn": round(_i(r.get("frgn_ntby_tr_pbmn")) / 100, 2),
                         "prsn": round(_i(r.get("prsn_ntby_tr_pbmn")) / 100, 2),
                         "orgn": round(_i(r.get("orgn_ntby_tr_pbmn")) / 100, 2),
                         "close": _f(r.get("bstp_nmix_prpr"))})
    return sorted(rows, key=lambda r: r["date"])


def streak(rows: list, key: str) -> int:
    """끝에서부터 같은 부호가 이어진 일수. 양수=순매수 연속, 음수=순매도 연속, 마지막이 0이면 0."""
    if not rows or not rows[-1].get(key):
        return 0
    sign = 1 if rows[-1][key] > 0 else -1
    n = 0
    for r in reversed(rows):
        v = r.get(key) or 0
        if (v > 0) != (sign > 0) or v == 0:
            break
        n += 1
    return sign * n


def parse_funds(js) -> list:
    if not _ok(js):
        return []
    rows = []
    for r in js.get("output") or []:
        d = _d8(r.get("bsop_date"))
        if d:
            rows.append({"date": d, "deposit": _i(r.get("cust_dpmn_amt")),
                         "deposit_chg": _i(r.get("cust_dpmn_amt_prdy_vrss")),
                         "credit": _i(r.get("crdt_loan_rmnd")), "uncl": _i(r.get("uncl_amt")),
                         "mmf": _i(r.get("mmf_amt")), "futs": _i(r.get("futs_tfam_amt"))})
    return sorted(rows, key=lambda r: r["date"])


def parse_breadth(js) -> Optional[dict]:
    if not _ok(js):
        return None
    o = js.get("output1") or {}
    return {"up": _i(o.get("ascn_issu_cnt")), "down": _i(o.get("down_issu_cnt")),
            "flat": _i(o.get("stnr_issu_cnt"))}


def parse_sectors(js) -> list:
    if not _ok(js):
        return []
    out = []
    for r in js.get("output2") or []:
        name = str(r.get("hts_kor_isnm") or "").strip()
        if not name or any(x in name for x in _NOT_SECTOR):
            continue
        out.append({"name": name, "rate": _f(r.get("bstp_nmix_prdy_ctrt"))})
    return out


def parse_expected(js) -> Optional[float]:
    if not _ok(js):
        return None
    for r in js.get("output2") or []:
        if str(r.get("bstp_cls_code") or "").strip() == "0001":
            return _f(r.get("bstp_nmix_prdy_ctrt"))
    return None


async def _cached(name: str, fetch):
    now = time.time()
    hit = _caches.get(name)
    if hit and now - hit[0] < _TTL[name]:
        return hit[1]
    data = await fetch()
    _caches[name] = (now, data)
    return data


def reset_caches() -> None:
    _caches.clear()


def _pos20(rows: list, key: str) -> Optional[float]:
    vals = [r[key] for r in rows[-20:] if r.get(key)]
    if len(vals) < 2:
        return None
    lo, hi = min(vals), max(vals)
    return 50.0 if hi == lo else round((vals[-1] - lo) / (hi - lo) * 100, 1)


async def get_market_flow(client=None, now=None, futures=None) -> dict:
    """{investors, funds, breadth, sectors, expected, basis, asof, demo} — 실패 키는 None.

    futures: 테스트 주입용(대시보드 선물 칩과 같은 dict). None이면 marketdata.get_futures()."""
    if client is None:
        return demo_market_flow()
    now = now or kst.now()
    today = now.date()
    out = {"investors": None, "funds": None, "breadth": None, "sectors": None,
           "expected": None, "basis": None, "asof": now.strftime("%H:%M:%S"), "demo": False}

    async def _inv():
        return parse_investor_daily(await client._get(
            _Q + "inquire-investor-daily-by-market", "FHPTJ04040000",
            {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": "0001",
             "FID_INPUT_DATE_1": today.strftime("%Y%m%d"), "FID_INPUT_ISCD_1": "KSP",
             "FID_INPUT_DATE_2": (today - dt.timedelta(days=60)).strftime("%Y%m%d"),
             "FID_INPUT_ISCD_2": "0001"}))
    try:
        rows = await _cached("investors", _inv)
        if rows:
            last = rows[-1]
            today_row = last if last["date"] == today.isoformat() else None
            out["investors"] = {"rows": rows[-20:], "today": today_row,
                                "streak_frgn": streak(rows, "frgn"), "streak_orgn": streak(rows, "orgn"),
                                "asof": last["date"],
                                "provisional": bool(today_row) and now.time() < dt.time(16, 0)}
    except Exception:
        log.warning("시장 투자자 일별 조회 실패", exc_info=True)

    async def _funds():
        return parse_funds(await client._get(_Q + "mktfunds", "FHKST649100C0", {"FID_INPUT_DATE_1": ""}))
    try:
        rows = await _cached("funds", _funds)
        if rows:
            last = rows[-1]
            chg5 = (round((last["deposit"] / rows[-6]["deposit"] - 1) * 100, 1)
                    if len(rows) >= 6 and rows[-6]["deposit"] else None)
            out["funds"] = {"rows": rows[-20:], "deposit": last["deposit"], "deposit_chg5_pct": chg5,
                            "credit": last["credit"], "credit_pos20": _pos20(rows, "credit"),
                            "uncl": last["uncl"], "asof": last["date"]}
    except Exception:
        log.warning("증시자금 조회 실패", exc_info=True)

    async def _breadth():
        P = {"FID_COND_MRKT_DIV_CODE": "U", "FID_COND_SCR_DIV_CODE": "20214", "FID_BLNG_CLS_CODE": "0"}
        kospi = await client._get(_Q + "inquire-index-category-price", "FHPUP02140000",
                                  dict(P, FID_INPUT_ISCD="0001", FID_MRKT_CLS_CODE="K"))
        kosdaq = await client._get(_Q + "inquire-index-category-price", "FHPUP02140000",
                                   dict(P, FID_INPUT_ISCD="1001", FID_MRKT_CLS_CODE="Q"))
        return {"kospi": parse_breadth(kospi), "kosdaq": parse_breadth(kosdaq),
                "sectors": parse_sectors(kospi)}
    try:
        b = await _cached("breadth", _breadth)
        out["breadth"] = {"kospi": b["kospi"], "kosdaq": b["kosdaq"]}
        sec = sorted(b["sectors"], key=lambda s: -s["rate"])
        out["sectors"] = {"up": sec[:3], "down": sorted(sec[-3:], key=lambda s: s["rate"])}
    except Exception:
        log.warning("업종·시장 폭 조회 실패", exc_info=True)

    if _EXP_FROM <= now.time() < _EXP_TO:
        async def _exp():
            return parse_expected(await client._get(
                _Q + "exp-total-index", "FHKUP11750000",
                {"fid_mrkt_cls_code": "0", "fid_cond_mrkt_div_code": "U", "fid_cond_scr_div_code": "11175",
                 "fid_input_iscd": "0000", "fid_mkop_cls_code": "1"}))
        try:
            r = await _cached("expected", _exp)
            out["expected"] = {"rate": r} if r is not None else None
        except Exception:
            log.warning("예상체결 지수 조회 실패", exc_info=True)

    try:
        if futures is None:
            from backend.api import marketdata
            futures = await marketdata.get_futures() or {}
        fut = ((futures or {}).get("k200") or {}).get("price")
        if fut:
            async def _spot():
                return (await client.index("2001") or {}).get("price")
            spot = await _cached("spot", _spot)
            if spot:
                out["basis"] = {"fut": fut, "spot": spot, "basis": round(fut - spot, 2)}
    except Exception:
        log.warning("베이시스(K200 현물) 조회 실패", exc_info=True)
    return out


def demo_market_flow(today=None) -> dict:
    """키 없음 — 결정적 합성. 홈 캡처(make verify)에 섹션이 보이게 한다."""
    rng = random.Random("market-flow")
    today = today or kst.today()
    inv, funds = [], []
    day = today - dt.timedelta(days=30)
    dep = 950000
    while len(inv) < 20:
        day += dt.timedelta(days=1)
        if day.weekday() >= 5:
            continue
        f = rng.randint(-8000, 8000)
        inv.append({"date": day.isoformat(), "frgn": float(f), "prsn": float(-f + rng.randint(-2000, 2000)),
                    "orgn": float(rng.randint(-3000, 3000)), "close": 6900 + rng.randint(-200, 200)})
        dep += rng.randint(-30000, 30000)
        funds.append({"date": day.isoformat(), "deposit": dep, "deposit_chg": rng.randint(-30000, 30000),
                      "credit": 330000 + rng.randint(-5000, 5000), "uncl": 10000 + rng.randint(-500, 500),
                      "mmf": 2650000, "futs": 400000})
    sectors = [{"name": n, "rate": round(rng.uniform(-3, 3), 2)} for n in
               ("전기·전자", "화학", "금융", "건설", "운송장비·부품", "의료·정밀기기", "통신", "유통")]
    sec = sorted(sectors, key=lambda s: -s["rate"])
    return {"investors": {"rows": inv, "today": inv[-1], "streak_frgn": streak(inv, "frgn"),
                          "streak_orgn": streak(inv, "orgn"), "asof": inv[-1]["date"], "provisional": True},
            "funds": {"rows": funds, "deposit": funds[-1]["deposit"],
                      "deposit_chg5_pct": round((funds[-1]["deposit"] / funds[-6]["deposit"] - 1) * 100, 1),
                      "credit": funds[-1]["credit"], "credit_pos20": _pos20(funds, "credit"),
                      "uncl": funds[-1]["uncl"], "asof": funds[-1]["date"]},
            "breadth": {"kospi": {"up": 231, "down": 634, "flat": 45}, "kosdaq": {"up": 506, "down": 1141, "flat": 90}},
            "sectors": {"up": sec[:3], "down": sorted(sec[-3:], key=lambda s: s["rate"])},
            "expected": {"rate": 0.8}, "basis": {"fut": 1101.2, "spot": 1100.08, "basis": 1.12},
            "asof": "데모", "demo": True}
