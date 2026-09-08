from __future__ import annotations

"""종목 상세 부가 데이터 — `/api/stockinfo/{code}`(5분 폴링) 한 번에 내려가는 8묶음.

엔진·SSE 경로를 건드리지 않으려고 만든 별도 통로다: 여기 것들은 분 단위 이하로 바뀌지
않는다(일정·투자의견·순위 = 일 단위, 매물대·시간외·체결금액 비중 = 5분, 프로그램·체결량
일별 = 1시간). 원천마다 try/except로 격리해 하나가 죽어도 나머지 키는 내려간다(실패 키는
None). 키 없음/데모면 `demo_stockinfo`의 결정적 합성 데이터로 화면·`make verify`를 채운다.

실측(2026-09-08, 000660):
- 투자의견 FHKST663300C0: output(list, 최신순). 의견 문자열이 증권사마다 'BUY'/'매수'로
  섞여 온다 → 한 단어로 정규화. hts_goal_prc 원, stck_prdy_clpr 전일종가, dprt 괴리율.
- 매물대 FHPST01130000: output1(현재가·가중평균가 wghn_avrg_stck_prc), output2 100행
  (가격대 stck_prpr, 체결량 cntg_vol, 거래량 비중 acml_vol_rlim %).
- 시간외 단일가 FHPST02300000: output(dict). **대형주는 vol 0**(005930·000660 — 애프터마켓이
  NXT로 옮겨 감), 소형주(032820)만 체결이 있다 → vol 0이면 화면은 알약을 숨긴다.
- 프로그램 일별 FHPPG04650201: output(30행 최신순) whol_smtn_ntby_qty 주·_tr_pbmn 원.
- 일별 매수/매도 체결량 FHKST03010800: output2(최신순) total_shnu_qty(매수)·total_seln_qty(매도).
- 체결금액별 비중 FHKST111900C0: output(8행 '3백 이하'~'5억 초과') 거래량·건수·순매수비율.
"""

import datetime as dt
import logging
import random
import time
from typing import Optional

from backend.flow import ksdinfo, kst, rankpos
from backend.flow.kis import _f, _i

log = logging.getLogger(__name__)

_Q = "/uapi/domestic-stock/v1/quotations/"
_TTL_DAY, _TTL_HOUR, _TTL_5M = 86400.0, 3600.0, 300.0
_caches: dict = {}   # (name, code) -> (ts, data)


