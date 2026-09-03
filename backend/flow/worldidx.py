from __future__ import annotations

"""글로벌 지표(미국채·원자재·해외지수) — 대시보드 '글로벌' 섹션 데이터.

"미국이 어젯밤 어땠나"를 다른 앱에서 보던 왕복을 없앤다. 원천이 셋이지만 소비자가 보는
건 칩 목록 하나라 한 모듈로 묶었다(futures.py·semi.py와 같은 결 — 한 주제 = 한 모듈).

원천은 2026-08-11 실측으로 확정했다(docs/superpowers/specs/2026-08-11-global-indices-design.md):
- 미국채 2Y/10Y/30Y: 미 재무부 일별 금리곡선 Atom XML. 매 영업일 ~15:47 UTC 공시라
  한국 아침엔 항상 직전 미국장 값이 있다. **월초엔 이번 달 엔트리가 아예 없어** 전월로
  폴백한다(빈 피드도, 404/타임아웃 예외도 같은 폴백을 탄다).
- WTI·금: FinanceDataReader CL=F / GC=F. 동기 라이브러리라 asyncio.to_thread로 감싼다.
- S&P500·나스닥·VIX: KIS FHKST03030100(div=N). 클라이언트는 candles._get_client()를
  **모듈 경유로** 부른다(테스트가 그 지점만 갈아끼운다). 조회 날짜·기준일은 전부
  _last_us_session()에서 나온다 — KST 오늘도 ET 오늘도 실제 세션보다 앞선다.

버린 후보(재조사 방지): FRED는 최신 관측이 나흘~일주일 지연, ETF 프록시(GLD·USO)는
단위가 달라 "금 402"처럼 틀린 숫자로 읽히고, KIS 해외선물(CLU26·GCQ26)은 파라미터가
아니라 거래소 신청 권한이 없어 막힌다(EGW00551/EGW00553).
장중 미국금리 후보도 2026-08-12에 전부 실측했다: 야후 ^TNX는 값은 맞지만 미 채권장
시간에만 움직이고 **2년물 지수가 없다**(^FVX는 5년물). CME 마이크로 수익률선물은
유동성이 없어 **만료된 월물을 조용히 계속 준다**(2YY=F가 07-15 만료 계약값). CBOT
국채선물 ZN=F/ZT=F는 살아 움직이지만 가격 호가라 108.45는 금리가 아니다(수익률 변환은
CTD·전환계수가 필요). MarketWatch는 401, stooq는 404. **CNBC만 유일하게 된다.**

**KIS 해외지수 TR의 함정**: 이 TR은 주식 티커도 받는다. `CL`=93.15는 WTI가 아니라
콜게이트고 `XAU`는 금광주 지수다 — 값이 0이 아니라고 그 상품이 아니다. 단위 검증 없이
_INDICES를 늘리지 말 것.

설계 결정 셋:
- `unit`을 **데이터에 실어** 내린다. 프런트가 단위를 추측하면 위 프록시 사고가 재발한다.
- `basis`(기준일)도 **항목마다** 싣는다. 살아 있는 코스피 칩 옆에 놓이면 값이 신선해
  보이므로 칩 자체에 기준일이 찍혀야 한다.
- 모든 원격 호출에 **하드 상한**(_CALL_TIMEOUT)을 씌운다. 실패 격리를 예외로만 짜면
  원천이 무응답으로 매달릴 때(TCP 블랙홀) 그대로 뚫린다 — 매달린 스레드가 락을 붙잡아
  멀쩡한 나머지 원천까지 영영 갱신되지 않는다.

`rate`는 세 원천 모두 **등락률(%)**이다 — 금리도 bp/%p가 아니라 같은 정의를 쓴다.
대시보드의 칩 렌더러(fxchip/ix)가 rate에 '%'를 붙여 그리므로, 여기서만 %p를 넣으면
설계 문서가 경고한 단위 섞임이 그대로 재현된다. 모르는 값은 0.00%로 꾸미지 않고 None.

Python 3.9 호환.
"""

import asyncio
import datetime as dt
import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional

from backend.flow import adr, candles, kst, toss
from backend.flow.kis import _SIGN
# kis._f는 일부러 안 쓴다 — None·빈문자·비숫자를 전부 0.0으로 뭉개, 위 '모르는 값은
# None' 계약을 조용히 깬다. 이 모듈은 _num(모르면 None)만 쓴다.

log = logging.getLogger(__name__)

_TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
                 "interest-rates/pages/xml?data=daily_treasury_yield_curve"
                 "&field_tdr_date_value_month={month}")
_NS = {"a": "http://www.w3.org/2005/Atom",
       "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
       "d": "http://schemas.microsoft.com/ado/2007/08/dataservices"}

_IDX_PATH = "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
_IDX_TR = "FHKST03030100"

# (key, label, XML 필드) — 만기 셋만 쓴다(20Y·1M 등은 화면에 안 올린다).
_TENORS = (("ust2y", "2년", "2Y"), ("ust10y", "10년", "10Y"),
           ("ust30y", "30년", "30Y"))
# (key, label, FDR 심볼, 단위)
_COMMODITIES = (("wti", "WTI", "CL=F", "$/bbl"), ("gold", "금", "GC=F", "$/oz"))
# (key, label, KIS ISCD) — 늘리기 전에 위 '함정' 문단을 읽을 것.
# comp 라벨이 '나스닥 종합'인 이유: '지수' 섹션에서 '나스닥 선물' 칩과 나란히 뜬다.
# COMP는 실제로 나스닥 종합지수라 더 정확하기도 하다.
_INDICES = (("spx", "S&P500", "SPX"), ("comp", "나스닥 종합", "COMP"),
            ("vix", "VIX", "VIX"))

