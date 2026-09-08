from __future__ import annotations

"""예탁원(KSD) 일정 7종 — KIS 종목정보 HHKDB6691xxC0 계열. 종목 상세 "다가오는 일정" 칩의 원천.

실측(2026-09-08, 000660·시장 전체 각 1콜):
- 본문은 전부 output1(list). 기간 필터는 record_date(기준일) 기준이고 SHT_CD를 주면 그 종목만,
  비우면 시장 전체(9~12월 배당 68행)가 온다. 우리는 종목별로만 부른다(관심종목 20개 × 7콜/일).
- 날짜 표기가 TR마다 다르다: record_date·right_dt는 'YYYYMMDD', 지급일·주총일·청약기간은
  'YYYY/MM/DD', 거래정지는 'YYYY/MM/DD ~', 매수청구 접수시한은 앞에 0이 하나 붙은
  '0YYYYMMDD', 매수청구가·액면가는 0패딩(12자리·9자리). 파서가 전부 여기서 정규화한다.
- 합병·분할은 9~12월 조회에 0행이라 실응답 픽스처가 없다 — 필드명은 공식 예제
  COLUMN_MAPPING을 따랐고, 없는 키는 빈 문자열로 흘려보낸다.
"""

import datetime as dt
import logging
import time

from backend.flow import kst
from backend.flow.kis import _f, _i

log = logging.getLogger(__name__)

_BASE = "/uapi/domestic-stock/v1/ksdinfo/"
# (kind, TR, path, 추가 파라미터). 공통 파라미터는 CTS·F_DT·T_DT·SHT_CD.
_KINDS = [
    ("dividend", "HHKDB669102C0", "dividend", {"GB1": "0", "HIGH_GB": ""}),
    ("paidin", "HHKDB669100C0", "paidin-capin", {"GB1": "1"}),
    ("bonus", "HHKDB669101C0", "bonus-issue", {}),
    ("meet", "HHKDB669111C0", "sharehld-meet", {}),
    ("split", "HHKDB669105C0", "rev-split", {"MARKET_GB": "0"}),
    ("merger", "HHKDB669104C0", "merger-split", {}),
    ("purreq", "HHKDB669103C0", "purreq", {}),
]
_TTL = 86400.0        # 일정은 하루 단위로 바뀐다
_BACK_DAYS, _FWD_DAYS = 45, 120
_cache: dict = {}     # code -> (ts, data)


def _s(r: dict, k: str) -> str:
    return str(r.get(k) or "").strip()


