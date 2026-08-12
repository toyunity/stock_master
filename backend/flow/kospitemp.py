from __future__ import annotations

"""'코스피 온도' — 코스피 지수값이 최근 흐름에서 어디쯤인지.

'지수' 섹션은 값을 보여준다(코스피 6,598). 그런데 초보에게 6,598은 그 자체로 의미가
없다 — 최근 흐름에서 어디쯤인지를 모르기 때문이다. 여기서 그 답을 만든다.

**새 원천이 없다.** VKOSPI에 이미 쓰는 TR(FHPUP02120000)을 0001(코스피)로 부르면
100거래일이 한 번에 온다.

**계산은 종가 리스트 하나의 순수 함수다.** `days[-1].v == now.price`가 실측으로 참이라
(2026-08-12) 현재가를 따로 받지 않는다 — 입력이 리스트뿐이면 테스트가 KIS를 안 거친다.

Python 3.9 호환.
"""

import logging
import time
from typing import Optional

from backend.education import glossary
from backend.flow import candles, kst

_EMA_SPAN = 12
_DOWN_WINDOW = 20
# 하락일이 이보다 적으면 표본이 너무 작다 — 평균을 내도 뜻이 없다.
_MIN_DOWN_DAYS = 3


def _clean(closes) -> list:
    """숫자이고 양수인 값만. NaN·0·음수는 지수 종가가 아니다."""
    out = []
    for v in closes or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == f and f > 0:            # NaN 판정(math 임포트 없이)
            out.append(f)
    return out


def _ema(vals: list, span: int) -> float:
    k = 2.0 / (span + 1)
    e = vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
    return e


def _down_avg(vals: list) -> Optional[float]:
    """최근 20 수익률 중 **음수만**의 평균 하락률(양수 %p).

    표준편차가 아니라 평균인 이유: "하락한 날엔 평균 5.0% 빠졌어요"는 읽히지만
    표준편차는 안 읽힌다. 이 지표를 넣는 목적이 그것이다."""
    rets = [(vals[i] - vals[i - 1]) / vals[i - 1] * 100
            for i in range(1, len(vals))]
    down = [r for r in rets[-_DOWN_WINDOW:] if r < 0]
    if len(down) < _MIN_DOWN_DAYS:
        return None
    return round(sum(-r for r in down) / len(down), 2)


def compute(closes) -> dict:
    """종가 리스트(오래된 순, 마지막이 현재가) → 세 지표. 모르면 None.

    ma_gap의 평균에는 오늘 진행 중 봉이 포함된다(가중치 1/100이라 무시할 수 있다).
    ema_gap도 마지막 값이 오늘을 15%쯤 포함한다(k=2/13) — 자기참조지만 관례대로 둔다."""
    vals = _clean(closes)
    if len(vals) < 2:
        return {"ma_gap": None, "ema_gap": None, "down_avg": None}
    cur = vals[-1]
    ma = sum(vals) / len(vals)
    ema = _ema(vals, _EMA_SPAN)
    return {"ma_gap": round((cur - ma) / ma * 100, 2) if ma else None,
            "ema_gap": round((cur - ema) / ema * 100, 2) if ema else None,
            "down_avg": _down_avg(vals)}


# ── KIS 조회 + 조립 ───────────────────────────────────────────────────────

log = logging.getLogger(__name__)

_ISCD = "0001"                      # 코스피
_TTL = 60.0                         # 마지막 봉이 장중에 움직인다 — 해외지수와 같은 주기
_cache = {"ts": 0.0, "data": None, "asof": None}

# (key, label, unit) — 화면 순서. 장기 → 단기 → 변동폭.
_ITEMS = (("ma_gap", "100일 평균", "%"),
          ("ema_gap", "12일 평균", "%"),
          ("down_avg", "하락폭(20일)", "%p"))


async def get_temp() -> dict:
    """{'asof': ISO(KST), 'items': [{key,label,value,unit,verdict}, …]}.

    실패하면 items=[]다 — 에러가 아니라 '그룹을 감추라'는 신호다(빈 껍데기 금지).
    키 없음도 여기서 막지 않는다: 클라이언트 생성 실패가 아래 except로 흡수된다
    (/api/worldidx와 같은 관례 — 게이트를 앞에 두면 테스트가 설정에 끌려간다)."""
    now = kst.now().replace(microsecond=0).isoformat()
    if _cache["data"] is not None and time.time() - _cache["ts"] < _TTL:
        # asof는 **데이터의 시각**이지 요청 시각이 아니다. 여기서 now를 찍으면 캐시
        # 히트 때 최대 60초 묵은 값에 방금 조회한 얼굴을 씌운다 — 이 저장소가 반복해서
        # 잡아온 '신선도를 확신 있게 틀리게 말하는' 결함과 같은 부류다.
        return {"asof": _cache["asof"], "items": _cache["data"]}
    try:
        client = candles._get_client()      # 모듈 경유 — 테스트가 이 지점만 갈아끼운다
        d = await client.index_daily(_ISCD, kst.now().strftime("%Y%m%d"))
    except Exception:
        log.warning("코스피 온도 조회 실패 — 그룹 생략", exc_info=True)
        return {"asof": now, "items": []}
    vals = [x.get("v") for x in ((d or {}).get("days") or [])]
    got = compute(vals)
    items = []
    for key, label, unit in _ITEMS:
        v = got.get(key)
        if v is None:
            continue                        # 모르는 항목은 빼고 보낸다(null 금지)
        items.append({"key": key, "label": label, "value": v, "unit": unit,
                      "verdict": glossary.read_temp(key, v)})
    if items:
        _cache["ts"], _cache["data"], _cache["asof"] = time.time(), items, now
    return {"asof": now, "items": items}