# (key, label, 토스 심볼) — 한국 국채. 토스 Open API에만 있다(KIS엔 없다).
# 6종(2·3·5·10·20·30Y)이 전부 오지만 둘만 올린다: 3년은 뉴스가 인용하는 국내 지표금리,
# 10년은 미국채 10년과 나란히 놓아 한·미 금리차를 눈으로 읽는 자리다. 칩 스트립이
# 길어지면 화면에서 안 읽힌다. 늘리려면 여기만 늘리면 되고, 그룹 벽 테스트가 먼저 잡는다.
_KR_TENORS = (("krb3y", "3년", "KR_BOND_3Y"),
              ("krb10y", "10년", "KR_BOND_10Y"))

_TTL = {"treasury": 600.0,      # CNBC 사이클 — 10분에 한 번(마스터 지시: 사설 API 배려)
        "treasury_rows": 3600.0,  # 재무부 원본(폴백 바닥) — 하루 한 번 갱신되는 값
        "commodity": 600.0,     # FDR(비공식 경유)은 아껴 쓴다
        # 국채 일봉의 **마지막 봉이 확정치인지 장중 진행값인지 문서에 명시가 없다**
        # (2026-09-03 스펙 실사). 10분이면 어느 쪽이든 안전하고, 그룹 한도
        # MARKET_INDICATOR_CHART(초당 5회)에 부담이 없다.
        "krbond": 600.0,
        "index": 60.0}          # KIS 지수는 지연 실시간
# fail_ts: 실패한 원천을 매 폴링마다 다시 두드리지 않기 위한 쿨다운 시각.
# 없으면 재무부가 죽었을 때 폴링마다 두 달치 타임아웃을 물고 락을 잡은 채 서 있어,
# 멀쩡히 캐시된 나머지 그룹까지 같이 늦어진다.
_cache = {k: {"ts": 0.0, "data": None, "fail_ts": 0.0} for k in _TTL}
_FAIL_COOLDOWN = 60.0
# CNBC는 기본보다 길게 물러선다. 우리를 거절하는 중이라면 1분마다 다시 두드리는 게
# 최악의 행동이다 — 그동안 화면은 재무부 확정치로 조용히 강등된다.
_COOLDOWN = {"treasury": 600.0}

_FDR_LOOKBACK_DAYS = 10   # 주말·휴장 + 전부 NaN인 결측 행을 넘길 만큼 넉넉히
_GAP = 0.25               # KIS 연속 호출 간헐 500 완화(semi.py와 같은 관례)
_TIMEOUT = 5.0            # 실패 시 두 달을 연달아 물으므로 넉넉히 잡으면 두 배로 늦다

# 원격 호출 하나의 **하드 상한**. requests의 timeout은 상한이 아니라 connect/read에
# 각각 적용되는 값이고, FDR(fdr.DataReader → requests.get)엔 그 인자조차 없다 —
# 야후가 RST 없이 무응답이면(TCP 블랙홀) 그 스레드는 영원히 매달린다.
_CALL_TIMEOUT = 8.0
# CNBC **단계 전체** 상한. 재무부 그룹은 CNBC 단계와 재무부 폴백이 연달아 돌므로 둘의
# 합이 _GROUP_TIMEOUT 안에 들어와야 한다 — 안 들어오면 그룹 벽이 먼저 터져 전월 폴백을
# 아예 못 타고 미국 금리가 통째로 사라진다(그리고 600초 쿨다운). 호출 단위가 아니라
# 단계 단위로 거는 이유: 만기를 하나 더 늘려도 이 항이 안 커진다.
# 실측 응답은 1초 미만이라(2026-08-12) 10초면 정상 경로에 넉넉하다.
_CNBC_PHASE_TIMEOUT = 10.0
# 그룹 하나의 백스톱. **_GROUP_TIMEOUT > (그룹 안 호출 수 × _CALL_TIMEOUT) + 슬립 합**을
# 지켜라. 이 부등식이 깨지면 그룹 벽이 먼저 터져, 이미 모아둔 칩까지 통째로 버린다 —
# 칩 단위 격리를 스스로 무효화하는 셈이다.
#   최대는 재무부 그룹이다: _CNBC_PHASE_TIMEOUT(10) + 재무부 두 달(2×8) = 26.0.
#   지수 그룹은 3×8+0.5=24.5. 이 관계는 주석이 아니라
#   test_group_wall_leaves_room_for_every_call_in_the_group이 지킨다.
_GROUP_TIMEOUT = 30.0
_UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/126.0.0.0 Safari/537.36")}

_lock: Optional[asyncio.Lock] = None   # 3.9 호환 — 루프 안에서 lazy 생성


