from __future__ import annotations

"""신용융자 잔고(반대매매 연료 게이지) — KIS 국내주식 신용잔고일별 FHPST04760000.

원래 계획은 금융투자협회 freesis 크롤링이었으나 프로브(2026-07-13)로 freesis에는
종목별 신용공여 통계 자체가 없음을 확인(메뉴 트리 152종 전수 — 신용공여는 시장
집계 2종뿐, 종목 입력 조건 없음). KIS TR이 종목별 일별 잔고를 30행/1콜로 제공.

주의(실측):
- deal_date(매매일) 기준이지만 결제(stlm_date) 반영이라 실질 T+2 지연 — T+1이 아니다.
- whol_loan_rmnd_amt(잔고 금액)는 단위가 문서 불명(만원 추정) → 쓰지 않고
  주수×그날 종가로 산출해 '≈' 라벨을 붙인다(shortbal의 SEIBro 방식과 동일).
- 주수(_stcn)·비율(_rate/gvrt %) 필드는 교차 검증됨(공여율 = 신규/거래량 일치).
"""

import logging
import time
from typing import Optional

from backend.flow import kst
from backend.flow.kis import _f, _i

log = logging.getLogger(__name__)

_PATH = "/uapi/domestic-stock/v1/quotations/daily-credit-balance"
_TR = "FHPST04760000"
_TTL = 3600.0    # 하루 한 번 갱신되는 데이터 — 1시간 캐시로 충분
_cache: dict = {}  # code -> (ts, data)


def parse_credit(js: dict) -> list:
    """FHPST04760000 → [{date,qty,ratio,new,rdmp,close,value}] 날짜 오름차순.

    value는 주수×종가 산출값(원) — 응답의 잔고금액 필드는 단위 불명이라 미사용."""
    if js.get("rt_cd") != "0":
        return []
    rows = []
    for r in js.get("output") or []:
        d = str(r.get("deal_date", ""))
        if len(d) != 8:
            continue
        qty = _i(r.get("whol_loan_rmnd_stcn"))
        close = _i(r.get("stck_prpr"))
        rows.append({"date": f"{d[0:4]}-{d[4:6]}-{d[6:8]}", "qty": qty,
                     "ratio": _f(r.get("whol_loan_rmnd_rate")),
                     "new": _i(r.get("whol_loan_new_stcn")),
                     "rdmp": _i(r.get("whol_loan_rdmp_stcn")),
                     "close": close, "value": qty * close})
    rows.sort(key=lambda r: r["date"])
    out = []
    for i, r in enumerate(rows):
        out.append(dict(r, chg=(r["qty"] - rows[i - 1]["qty"]) if i else None))
    return out


def credit_signal(rows: list) -> Optional[dict]:
    """스펙 판정: '주가 급락일 다음 날 잔고 급감 = 강제청산 소화 진행'.

    반대매매는 급락 다음 날 아침에 집행 → 전일 급락(-3%↓) × 당일 잔고 급감(-1%↓)
    조합을 우선 판정하고, 나머지는 잔고 증감 × 주가 방향 4분면."""
    if len(rows) < 2:
        return None
    cur, prev = rows[-1], rows[-2]
    if not prev["qty"] or not prev["close"]:
        return None
    qty_pct = (cur["qty"] - prev["qty"]) / prev["qty"] * 100
    px_pct = (cur["close"] - prev["close"]) / prev["close"] * 100
    if len(rows) >= 3 and rows[-3]["close"]:
        prev_px_pct = (prev["close"] - rows[-3]["close"]) / rows[-3]["close"] * 100
        if prev_px_pct <= -3 and qty_pct <= -1:
            return {"text": "급락 다음 날 잔고 급감 — 강제청산(반대매매) 소화 진행",
                    "tone": "info"}
    if px_pct <= -3 and qty_pct <= -1:
        return {"text": "급락과 동시에 잔고 급감 — 반대매매 진행 중 (경계)",
                "tone": "warn"}
    if qty_pct >= 1 and px_pct < 0:
        return {"text": "하락에도 신용 증가 — 반대매매 연료 축적 (경계)", "tone": "warn"}
    if qty_pct >= 1:
        return {"text": "상승 속 신용 확대 — 레버리지 베팅 증가", "tone": "info"}
    if qty_pct <= -1:
        return {"text": "신용 상환 진행 — 반대매매 연료 감소", "tone": "good"}
    return {"text": "중립 — 뚜렷한 신호 없음", "tone": "flat"}


async def get_history(client, code: str, days: int = 20) -> dict:
    """최근 N거래일 신용융자 잔고 — 1콜(30행), 1시간 메모리 캐시.

    반환 {rows, asof}. 실패는 예외로 위임(엔진이 격리 처리, 화면은 이전 값 유지)."""
    now = time.time()
    hit = _cache.get(code)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    js = await client._get(_PATH, _TR,
                           {"FID_COND_MRKT_DIV_CODE": "J",
                            "FID_COND_SCR_DIV_CODE": "20476",
                            "FID_INPUT_ISCD": code,
                            "FID_INPUT_DATE_1": kst.today().strftime("%Y%m%d")})
    if js.get("rt_cd") != "0":
        # KIS 소프트 오류는 HTTP 200 + rt_cd≠0으로 온다(kis.py 실측) — 빈 결과로
        # 1시간 캐시하면 엔진의 매분 재시도가 무력화되므로 예외로 위임(리뷰 확정).
        raise RuntimeError(f"KIS {_TR} rt_cd={js.get('rt_cd')} {js.get('msg1', '')}")
    rows = parse_credit(js)[-days:]
    data = {"rows": rows, "asof": rows[-1]["date"] if rows else None}
    _cache[code] = (now, data)
    return data
