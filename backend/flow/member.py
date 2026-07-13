from __future__ import annotations

"""거래원(회원사) 창구 분석 — 매수/매도 상위 5 창구 + 외국계 vs 국내 (추정).

실측(프로브 2026-07-13):
- FHKST01010600(주식현재가 회원사)은 div J/NX/UN 모두 동작. 회원사별 수량·비중과
  외국계 플래그(seln/shnu_mbcr_glob_yn_N)·외국계 합계(glob_*)를 내장.
- ⚠ 외국계 집계는 KRX(J) 기준만 신뢰 가능: NX 응답은 glob_* 전부 0(미제공),
  UN의 glob 합계는 top5 노출분만 합산돼 J보다 작게 나온다(실측 479k vs 832k).
  → 상위 창구 표는 UN(통합), 외국계 합계는 J로 따로 얻어 '정규장(KRX) 기준' 라벨.
- 금액(원) 필드는 미지원 — 수량·비중(%)만 제공.
- 창구≠주체: 외국인이 국내 창구를 쓸 수 있음 — 화면에 '추정' 라벨 필수(스펙).
"""

import logging
import time
from typing import Optional

from backend.flow import kst
from backend.flow.kis import _f, _i

log = logging.getLogger(__name__)

_PATH = "/uapi/domestic-stock/v1/quotations/inquire-member"
_TR = "FHKST01010600"
_TTL = 60.0
_cache: dict = {}  # code -> (ts, data)

# 외국계 창구 상수 — 응답의 glob_yn이 비거나 N인데 이름이 외국계인 경우의 백스톱
# (NXT 행은 glob_yn이 전부 N으로 오는 실측 제약 보완)
FOREIGN_DESKS = ("모간", "모건", "JP", "제이피", "골드만", "메릴", "머릴", "UBS",
                 "유비에스", "CS", "크레디트", "노무라", "다이와", "맥쿼리", "씨엘",
                 "CLSA", "씨티", "HSBC", "에이치에스비씨", "BNP", "비엔피", "도이치",
                 "소시에테", "SG", "바클레이", "스탠다드차타드", "미즈호", "SMBC")


def _is_foreign(name: str, glob_yn: str) -> bool:
    if glob_yn == "Y":
        return True
    return any(k in (name or "") for k in FOREIGN_DESKS)


def parse_member(js: dict) -> Optional[dict]:
    """FHKST01010600 → {sell:[{name,qty,rlim,foreign}×5], buy:[...],
    glob:{seln,shnu,ntby,seln_rlim,shnu_rlim}}. rt_cd≠0이면 None."""
    if js.get("rt_cd") != "0":
        return None
    out = js.get("output") or {}
    if isinstance(out, list):  # 1원소 배열로 직렬화되는 경우 관측됨
        out = out[0] if out else {}
    if not out:
        return None

    def side(prefix_name, prefix_qty, prefix_rlim, prefix_glob):
        rows = []
        for i in range(1, 6):
            name = (out.get(f"{prefix_name}{i}") or "").strip()
            qty = _i(out.get(f"{prefix_qty}{i}"))
            if not name and not qty:
                continue
            rows.append({"name": name, "qty": qty,
                         "rlim": _f(out.get(f"{prefix_rlim}{i}")),
                         "foreign": _is_foreign(
                             name, str(out.get(f"{prefix_glob}{i}", "")))})
        return rows

    return {
        "sell": side("seln_mbcr_name", "total_seln_qty", "seln_mbcr_rlim",
                     "seln_mbcr_glob_yn_"),
        "buy": side("shnu_mbcr_name", "total_shnu_qty", "shnu_mbcr_rlim",
                    "shnu_mbcr_glob_yn_"),
        "glob": {"seln": _i(out.get("glob_total_seln_qty")),
                 "shnu": _i(out.get("glob_total_shnu_qty")),
                 "ntby": _i(out.get("glob_ntby_qty")),
                 "seln_rlim": _f(out.get("glob_seln_rlim")),
                 "shnu_rlim": _f(out.get("glob_shnu_rlim"))},
    }


async def get_member(client, code: str) -> dict:
    """상위 창구(UN 통합) + 외국계 합계(J·정규장 기준) — 60초 TTL.

    반환 {sell, buy, glob(J 기준), asof}. 실패는 예외로 위임."""
    now = time.time()
    hit = _cache.get(code)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    js_un = await client._get(_PATH, _TR, {"FID_COND_MRKT_DIV_CODE": "UN",
                                           "FID_INPUT_ISCD": code})
    un = parse_member(js_un)
    js_j = await client._get(_PATH, _TR, {"FID_COND_MRKT_DIV_CODE": "J",
                                          "FID_INPUT_ISCD": code})
    j = parse_member(js_j)
    if un is None or j is None:
        # 한쪽 소프트 오류를 캐시하면 유효하던 외국계 합계가 60초+ 사라진다
        # (리뷰 확정) — 예외로 위임, 엔진이 이전 패널 유지.
        raise RuntimeError(f"KIS {_TR} rt_cd≠0 (UN={un is not None}, "
                           f"J={j is not None})")
    data = {"sell": un["sell"], "buy": un["buy"], "basis": "UN",
            "glob": j["glob"],  # 외국계 합계는 J 기준만 신뢰(실측)
            "asof": kst.now().strftime("%H:%M:%S")}
    _cache[code] = (now, data)
    return data