def _get_lock() -> asyncio.Lock:
    """아이폰+맥이 동시에 폴링해도 세 원천 스윕이 겹치지 않게(semi.get_overview와 동일)."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _mmdd(d: Optional[dt.date]) -> Optional[str]:
    return d.strftime("%m-%d") if d else None


def _last_us_session() -> dt.date:
    """지수 값이 실제로 속한 '가장 최근 미국 정규장' 날짜.

    KST 오늘로 찍으면 간밤 미국장 값에 오늘 날짜가 박힌다. 그런데 **ET 오늘도 답이
    아니다** — 실제 세션보다 앞선 날을 찍는 구간이 주중 대부분이다: 주말 전체,
    월요일 아침(ET는 일요일), 그리고 매 평일 KST 13:00~22:30(ET로는 오늘이지만
    미국장은 22:30 KST에나 열린다). 값은 직전 종가인데 날짜만 앞선 날이 박히면
    basis를 항목마다 실은 목적(신선도 착시 방지)이 정면으로 무너진다. 그래서 개장
    전·주말이면 직전 거래일로 되감는다.

    ET 시계는 adr._ET 하나만 쓰고 개장 경계(09:30)도 adr.us_market_open과 같다 —
    DST 처리를 두 군데서 흉내내지 않는다. 미국 휴장일 달력은 없다(adr.py가 이미 같은
    한계를 기록해뒀다) — 휴장일엔 하루 앞선 날짜가 나올 수 있고, 그 자리는 KIS
    output2가 실제 세션 날짜를 주면 그쪽이 바로잡는다(호출부의 '더 이른 쪽이 이긴다')."""
    n = kst.now().astimezone(adr._ET)
    d = n.date()
    if n.strftime("%H:%M") < "09:30":     # 개장 전이면 아직 '어제 장'이다
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:               # 토·일 → 금요일
        d -= dt.timedelta(days=1)
    return d


def cme_open(now_et: Optional[dt.datetime] = None) -> bool:
    """CME Globex(원자재)와 현금 국채 시장이 열려 있는가 — **ET 벽시계**.

    일 18:00 ET 개장 → 금 17:00 ET 마감, 매일 17:00~18:00 ET 휴식.
    두 시장의 창이 사실상 같아 **헬퍼 하나를 공유한다** — 같은 판정을 두 군데서
    흉내내면 한쪽만 고쳐지는 날이 온다(원자재 신선도 + CNBC 호출 게이트).

    KST 벽시계로 판정하면 미국 서머타임 전환마다 한 시간씩 어긋나므로 adr._ET를 쓴다
    (_last_us_session과 같은 시계 — DST 처리를 두 군데서 흉내내지 않는다).

    **절대 쓰면 안 되는 대안**: "값의 시각이 오늘(KST)이면 열림". 토요일 10:00 KST면
    마지막 호가가 토 06:00 KST(= 금 17:00 ET 정산)라 '오늘'이 되어 정산된 값에 live가
    붙고, 일요일 10:00엔 같은 숫자가 '오늘이 아니'라 마감으로 뒤집힌다.

    한계: 미국 휴장일 달력은 없다 — 휴장일엔 정산된 값에 '실시간'이 붙을 수 있다.
    adr.us_market_open·futures.session_of가 이미 같은 한계를 안고 같은 이유로
    받아들인다(휴장일 하루를 위해 달력을 들이는 값어치가 없다)."""
    n = now_et or kst.now().astimezone(adr._ET)
    wd, hm = n.weekday(), n.strftime("%H:%M")      # 월=0 … 토=5, 일=6
    if wd == 5:                                    # 토요일은 종일 휴장
        return False
    if wd == 6:                                    # 일요일은 18:00 ET에 열린다
        return hm >= "18:00"
    if wd == 4 and hm >= "17:00":                  # 금요일 17:00 마감 → 주말
        return False
    return not ("17:00" <= hm < "18:00")           # 평일 일일 휴식


async def _blocking(fn, *args):
    """동기 함수를 스레드로 넘기되 **하드 상한**을 씌운다.

    상한이 없으면 원천이 예외를 던지지 않고 그냥 매달릴 때(TCP 블랙홀) 이 코루틴이
    영영 안 끝나고, get_worldidx가 락 안에서 그걸 기다리므로 이후 모든 폴링이 줄서서
    같이 멈춘다. 그러면 멀쩡한 나머지 원천까지 갱신이 끊겨 화면이 옛 스냅샷을
    무기한 붙든다 — 설계의 '한 원천이 죽어도 나머지는 뜬다'가 예외에는 성립하고
    행(hang)에는 성립하지 않는 자리였다.

    한계: 파이썬엔 스레드 강제종료가 없어 wait_for는 **스레드를 죽이지 못한다**.
    락을 풀고 응답을 돌려주는 것까지가 이 함수의 일이고, 매달린 스레드는 쿨다운당
    몇 개씩 새는 것을 감수한다(_FAIL_COOLDOWN이 그 유출 속도를 제한한다)."""
    return await asyncio.wait_for(asyncio.to_thread(fn, *args), _CALL_TIMEOUT)


def _cached(name: str) -> Optional[dict]:
    slot = _cache[name]
    if slot["data"] is not None and time.time() - slot["ts"] < _TTL[name]:
        return slot["data"]
    return None


def _cooling(name: str) -> bool:
    return (time.time() - _cache[name]["fail_ts"]
            < _COOLDOWN.get(name, _FAIL_COOLDOWN))


def _store(name: str, group: Optional[dict]) -> Optional[dict]:
    """성공은 캐시, 실패는 쿨다운 시각만 남긴다(실패는 캐시를 덮지 않는다)."""
    slot = _cache[name]
    if group is None:
        slot["fail_ts"] = time.time()
    else:            # 완료 시점 기준(TTL 온전) — 페치 소요만큼 TTL이 깎이지 않게
        slot["ts"], slot["data"], slot["fail_ts"] = time.time(), group, 0.0
    return group


def _to_date(v) -> Optional[dt.date]:
    """pandas Timestamp / datetime / 'YYYY-MM-DD…' 문자열 → date."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _num(v) -> Optional[float]:
    """숫자로 못 읽히거나 NaN이면 None — 0.0으로 뭉개면 결측이 값처럼 보인다."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # NaN 판정(math 임포트 없이)


def _rate_sign(value: float, prev: Optional[float]):
    """등락률(%)과 방향. 직전값이 없으면 (None, 'flat') — 0.00%로 꾸미지 않는다."""
    if not prev:
        return None, "flat"
    r = round((value - prev) / prev * 100, 2)
    return r, "up" if r > 0 else ("down" if r < 0 else "flat")


def _bp_sign(value: float, prev: Optional[float]):
    """금리 변화는 **bp**(1bp = 0.01%p). 직전값이 없으면 (None, 'flat').

    값 자체가 %인 그룹이라 등락까지 %로 내리면 화면이 "4.72% ▲1.51%"가 되고,
    금리가 1.51%p 뛴 것으로 읽힌다(실제로는 0.07%p = 7bp). 채권시장 관례가 bp이기도
    하다. 소수 1자리 — 0.1bp보다 잘게 보여줄 근거가 없다."""
    if prev is None:
        return None, "flat"
    bp = round((value - prev) * 100, 1)
    return bp, "up" if bp > 0 else ("down" if bp < 0 else "flat")


def _item(key, label, value, unit, rate, sign, basis, src, rate_unit="%",
          basis_kind="date") -> dict:
    """칩 하나 — 키 구성은 설계 문서의 Item + `rate_unit`·`basis_kind`(프런트 계약).

    `rate_unit`·`basis_kind`를 **데이터에 실는** 이유는 `unit`과 같다: 프런트가 등락
    단위나 신선도를 추측하기 시작하면 이 파일이 막으려는 사고가 렌더러에서 재발한다.

    basis_kind: "date"=그날 확정/마감값 / "live"=지금 움직이는 중.
    "live"여도 basis는 그대로 싣는다 — 폴백 경계에서 필드 모양이 바뀌지 않게."""
    return {"key": key, "label": label, "value": value, "unit": unit,
            "rate": rate, "sign": sign, "basis": basis, "src": src,
            "rate_unit": rate_unit, "basis_kind": basis_kind}


# ── CNBC 장중 미국금리(Tradeweb) ──────────────────────────────────────────
# 2026-08-12 한국 장중 실측: US2Y 4.222 / US10Y 4.69 / US30Y 5.24, 지연 약 30초,
# 재무부 확정치 대비 0~1bp. 값이 그만큼 가까워서 폴백해도 화면 숫자가 튀지 않는다.
# **심볼은 반드시 한 건씩** 부른다 — 여러 개 붙이면 에러가 아니라 last=null인 빈 응답이
# 조용히 온다(실측). 재배포 제약: Tradeweb 라이선스 피드라 야후보다 리스크가 크다 —
# 공개 전환 시 1순위 제거 대상이다(설계 문서 실측 2).

_CNBC_URL = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/"
             "symbol?symbols={sym}&requestMethod=itv&noform=1&partnerId=2"
             "&fund=1&exthrs=1&output=json&events=1")
# (key, label, CNBC 심볼) — key·label을 _TENORS와 **똑같이** 맞춘다. 폴백 경계에서
# 칩 자리가 바뀌면 원천이 바뀐 게 사용자에겐 칩이 움직인 것으로 보인다.
_CNBC_TENORS = (("ust2y", "2년", "US2Y"), ("ust10y", "10년", "US10Y"),
                ("ust30y", "30년", "US30Y"))
_YIELD_MIN, _YIELD_MAX = 0.0, 15.0


def _pct(v) -> Optional[float]:
    """'4.69%' → 4.69. %가 없어도 읽는다. 못 읽으면 None(0.0으로 뭉개지 않는다)."""
    if v is None:
        return None
    return _num(str(v).replace("%", "").replace(",", "").strip())


def parse_cnbc_yield(js: dict) -> Optional[dict]:
    """CNBC 단건 시세 → {'value','prev','basis'(date|None)}.

    범위 가드(0 < y < 15%)를 통과하지 못하면 None이다. 사설 API가 조용히 깨지는 것을
    전제로 짠다 — 실측에서 겪은 실패 모드가 예외가 아니라 `last: null`이었다."""
    rows = (((js or {}).get("FormattedQuoteResult") or {})
            .get("FormattedQuote") or [])
    if not rows:
        return None
    o = rows[0]
    value = _pct(o.get("last"))
    if value is None or not (_YIELD_MIN < value < _YIELD_MAX):
        return None
    try:                       # '2026-08-11T21:03:06.000-0400'
        basis = dt.date.fromisoformat(str(o.get("last_time") or "")[:10])
    except ValueError:
        basis = None
    return {"value": value, "prev": _pct(o.get("previous_day_closing")),
            "basis": basis}


def _fetch_cnbc(symbol: str) -> dict:
    """동기 HTTP — to_thread로 감싸 호출한다. 테스트는 이 지점을 갈아끼운다."""
    import requests
    r = requests.get(_CNBC_URL.format(sym=symbol), headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


async def _cnbc_items() -> list:
    """CNBC 3만기 — **한 건씩 순차**로 부른다(마스터 지시: 사설 API에 버스트 금지).

    _index_group이 KIS에 쓰는 것과 같은 _GAP 관례. 만기별로 시차를 두지는 않는다 —
    호출은 1/3로 줄지만 한 그룹 안에서 세 만기의 기준 시각이 섞이고, 금리 곡선은
    만기 간 관계를 보는 값이라 시각이 어긋나면 곡선 자체가 거짓이 된다."""
    items = []
    for i, (key, label, sym) in enumerate(_CNBC_TENORS):
        if i:
            await asyncio.sleep(_GAP)
        try:
            q = parse_cnbc_yield(await _blocking(_fetch_cnbc, sym))
        except Exception:
            log.warning("CNBC %s 실패 — 이 만기만 생략", sym, exc_info=True)
            q = None
        if not q:
            continue
        rate, sign = _bp_sign(q["value"], q["prev"])
        items.append(_item(key, label, q["value"], "%", rate, sign,
                           _mmdd(q["basis"]), "cnbc", rate_unit="bp",
                           basis_kind="live"))
    return items


# ── 미 재무부 일별 금리곡선 ────────────────────────────────────────────────

def parse_treasury(xml_text: str) -> list:
    """Atom 피드 → [{'date': date, '2Y':float|None, '10Y':…, '30Y':…}, …].

    피드 순서를 그대로 보존한다 — **마지막 엔트리가 최신**이다(실측). 날짜로 다시
    정렬하지 않는 이유는 그 관례를 계약으로 못 박아두기 위해서다. 월초엔 entry가 하나도
    없는 200 응답이 오므로 빈 리스트가 정상 결과다(호출부가 전월로 폴백)."""
    rows = []
    root = ET.fromstring(xml_text)
    for entry in root.findall("a:entry", _NS):
        props = entry.find("a:content/m:properties", _NS)
        if props is None:
            continue

        def field(name):
            el = props.find("d:" + name, _NS)
            return el.text if el is not None else None

        d = _to_date(field("NEW_DATE"))
        if d is None:
            continue
        rows.append({"date": d,
                     "2Y": _num(field("BC_2YEAR")),
                     "10Y": _num(field("BC_10YEAR")),
                     "30Y": _num(field("BC_30YEAR"))})
    return rows


def _fetch_treasury_xml(month: str) -> str:
    """동기 HTTP — to_thread로 감싸 호출한다. month='YYYYMM'."""
    import requests
    r = requests.get(_TREASURY_URL.format(month=month), headers=_UA,
                     timeout=_TIMEOUT)
    r.raise_for_status()
    return r.text


def _treasury_month_codes(today: dt.date) -> list:
    """조회할 달 — 이번 달, 그리고 월초 폴백용 전월.

    개수가 그룹 벽 부등식의 항이라(_GROUP_TIMEOUT 주석) 테스트가 이 함수에서 직접
    센다. 하드코딩한 '2'는 달을 하나 늘리는 날 조용히 틀린다 — 실제로 그렇게 틀렸다."""
    prev_month = today.replace(day=1) - dt.timedelta(days=1)
    return [today.strftime("%Y%m"), prev_month.strftime("%Y%m")]


async def _treasury_rows() -> list:
    """이번 달 → (비면/터지면) 전월. 월초 첫 영업일 전에는 이번 달 엔트리가 없다."""
    months = _treasury_month_codes(kst.today())
    for i, month in enumerate(months):
        try:
            rows = parse_treasury(await _blocking(_fetch_treasury_xml, month))
        except Exception:
            # 예외(404·타임아웃·XML 깨짐)도 '엔트리 없음'과 같은 폴백을 탄다 —
            # 여기서 그대로 올리면 월초에 전월을 영영 못 물어본다.
            log.warning("재무부 %s 조회 실패 — %s", month,
                        "전월 폴백" if i == 0 else "그룹 생략", exc_info=True)
            continue
        if rows:
            return rows
        log.info("재무부 %s 엔트리 없음 — 전월 폴백", month)
    return []


async def _treasury_group() -> Optional[dict]:
    """CNBC 우선 + 재무부 폴백.

    값이 0~1bp 차이라 원천이 바뀌어도 화면 숫자가 튀지 않는다 — 사용자에겐 신선도
    줄이 '실시간(지연)' ↔ '08-11 확정'으로 바뀌는 것으로만 보인다. 이 성질이 폴백
    설계를 정당화한다(값이 크게 달랐다면 원천을 섞을 수 없다)."""
    hit = _cached("treasury")
    if hit is not None or _cooling("treasury"):
        return hit
    # 미 채권장이 닫혀 있으면 CNBC를 **아예 안 부른다**. 절약이기 전에 더 정확하다 —
    # 시장이 닫혀 있으면 재무부 확정치가 애초에 맞는 값이다.
    items = []
    if cme_open():
        try:
            # 단계 상한 — 매달린 CNBC가 재무부 폴백 몫까지 먹지 못하게 한다.
            items = await asyncio.wait_for(_cnbc_items(), _CNBC_PHASE_TIMEOUT)
        except Exception:
            # 상한 초과도 '한 만기도 못 얻음'과 같은 폴백을 탄다. 단계가 잘리면 그때까지
            # 모은 만기도 버린다 — 그룹에 live/date를 섞지 않는다는 계약이 우선이다.
            log.warning("CNBC 단계 상한 초과 — 재무부로 폴백", exc_info=True)
            items = []
    if items:
        return _store("treasury", {"label": "미국 금리", "items": items})
    return _store("treasury", await _treasury_fallback())


async def _treasury_fallback() -> Optional[dict]:
    """재무부 확정치 — 폴백의 바닥. rows는 **별도 슬롯에 1시간** 캐시한다.

    같이 캐시하면 CNBC가 죽어 있는 동안 재무부를 10분마다 새로 두드리게 된다."""
    rows = _cached("treasury_rows")
    if rows is None:
        if _cooling("treasury_rows"):
            return None
        rows = _store("treasury_rows", (await _treasury_rows()) or None)
    if not rows:
        return None
    last, prev = rows[-1], (rows[-2] if len(rows) >= 2 else {})
    basis = _mmdd(last["date"])
    items = []
    for key, label, field in _TENORS:
        value = last.get(field)
        if value is None:
            continue
        rate, sign = _bp_sign(value, prev.get(field))
        items.append(_item(key, label, value, "%", rate, sign, basis, "treasury",
                           rate_unit="bp", basis_kind="date"))
    return {"label": "미국 금리", "items": items} if items else None


# ── FinanceDataReader 원자재 ──────────────────────────────────────────────

def parse_fdr_last(df) -> Optional[dict]:
    """FDR 일봉 → {'value','rate','sign','basis'(date)}. 마지막 유효 행 기준.

    **마지막 행은 종가가 아니라 진행 중 세션의 현재가다**(2026-08-12 실측: 90초 간격
    3회 호출에 금 4427.10 → 4428.20 → 4428.10). FDR `_validate_dates`의 end 기본값이
    자정이 아니라 `datetime.today()`(현재 시각)라 오늘 봉이 안 잘린다. 야후 분봉 교차
    확인 지연은 금 10.1분 / WTI 11.8분. 그런데 야후는 그 진행 중 봉에 **하루 전 날짜**를
    찍으므로 basis만 어제가 된다 — 그래서 화면 신선도는 basis가 아니라 basis_kind
    (cme_open)로 정한다. 등락률(직전 완료 세션 종가 대비 현재가)은 의미가 맞다.

    FDR은 거래일인데도 통째로 NaN인 행을 실제로 내보낸다(결측 — futures.pick_latest_pair
    가 같은 함정을 이미 기록해뒀다). 그 행은 값도 기준일도 쓰지 않는다. 유효 행이
    하나뿐이면 rate=None.

    값은 소수 2자리로 정규화한다 — FDR은 float32에서 승격된 값을 준다(2026-08-11 실호출:
    WTI 81.9800033569336, 금 4455.2998046875). 그대로 내리면 그 잡음이 API 응답과
    화면에 그대로 나간다. 등락률은 반올림 전 원값으로 계산한다."""
    if df is None or "Close" not in getattr(df, "columns", []):
        return None
    rows = []
    for idx, close in zip(list(df.index), list(df["Close"])):
        value = _num(close)
        if value is None:
            continue
        rows.append((_to_date(idx), value))
    if not rows:
        return None
    basis, value = rows[-1]
    rate, sign = _rate_sign(value, rows[-2][1] if len(rows) >= 2 else None)
    return {"value": round(value, 2), "rate": rate, "sign": sign, "basis": basis}


def _fetch_fdr(symbol: str, start: str):
    """FDR은 동기·블로킹 — to_thread로 감싸 이벤트루프를 막지 않는다.

    개인용 한정: CL=F·GC=F는 비공식 Yahoo 경유라 재배포 허가가 없다(나스닥 선물 칩과
    같은 제약). 앱을 공개로 열면 이 그룹은 제거 대상이다."""
    import FinanceDataReader as fdr
    return fdr.DataReader(symbol, start)


async def _commodity_group() -> Optional[dict]:
    hit = _cached("commodity")
    if hit is not None or _cooling("commodity"):
        return hit
    start = (kst.today()
             - dt.timedelta(days=_FDR_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    # 마지막 봉은 세션이 열려 있으면 '진행 중'이라 값이 현재가다(2026-08-12 실측:
    # 90초 간격 호출에 값이 계속 바뀐다). 닫혀 있으면 완료된 세션의 종가다.
    kind = "live" if cme_open() else "date"
    items = []
    for key, label, symbol, unit in _COMMODITIES:
        try:
            # 상한은 **심볼마다** 건다 — WTI를 먼저 await하므로, 그룹 단위로만 끊으면
            # CL=F 하나가 매달릴 때 금은 시도조차 못 한다(격리의 역방향이 깨진다).
            q = parse_fdr_last(await _blocking(_fetch_fdr, symbol, start))
        except Exception:
            log.warning("FDR %s 실패 — 이 칩만 생략", symbol, exc_info=True)
            q = None
        if not q:
            continue          # 종목 단위 격리 — 금이 죽어도 유가는 뜬다
        items.append(_item(key, label, q["value"], unit, q["rate"], q["sign"],
                           _mmdd(q["basis"]), "fdr", basis_kind=kind))
    return _store("commodity", {"label": "원자재", "items": items} if items
                  else None)


# ── KIS 해외지수 ──────────────────────────────────────────────────────────

def parse_index(js: dict) -> Optional[dict]:
    """FHKST03030100(div=N) → {'value','rate','sign','basis'(date|None)}.

    semi.parse_sox와 같은 TR이지만 반환 모양이 다르다 — 이 모듈은 기준일을 항목마다
    실어야 해서 output2의 stck_bsop_date까지 꺼낸다. output2는 실제로 비어 오는 종목이
    있어(SPX·COMP 실측) basis=None을 그대로 돌려주고, 폴백은 호출부가 정한다.

    등락률은 kis._f가 아니라 _num으로 읽는다. _f는 빈 문자열·필드 누락을 전부 0.0으로
    뭉개는데, 프런트는 rate==null일 때만 대시를 찍으므로 그 0.0이 '보합'으로 그려진다 —
    모르는 상태에서 '간밤 미국장 보합'이라는 없는 사실을 단언하게 된다. 값(value)이
    없으면 칩을 통째로 빼지만, 등락률만 모르는 건 칩을 뺄 이유가 아니다."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output1") or {}
    value = _num(o.get("ovrs_nmix_prpr"))
    if not value or value <= 0:
        return None
    basis = None
    rows = js.get("output2") or []
    if rows:
        try:
            basis = dt.datetime.strptime(
                str(rows[0].get("stck_bsop_date", "")), "%Y%m%d").date()
        except ValueError:
            basis = None
    rate = _num(o.get("prdy_ctrt"))
    # 등락률을 모르면 방향도 모른다 — _rate_sign의 (None, 'flat')과 같은 관례로 맞춘다.
    sign = _SIGN.get(str(o.get("prdy_vrss_sign", "")), "flat")
    return {"value": value, "rate": rate,
            "sign": sign if rate is not None else "flat", "basis": basis}