def _d8(s):
    s = str(s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def _ok(js) -> bool:
    return isinstance(js, dict) and js.get("rt_cd") == "0"


# ── 투자의견 ──────────────────────────────────────────────────────────────
_OPN = {"BUY": "매수", "매수": "매수", "STRONG BUY": "매수", "TRADING BUY": "매수", "OUTPERFORM": "매수",
        "HOLD": "중립", "중립": "중립", "NEUTRAL": "중립", "MARKETPERFORM": "중립", "보유": "중립",
        "SELL": "매도", "매도": "매도", "REDUCE": "매도", "UNDERPERFORM": "매도"}


def _norm_opinion(s) -> str:
    s = str(s or "").strip()
    return _OPN.get(s.upper(), s)


def parse_opinions(js) -> list:
    """FHKST663300C0 output → [{date, broker, opinion, prev, target, close}] 최신순(응답 순서)."""
    if not _ok(js):
        return []
    out = []
    for r in js.get("output") or []:
        d = _d8(r.get("stck_bsop_date"))
        if not d:
            continue
        out.append({"date": d, "broker": str(r.get("mbcr_name") or "").strip(),
                    "opinion": _norm_opinion(r.get("invt_opnn")),
                    "prev": _norm_opinion(r.get("rgbf_invt_opnn")),
                    "target": _i(r.get("hts_goal_prc")), "close": _i(r.get("stck_prdy_clpr"))})
    return out


def summarize_opinions(rows: list, price: Optional[int]) -> dict:
    """증권사별 **최신 1건**만 집계. gap_pct = 현재가/평균 목표가 − 1. changes = 의견이 바뀐 행(최대 3)."""
    latest, seen = [], set()
    for r in rows:                      # rows는 최신순 — 첫 등장이 최신
        if r["broker"] and r["broker"] not in seen:
            seen.add(r["broker"])
            latest.append(r)
    targets = [r["target"] for r in latest if r["target"] > 0]
    avg = round(sum(targets) / len(targets)) if targets else None
    cnt = {"매수": 0, "중립": 0, "매도": 0}
    for r in latest:
        if r["opinion"] in cnt:
            cnt[r["opinion"]] += 1
    changes = [{"date": r["date"], "broker": r["broker"], "prev": r["prev"],
                "opinion": r["opinion"], "target": r["target"]}
               for r in rows if r["prev"] and r["opinion"] != r["prev"]][:3]
    return {"n": len(latest), "avg_target": avg,
            "max_target": max(targets) if targets else None,
            "min_target": min(targets) if targets else None,
            "gap_pct": round((price / avg - 1) * 100, 1) if avg and price else None,
            "buy": cnt["매수"], "hold": cnt["중립"], "sell": cnt["매도"],
            "latest": rows[0]["date"] if rows else None, "changes": changes}


# ── 매물대 ────────────────────────────────────────────────────────────────
def parse_profile(js) -> Optional[dict]:
    """FHPST01130000 → {price, wavg, levels(비중 상위 8, 가격 내림차순), top{price,pct}}."""
    if not _ok(js):
        return None
    o1 = js.get("output1") or {}
    lv = [{"price": _i(r.get("stck_prpr")), "vol": _i(r.get("cntg_vol")),
           "pct": _f(r.get("acml_vol_rlim"))} for r in js.get("output2") or []]
    lv = [l for l in lv if l["price"] > 0]
    if not lv:
        return None
    top = max(lv, key=lambda l: l["pct"])
    levels = sorted(sorted(lv, key=lambda l: -l["pct"])[:8], key=lambda l: -l["price"])
    return {"price": _i(o1.get("stck_prpr")), "wavg": _f(o1.get("wghn_avrg_stck_prc")),
            "levels": levels, "top": {"price": top["price"], "pct": top["pct"]}}


# ── 시간외 단일가 ─────────────────────────────────────────────────────────
def parse_overtime(js) -> Optional[dict]:
    if not _ok(js):
        return None
    o = js.get("output") or {}
    vol = _i(o.get("ovtm_untp_vol"))
    if vol <= 0:
        return {"vol": 0}
    return {"price": _i(o.get("ovtm_untp_prpr")), "change": _i(o.get("ovtm_untp_prdy_vrss")),
            "rate": _f(o.get("ovtm_untp_prdy_ctrt")), "vol": vol,
            "value": _i(o.get("ovtm_untp_tr_pbmn")),
            "expected": _i(o.get("ovtm_untp_antc_cnpr")),
            "expected_rate": _f(o.get("ovtm_untp_antc_cntg_ctrt"))}


# ── 일별 시계열 ───────────────────────────────────────────────────────────
def parse_pgm_daily(js) -> list:
    if not _ok(js):
        return []
    rows = [{"date": _d8(r.get("stck_bsop_date")), "net_qty": _i(r.get("whol_smtn_ntby_qty")),
             "net_value": _i(r.get("whol_smtn_ntby_tr_pbmn")), "close": _i(r.get("stck_clpr"))}
            for r in js.get("output") or []]
    return sorted((r for r in rows if r["date"]), key=lambda r: r["date"])


def parse_trade_volume(js) -> list:
    if not _ok(js):
        return []
    rows = []
    for r in js.get("output2") or []:
        d, buy, sell = _d8(r.get("stck_bsop_date")), _i(r.get("total_shnu_qty")), _i(r.get("total_seln_qty"))
        if d:
            rows.append({"date": d, "buy": buy, "sell": sell,
                         "strength": round(buy / sell * 100, 1) if sell else None})
    return sorted(rows, key=lambda r: r["date"])


def parse_trade_by_amount(js) -> list:
    if not _ok(js):
        return []
    return [{"band": str(r.get("prpr_name") or "").strip(), "avg": _i(r.get("smtn_avrg_prpr")),
             "vol": _i(r.get("acml_vol")), "buy_vol": _i(r.get("shnu_cnqn_smtn")),
             "sell_vol": _i(r.get("seln_cnqn_smtn")), "buy_cnt": _i(r.get("shnu_cntg_csnu")),
             "sell_cnt": _i(r.get("seln_cntg_csnu")), "net_rate": _f(r.get("whol_ntby_qty_rate"))}
            for r in js.get("output") or []]


# ── 조회(캐시) ────────────────────────────────────────────────────────────
async def _cached(name: str, code: str, ttl: float, fetch):
    """실패는 캐시하지 않는다 — 다음 5분 폴링이 다시 두드린다."""
    now = time.time()
    hit = _caches.get((name, code))
    if hit and now - hit[0] < ttl:
        return hit[1]
    data = await fetch()
    _caches[(name, code)] = (now, data)
    return data


def reset_caches() -> None:
    _caches.clear()


async def get_stockinfo(code: str, client=None, now=None) -> dict:
    """{events, opinion, pbar, overtime, pgm_daily, tradevol, tradeamt, rankpos, asof} — 실패 키는 None."""
    if client is None:
        return demo_stockinfo(code)
    now = now or kst.now()
    out = {"events": None, "opinion": None, "pbar": None, "overtime": None,
           "pgm_daily": None, "tradevol": None, "tradeamt": None, "rankpos": None,
           "asof": now.strftime("%H:%M:%S"), "demo": False}
    J = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}

    async def _pbar():
        return parse_profile(await client._get(_Q + "pbar-tratio", "FHPST01130000",
                                               dict(J, FID_COND_SCR_DIV_CODE="20113", FID_INPUT_HOUR_1="")))

    async def _opinion():
        d1 = (now.date() - dt.timedelta(days=120)).strftime("%Y%m%d")
        js = await client._get(_Q + "invest-opinion", "FHKST663300C0",
                               dict(J, FID_COND_SCR_DIV_CODE="16633", FID_INPUT_DATE_1=d1,
                                    FID_INPUT_DATE_2=now.strftime("%Y%m%d")))
        return parse_opinions(js)

    async def _overtime():
        return parse_overtime(await client._get(_Q + "inquire-overtime-price", "FHPST02300000", J))

    async def _pgm():
        return parse_pgm_daily(await client._get(_Q + "program-trade-by-stock-daily", "FHPPG04650201",
                                                 dict(J, FID_INPUT_DATE_1="")))

    async def _tv():
        d1 = (now.date() - dt.timedelta(days=40)).strftime("%Y%m%d")
        return parse_trade_volume(await client._get(_Q + "inquire-daily-trade-volume", "FHKST03010800",
                                                    dict(J, FID_PERIOD_DIV_CODE="D", FID_INPUT_DATE_1=d1,
                                                         FID_INPUT_DATE_2=now.strftime("%Y%m%d"))))

    async def _ta():
        return parse_trade_by_amount(await client._get(_Q + "tradprt-byamt", "FHKST111900C0",
                                                       dict(J, FID_COND_SCR_DIV_CODE="11119")))

    jobs = [("pbar", _TTL_5M, _pbar), ("opinion", _TTL_DAY, _opinion), ("overtime", _TTL_5M, _overtime),
            ("pgm_daily", _TTL_HOUR, _pgm), ("tradevol", _TTL_HOUR, _tv), ("tradeamt", _TTL_5M, _ta)]
    for name, ttl, fn in jobs:
        try:
            out[name] = await _cached(name, code, ttl, fn)
        except Exception:
            log.warning("stockinfo %s 조회 실패(%s)", name, code, exc_info=True)
    if out["opinion"] is not None:   # 현재가는 매물대 응답의 것(같은 순간) — 없으면 전일종가
        rows = out["opinion"]
        price = (out["pbar"] or {}).get("price") or (rows[0]["close"] if rows else None)
        out["opinion"] = summarize_opinions(rows, price)
    try:
        out["events"] = await ksdinfo.get_events(client, code)
    except Exception:
        log.warning("stockinfo events 조회 실패(%s)", code, exc_info=True)
    try:
        out["rankpos"] = await rankpos.get_position(client, code)
    except Exception:
        log.warning("stockinfo rankpos 조회 실패(%s)", code, exc_info=True)
    return out