def _d8(s: str):
    s = (s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def _dslash(s: str):
    """'2026/09/30' → '2026-09-30'. 앞 10자만 본다('2026/12/14 ~ 2026/12/16'도 시작일)."""
    s = (s or "").strip()
    return s[:10].replace("/", "-") if len(s) >= 10 and s[4] == "/" and s[7] == "/" else None


def _won(v) -> str:
    return f"{_i(v):,}원"


def _dividend(r):
    amt, rate = _i(r.get("per_sto_divi_amt")), _s(r, "divi_rate")
    kind = _s(r, "divi_kind") or "배당"
    detail = (f"{kind} 배당 {amt:,}원(액면 대비 {rate}%)" if amt else f"{kind} 배당 · 금액 미정")
    pay = _dslash(r.get("divi_pay_dt"))
    if pay:
        detail += f" · 지급 {pay}"
    return {"date": _d8(r.get("record_date")), "label": "배당 기준일", "detail": detail}


def _paidin(r):
    price = _i(r.get("fix_price"))
    detail = f"배정률 {_s(r, 'fix_rate')}% · " + (f"발행가 {price:,}원" if price else "발행가 미정")
    if _f(r.get("disc_rate")):
        detail += f"(할인 {_s(r, 'disc_rate')}%)"
    if _s(r, "sub_term"):
        detail += f" · 청약 {_s(r, 'sub_term')}"
    return {"date": _d8(r.get("right_dt")) or _d8(r.get("record_date")),
            "label": "유상증자 권리락", "detail": detail}


def _bonus(r):
    rate = _f(r.get("fix_rate"))
    return {"date": _d8(r.get("right_dt")) or _d8(r.get("record_date")),
            "label": "무상증자 권리락",
            "detail": f"배정률 {_s(r, 'fix_rate')}% (1주당 {rate / 100:g}주)"}


def _meet(r):
    return {"date": _dslash(r.get("gen_meet_dt")),
            "label": f"주주총회({_s(r, 'gen_meet_type') or '정기'})",
            "detail": _s(r, "agenda") or "의안 미공시"}


def _split(r):
    stop = _s(r, "td_stop_dt")
    return {"date": _dslash(stop) or _d8(r.get("record_date")),
            "label": "액면 변경(거래정지)",
            "detail": f"{_won(r.get('inter_bf_face_amt'))}→{_won(r.get('inter_af_face_amt'))}"
                      + (f" · 거래정지 {stop}" if stop else "")}


def _merger(r):
    stop = _s(r, "td_stop_dt")
    who = _s(r, "opp_cust_nm")            # 피합병(피분할) 회사 — 공식 예제 COLUMN_MAPPING
    detail = " · ".join(x for x in (
        _s(r, "merge_type") or "합병·분할", f"상대 {who}" if who else "",
        f"비율 {_s(r, 'merge_rate')}" if _s(r, "merge_rate") else "",
        f"거래정지 {stop}" if stop else "") if x)
    return {"date": _dslash(stop) or _d8(r.get("record_date")), "label": "합병·분할", "detail": detail}


def _purreq(r):
    term = _s(r, "buy_req_rcpt_term").lstrip("0")
    price = _i(r.get("buy_req_price"))
    detail = (f"청구가 {price:,}원" if price else "청구가 미정")
    meet, pay = _dslash(r.get("get_meet_dt")), _dslash(r.get("buy_amt_pay_dt"))
    if meet:
        detail += f" · 주총 {meet}"
    if pay:
        detail += f" · 대금 지급 {pay}"
    return {"date": _d8(term) or _d8(r.get("record_date")),
            "label": "주식매수청구 접수시한", "detail": detail}


_PARSERS = {"dividend": _dividend, "paidin": _paidin, "bonus": _bonus, "meet": _meet,
            "split": _split, "merger": _merger, "purreq": _purreq}


def parse_events(kind: str, js: dict) -> list:
    """한 TR 응답 → [{date, kind, label, detail, code}] (날짜 없는 행은 버린다)."""
    if not isinstance(js, dict) or js.get("rt_cd") != "0":
        return []
    fn = _PARSERS[kind]
    out = []
    for r in js.get("output1") or []:
        try:
            e = fn(r)
        except Exception:  # 한 행의 이상값이 전체 일정을 죽이면 안 된다
            continue
        if e and e.get("date"):
            e["kind"] = kind
            e["code"] = _s(r, "sht_cd")
            out.append(e)
    return out


async def get_events(client, code: str, today=None) -> dict:
    """종목 하나의 일정 — 7 TR 순차, 각 TR 격리(하나 실패해도 나머지 반환), 24h 캐시.

    반환 {rows(날짜 오름차순), asof}. 기간은 today-45일 ~ today+120일(지난 배당 기준일도
    '최근 배당' 참고로 조금 남긴다)."""
    now = time.time()
    hit = _cache.get(code)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    today = today or kst.today()
    f = (today - dt.timedelta(days=_BACK_DAYS)).strftime("%Y%m%d")
    t = (today + dt.timedelta(days=_FWD_DAYS)).strftime("%Y%m%d")
    rows = []
    for kind, tr, path, extra in _KINDS:
        params = {"CTS": "", "F_DT": f, "T_DT": t, "SHT_CD": code}
        params.update(extra)
        try:
            js = await client._get(_BASE + path, tr, params)
            rows.extend(parse_events(kind, js))
        except Exception:
            log.warning("예탁원 일정 조회 실패(%s %s) — 나머지 종류는 계속", code, kind, exc_info=True)
    rows.sort(key=lambda r: (r["date"], r["kind"]))
    data = {"rows": rows, "asof": today.isoformat()}
    _cache[code] = (now, data)
    return data