async def _index_group() -> Optional[dict]:
    hit = _cached("index")
    if hit is not None or _cooling("index"):
        return hit
    # 키 없음·데모는 여기서 걸러내지 않는다 — 그러면 클라이언트 주입(모킹) 지점보다
    # 앞에 게이트가 생겨 테스트/CI가 설정에 끌려간다. 키가 없으면 토큰 발급이 예외로
    # 떨어지고, 그건 아래 그룹 단위 실패 격리가 그대로 흡수한다.
    client = candles._get_client()        # 모듈 경유 — 테스트가 이 지점만 갈아끼운다
    # 조회 날짜·기준일 상한·폴백이 **한 함수**에서 나온다. 같은 TR·같은 순간의 응답인데
    # 항목마다 기준일 산출 경로가 다르면, 한 스냅샷에 두 날짜가 섞여 "VIX만 하루 더
    # 최신"으로 읽힌다. KST 오늘로 물으면 KST 00:00~13:00엔 ET로 아직 시작도 안 한
    # 날짜를 묻는 셈이라 조회 날짜도 여기서 가져온다(semi.py의 SOX는 output1만 쓰고
    # 기준일을 안 실어 kst.today()로 둔 것 — 이 모듈과 요구가 다르다).
    session = _last_us_session()
    day = session.strftime("%Y%m%d")
    kind = "live" if adr.us_market_open() else "date"
    items = []
    for i, (key, label, iscd) in enumerate(_INDICES):
        if i:
            await asyncio.sleep(_GAP)
        try:
            q = parse_index(await asyncio.wait_for(client._get(
                _IDX_PATH, _IDX_TR,
                {"FID_COND_MRKT_DIV_CODE": "N", "FID_INPUT_ISCD": iscd,
                 "FID_INPUT_DATE_1": day, "FID_INPUT_DATE_2": day,
                 "FID_PERIOD_DIV_CODE": "D"}), _CALL_TIMEOUT))
        except Exception:
            log.warning("KIS 해외지수 %s 실패 — 이 칩만 생략", iscd, exc_info=True)
            q = None
        if not q:
            continue
        # output2가 비어 오는 종목(SPX·COMP 실측)은 직전 세션으로 폴백하고, 있더라도
        # 직전 세션을 **넘지는** 못하게 한다: 픽스처 VIX의 output2 한 행은 OHLC가
        # output1과 글자 그대로 같은데 날짜만 조회일이다(같은 응답의 나스닥 누적거래량
        # 79억주 = 완료된 정규장 한 세션 → output1은 직전 세션 스냅샷). 상한이 없으면
        # 원천이 되비춘 조회 날짜가 그대로 화면 기준일이 된다. 더 이른 쪽이 이기는 건
        # 그대로다 — 휴장일처럼 원천이 진짜 세션을 알려주는 자리다.
        basis = min(q["basis"], session) if q["basis"] else session
        items.append(_item(key, label, q["value"], "idx", q["rate"], q["sign"],
                           _mmdd(basis), "kis", basis_kind=kind))
    return _store("index", {"label": "해외지수", "items": items} if items
                  else None)