# ── 데모(키 없음) — 결정적 합성. 화면·make verify가 새 패널을 그리게 한다. ──
def demo_stockinfo(code: str, today=None) -> dict:
    rng = random.Random(code)
    today = today or kst.today()
    base = 1000 * (100 + rng.randint(0, 900))
    d = lambda n: (today + dt.timedelta(days=n)).isoformat()
    events = [{"date": d(12), "kind": "dividend", "label": "배당 기준일",
               "detail": f"분기 배당 {base // 400:,}원(액면 대비 7.5%) · 지급 {d(42)}", "code": code},
              {"date": d(31), "kind": "meet", "label": "주주총회(임시총회)", "detail": "정관 변경의 건", "code": code},
              {"date": d(55), "kind": "paidin", "label": "유상증자 권리락",
               "detail": f"배정률 18.68% · 발행가 {int(base * 0.8):,}원 · 청약 {d(80)} ~ {d(82)}", "code": code}]
    opinion = {"n": 5, "avg_target": int(base * 1.25), "max_target": int(base * 1.5),
               "min_target": int(base * 1.05), "gap_pct": -20.0, "buy": 4, "hold": 1, "sell": 0,
               "latest": d(-1), "changes": [{"date": d(-1), "broker": "데모증권", "prev": "매수",
                                              "opinion": "중립", "target": int(base * 1.05)}]}
    levels = sorted([{"price": base + (i - 4) * (base // 100), "vol": 0, "pct": 0.0} for i in range(8)],
                    key=lambda l: -l["price"])
    for l in levels:
        l["pct"] = round(rng.uniform(1.5, 6.0), 2)
        l["vol"] = int(l["pct"] * 40000)
    top = max(levels, key=lambda l: l["pct"])
    pbar = {"price": base, "wavg": float(base) * 1.004, "levels": levels,
            "top": {"price": top["price"], "pct": top["pct"]}}
    overtime = {"price": int(base * 1.012), "change": int(base * 0.012), "rate": 1.19, "vol": 35757,
                "value": int(base * 1.012) * 35757, "expected": int(base * 1.01), "expected_rate": 1.0}
    pgm, tv = [], []
    day = today - dt.timedelta(days=45)
    while len(pgm) < 30:
        day += dt.timedelta(days=1)
        if day.weekday() >= 5:
            continue
        q = rng.randint(-400000, 500000)
        pgm.append({"date": day.isoformat(), "net_qty": q, "net_value": q * base, "close": base})
        b, s = rng.randint(800000, 2200000), rng.randint(800000, 2200000)
        tv.append({"date": day.isoformat(), "buy": b, "sell": s, "strength": round(b / s * 100, 1)})
    bands = ["3백 이하", "5백 이하", "1천 이하", "3천 이하", "5천 이하", "1억 이하", "5억 이하", "5억 초과"]
    tradeamt = []
    for i, bnd in enumerate(bands):
        bv, sv = rng.randint(20000, 900000), rng.randint(20000, 900000)
        tradeamt.append({"band": bnd, "avg": base, "vol": bv + sv, "buy_vol": bv, "sell_vol": sv,
                         "buy_cnt": bv // (3 + i * 20), "sell_cnt": sv // (3 + i * 20),
                         "net_rate": round((bv - sv) / (bv + sv) * 100, 2)})
    return {"events": {"rows": events, "asof": today.isoformat()}, "opinion": opinion, "pbar": pbar,
            "overtime": overtime, "pgm_daily": pgm[-30:], "tradevol": tv[-26:], "tradeamt": tradeamt,
            "rankpos": {"short": {"rank": 12, "n": 30, "ratio": 8.3},
                        "credit": {"rank": None, "n": 100, "rate": None}, "asof": d(-1)},
            "asof": "데모", "demo": True}
