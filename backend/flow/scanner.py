from __future__ import annotations

"""시장 스캐너 — 오늘 수급 특이 종목 자동 발굴.

KIS 랭킹 5콜(실측 검증 파라미터, 2026-07-10):
외국인 순매수/순매도 상위 · 기관 순매수 상위(FHPTJ04400000 가집계, 백만원 단위),
거래대금 상위(FHPST01710000, ETF/ETN/SPAC 제외 마스크), 급등 상위(FHPST01700000,
소문자 파라미터·rank_sort 1글자 — 공식 예제의 '0000'은 실서버가 거부).

가집계는 증권사 수기 입력(하루 4~5회 갱신, 1,000주 반올림 잠정치)이므로
새로고침은 60초 캐시로 충분하다. 픽 = 수급(외인/기관 순매수) ∩ 모멘텀(거래대금/급등).
"""

import asyncio
import datetime as dt
import logging
import re
import time

from backend.config import settings
from backend.flow.kis import _SIGN, KisClient, _f, _i

log = logging.getLogger(__name__)

_CODE6 = re.compile(r"^\d{6}$")
_TTL = 60.0
_cache = {"ts": 0.0, "data": None}

_FIT_PATH = "/uapi/domestic-stock/v1/quotations/foreign-institution-total"
_FIT_BASE = {"FID_COND_MRKT_DIV_CODE": "V", "FID_COND_SCR_DIV_CODE": "16449",
             "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "1"}  # 금액 기준
_VOL_PATH = "/uapi/domestic-stock/v1/quotations/volume-rank"
_VOL_PARAMS = {"FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171",
               "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "0",
               "FID_BLNG_CLS_CODE": "3",  # 거래금액순
               "FID_TRGT_CLS_CODE": "111111111",
               "FID_TRGT_EXLS_CLS_CODE": "0000001101",  # ETF·ETN·SPAC 제외(실측)
               "FID_INPUT_PRICE_1": "", "FID_INPUT_PRICE_2": "",
               "FID_VOL_CNT": "", "FID_INPUT_DATE_1": ""}
_FLUC_PATH = "/uapi/domestic-stock/v1/ranking/fluctuation"
_FLUC_PARAMS = {"fid_cond_mrkt_div_code": "J", "fid_cond_scr_div_code": "20170",
                "fid_input_iscd": "0000", "fid_rank_sort_cls_code": "0",  # 1글자!
                "fid_input_cnt_1": "0", "fid_prc_cls_code": "0",
                "fid_input_price_1": "", "fid_input_price_2": "",
                "fid_vol_cnt": "100000",  # 최소 거래량(잡주 제외)
                "fid_trgt_cls_code": "111111111",
                "fid_trgt_exls_cls_code": "0000001101",
                "fid_div_cls_code": "0", "fid_rsfl_rate1": "", "fid_rsfl_rate2": ""}


def _common(r: dict, code_key: str):
    """랭킹 행 공통 필드. 비 6자리 코드(ETN 'Q…' — 실측)는 버린다."""
    code = str(r.get(code_key, "")).strip()
    if not _CODE6.match(code):
        return None
    return {"code": code, "name": str(r.get("hts_kor_isnm", "")),
            "price": _i(r.get("stck_prpr")),
            "sign": _SIGN.get(str(r.get("prdy_vrss_sign", "")), ""),
            "rate": _f(r.get("prdy_ctrt")), "vol": _i(r.get("acml_vol"))}


def parse_fit_rank(js: dict) -> list:
    """FHPTJ04400000 → 투자자 순매수 랭킹. 금액은 백만원 → 원 환산(실측 검증)."""
    rows = []
    for r in js.get("output") or []:
        c = _common(r, "mksc_shrn_iscd")
        if not c:
            continue
        c.update({"frgn_qty": _i(r.get("frgn_ntby_qty")),
                  "frgn_value": _i(r.get("frgn_ntby_tr_pbmn")) * 1_000_000,
                  "orgn_qty": _i(r.get("orgn_ntby_qty")),
                  "orgn_value": _i(r.get("orgn_ntby_tr_pbmn")) * 1_000_000})
        rows.append(c)
    return rows


def parse_volume_rank(js: dict) -> list:
    """FHPST01710000 → 거래대금 랭킹. acml_tr_pbmn만 raw 원(실측)."""
    rows = []
    for r in js.get("output") or []:
        c = _common(r, "mksc_shrn_iscd")
        if not c:
            continue
        c.update({"rank": _i(r.get("data_rank")),
                  "value": _i(r.get("acml_tr_pbmn")),
                  "vol_change": _f(r.get("vol_inrt"))})  # 전일比 거래량 증가율 %
        rows.append(c)
    return rows


def parse_fluctuation(js: dict) -> list:
    """FHPST01700000 → 급등 랭킹. 코드 필드명이 stck_shrn_iscd로 다름(실측)."""
    rows = []
    for r in js.get("output") or []:
        c = _common(r, "stck_shrn_iscd")
        if not c:
            continue
        c.update({"rank": _i(r.get("data_rank")),
                  "streak": _i(r.get("cnnt_ascn_dynu")),
                  "limit_up": str(r.get("prdy_vrss_sign")) == "1"})
        rows.append(c)
    return rows


def build_picks(frgn_buy: list, orgn_buy: list, value_top: list,
                gainers: list) -> list:
    """수급(외인/기관 순매수 상위) ∩ 모멘텀(거래대금/급등 상위) = 오늘의 수급 특이."""
    frgn_codes = {r["code"] for r in frgn_buy}
    orgn_codes = {r["code"] for r in orgn_buy}
    val_codes = {r["code"] for r in value_top}
    gain_codes = {r["code"] for r in gainers}
    picks, seen = [], set()
    for r in list(frgn_buy) + list(orgn_buy):
        code = r["code"]
        if code in seen or not ((code in val_codes) or (code in gain_codes)):
            continue
        seen.add(code)
        reasons = []
        if code in frgn_codes:
            reasons.append("외인매수")
        if code in orgn_codes:
            reasons.append("기관매수")
        if code in val_codes:
            reasons.append("거래대금상위")
        if code in gain_codes:
            reasons.append("급등")
        picks.append(dict(r, reasons=reasons))
    return picks


async def fetch_scan(client=None) -> dict:
    """스캔 1회(5콜, 60s 캐시). 섹션별 실패는 빈 리스트로 강등(부분 결과 우선)."""
    now = time.time()
    if _cache["data"] is not None and now - _cache["ts"] < _TTL:
        return _cache["data"]
    if client is None:
        client = KisClient(settings.kis_app_key, settings.kis_app_secret,
                           settings.cache_dir)

    async def call(path, tr_id, params, parser):
        try:
            result = parser(await client._get(path, tr_id, params))
        except Exception:
            log.warning("스캐너 %s 조회 실패", tr_id, exc_info=True)
            result = []
        await asyncio.sleep(0.25)  # 연속 호출 간헐 500 완화(실측) — 콜 간 간격
        return result

    frgn_buy = await call(_FIT_PATH, "FHPTJ04400000",
                          dict(_FIT_BASE, FID_RANK_SORT_CLS_CODE="0",
                               FID_ETC_CLS_CODE="1"), parse_fit_rank)
    frgn_sell = await call(_FIT_PATH, "FHPTJ04400000",
                           dict(_FIT_BASE, FID_RANK_SORT_CLS_CODE="1",
                                FID_ETC_CLS_CODE="1"), parse_fit_rank)
    orgn_buy = await call(_FIT_PATH, "FHPTJ04400000",
                          dict(_FIT_BASE, FID_RANK_SORT_CLS_CODE="0",
                               FID_ETC_CLS_CODE="2"), parse_fit_rank)
    value_top = await call(_VOL_PATH, "FHPST01710000", _VOL_PARAMS,
                           parse_volume_rank)
    gainers = await call(_FLUC_PATH, "FHPST01700000", _FLUC_PARAMS,
                         parse_fluctuation)

    data = {"asof": dt.datetime.now().strftime("%H:%M:%S"),
            "sections": {"frgn_buy": frgn_buy, "frgn_sell": frgn_sell,
                         "orgn_buy": orgn_buy, "value_top": value_top,
                         "gainers": gainers},
            "picks": build_picks(frgn_buy, orgn_buy, value_top, gainers)}
    _cache["ts"], _cache["data"] = now, data
    return data