# ── 한국 국채(토스 Open API) ──────────────────────────────────────────────

async def _krbond_group() -> Optional[dict]:
    """한국 국채 수익률 — 토스 Open API. KIS에도 없고 우리에게도 없던 자리다.

    미국 금리 칩 **바로 옆**에 놓는다(한·미 금리차를 눈으로 읽는 게 이 칩의 용도다).
    값은 %(수익률), 등락은 **bp** — 미국 금리 그룹과 완전히 같은 규칙(_bp_sign)을
    쓴다. 여기서만 %로 내리면 "2.73% ▲1.49%"가 되어 1.49%p 뛴 것으로 읽힌다.

    호출은 만기당 캔들 1콜(`interval=1d&count=2`)이다. 현재가 API
    (`/market-indicators/prices`)를 안 쓰는 이유: 그 응답은 symbol·timestamp·
    lastPrice뿐이라 **전일 대비가 없다** — 등락을 만들려면 어차피 캔들이 필요하고,
    그러면 콜 수가 두 배가 된다(2026-09-03 스펙 실사).

    키가 없으면 None을 돌려주되 **쿨다운에 태우지 않는다** — 기능이 꺼진 것이지
    원천이 실패한 게 아니다."""
    hit = _cached("krbond")
    if hit is not None or _cooling("krbond"):
        return hit
    client = toss.get_client()
    if client is None:
        return None
    items = []
    for key, label, symbol in _KR_TENORS:
        try:
            rows = await client.bond_candles(symbol, count=2)
        except Exception:
            # 만기 하나가 죽어도 나머지 칩은 뜬다(칩 단위 격리 — 이 파일의 원칙).
            log.warning("한국 금리 %s 실패 — 나머지만 반환", symbol, exc_info=True)
            continue
        if not rows:
            continue
        last = rows[-1]
        rate, sign = _bp_sign(last["close"],
                              rows[-2]["close"] if len(rows) >= 2 else None)
        basis = _to_date(last["date"])
        # 마지막 봉이 오늘이면 **진행 중일 수 있다**. 확정인지 장중값인지는 문서에
        # 없으므로(위 _TTL 주석) 추측하지 않고 날짜로만 판정한다 — FDR 일봉에서
        # 값은 실시간인데 라벨만 어제였던 전례가 있다(fdr 일봉 함정, parse_fdr_last).
        items.append(_item(key, label, last["close"], "%", rate, sign,
                           _mmdd(basis), "toss", rate_unit="bp",
                           basis_kind=("live" if basis == kst.today() else "date")))
    return _store("krbond",
                  {"label": "한국 금리", "items": items} if items else None)


# ── 집계 ──────────────────────────────────────────────────────────────────

def _payload(groups) -> dict:
    return {"asof": kst.now().replace(microsecond=0).isoformat(),
            "groups": [g for g in groups if g]}


def _active() -> tuple:
    """이번 폴링에서 돌릴 (이름, 그룹함수) — 화면 순서 그대로. 금리끼리 붙여 놓는다.

    토스 키가 없으면 한국 금리를 **목록에서 아예 뺀다**. 무조건 넣으면 그 슬롯이 영원히
    None이라 아래 '전부 신선하면 락을 안 잡는다' 최적화가 죽고, 아이폰+맥이 5분마다
    폴링하는 화면에서 락 경합이 상시화된다."""
    src = [("treasury", _treasury_group)]
    if toss.get_client() is not None:
        src.append(("krbond", _krbond_group))
    src += [("commodity", _commodity_group), ("index", _index_group)]
    return tuple(src)


async def get_worldidx() -> dict:
    """{'asof': ISO(KST), 'groups': [{'label','items':[Item,…]}, …]}.

    한 원천이 죽어도 나머지는 뜬다(대시보드 칩 스트립의 기존 원칙과 같다) — gather에
    return_exceptions=True를 걸어 예외를 그룹 하나의 생략으로 국소화한다. 전부 실패면
    groups=[]로 내려 화면이 섹션을 통째로 감춘다(빈 껍데기 금지).

    실패 시 직전 캐시를 '지연' 배지로 서빙하지 않는 것은 설계 확정 사항이다 —
    그 그룹만 생략한다. 대신 실패한 원천은 _FAIL_COOLDOWN 동안 다시 부르지 않는다.

    락은 세 원천 스윕이 겹치지 않게(아이폰+맥 동시 폴링) 잡되, 전부 신선하면 아예
    잡지 않는다 — 워밍된 응답까지 줄 세우면 느린 원천 하나가 전체 폴링을 막는다.
    호출부 주의: 콜드 상태에서 원천이 매달려 있으면 이 호출은 최대 _GROUP_TIMEOUT만큼
    (세 그룹은 동시에 도니 합이 아니다) 걸리고, 그동안 락을 잡고 있다. 상한을 안 걸면
    '한 원천이 죽어도 나머지는 뜬다'가 예외에만 성립하고 행(hang)에는 성립하지 않는다 —
    매달린 스레드가 락을 붙잡아 멀쩡한 원천까지 영영 갱신되지 않는다."""
    sources = _active()
    warm = [_cached(name) for name, _ in sources]
    if all(g is not None for g in warm):
        return _payload(warm)
    async with _get_lock():
        # 그룹 벽은 호출 단위 상한(_CALL_TIMEOUT)이 못 잡는 지연의 백스톱이다.
        # TimeoutError도 예외라 아래 실패 처리(쿨다운)를 그대로 탄다.
        results = await asyncio.gather(
            *(asyncio.wait_for(fn(), _GROUP_TIMEOUT) for _, fn in sources),
            return_exceptions=True)
    groups = []
    for (name, _), r in zip(sources, results):   # gather는 순서를 보존한다
        if isinstance(r, BaseException):
            # 그룹 함수 밖에서 터진 경우(예: KIS 클라이언트 생성 실패)도 쿨다운에 태운다.
            _cache[name]["fail_ts"] = time.time()
            log.warning("글로벌 지표 %s 실패 — 나머지만 반환", name, exc_info=r)
            continue
        if r:
            groups.append(r)
    return _payload(groups)
