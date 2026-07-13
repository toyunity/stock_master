from __future__ import annotations

"""대차잔고(주식 대여 잔고) 수집 — 공매도 선행지표, T+1 일 단위 공시.

소스(실측 2026-07-13; KRX 정보데이터시스템은 2025-12-27 로그인 월로 익명 400 'LOGOUT',
OTP 다운로드 경로도 차단 확인 → 제외):
- 1차 KOFIA 종합통계(freesis.kofia.or.kr): 뉴스가 인용하는 '금투협 대차잔고'.
  getMetaDataList.do JSON POST, 무인증. 단면 조회라 하루당 1콜(시장 전체 ~1,000행).
  tmpV74는 반드시 "시장,0,,1" 4필드 패킹 — "1"만 보내면 HTTP 200에 빈 ds1(무증상 실패).
- 폴백 SEIBro(예탁결제원): 기간 조회 1콜로 임의 구간 히스토리. isin 파라미터에
  6자리 단축코드를 넣어야 한다(정식 ISIN은 무증상 0행). 잔고금액 컬럼이 없어
  주수×종가로 산출. 협회보다 집계 범위가 좁아 절대 수치가 다르므로(07-10 실측
  14.1M vs 11.1M주) 행마다 출처를 태그하고 이종 소스 사이의 전일 대비는 계산하지 않는다.

프록시: httpx는 기본 trust_env=True → 회사망 등에서는 HTTP_PROXY/HTTPS_PROXY
환경변수만 설정하면 그대로 반영된다.
"""

import asyncio
import datetime as dt
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_KOFIA_URL = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
_KOFIA_OBJ = "STATSCU0100000130BO"  # 주식 > 대차거래 > 대차거래내역
_SEIBRO_URL = ("https://seibro.or.kr/websquare/engine/proworks/"
               "callServletService.jsp")
_HEADERS = {  # 크롤링 차단 회피가 아니라 브라우저와 동일한 정상 요청임을 표시
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
}

_SPACING_SEC = 1.2   # KOFIA 백필 시 호출 간격(무료 공공 포털 예의)
_RETRY_SEC = 3600    # 원격 재시도 간격 — 엔진은 매분 문의하지만 이 스로틀이 1회/시로 제한
_BACKFILL_SCAN = 28  # 백필 시 훑는 평일 수 상한(휴일 감안해 20행 확보용)
_CACHE_KEEP = 30     # 캐시 보존 행 하한 — CLI --days가 작아도 서버(20일) 몫을 지운다(리뷰)
_last_try: dict = {}  # code → 마지막 원격 '시도' 시각(실패 포함; fetched는 성공 전용)


# ── 순수 파서/계산 (픽스처만으로 테스트) ──────────────────────

def parse_kofia(js: dict, code: str) -> Optional[dict]:
    """getMetaDataList.do 응답에서 종목 행 추출 → {qty(주), value(원)}.

    ds1 행: TMPV1 종목명 TMPV2 코드 TMPV3 체결 TMPV4 상환 TMPV5 잔고주수 TMPV6 잔고금액."""
    for r in js.get("ds1") or []:
        if str(r.get("TMPV2", "")) == code:
            return {"qty": int(r.get("TMPV5") or 0),
                    "value": int(r.get("TMPV6") or 0)}
    return None


def parse_seibro(text: str) -> list:
    """stksecnslbPList XML → [{date,qty,value,close}] 날짜 오름차순.

    <vector><data><result><STD_DT value=.../>…</result></data>…</vector> 구조.
    REM_AMT가 (이름과 달리) '잔고 주수'다 — 화면 그리드 매핑으로 확인.
    잔고금액 컬럼은 없어 주수×종가(CPRI)로 산출한다."""
    rows = []
    for res in ET.fromstring(text).iter("result"):
        f = {c.tag: c.attrib.get("value", "") for c in res}
        d, qty, close = f.get("STD_DT", ""), f.get("REM_AMT"), f.get("CPRI")
        if len(d) != 8 or qty in (None, ""):
            continue
        qty_i, close_i = int(qty), int(close or 0)
        rows.append({"date": f"{d[0:4]}-{d[4:6]}-{d[6:8]}", "qty": qty_i,
                     "value": qty_i * close_i, "close": close_i})
    rows.sort(key=lambda r: r["date"])
    return rows


def with_changes(rows: list) -> list:
    """날짜 오름차순 정렬 + 전일 대비(chg) 계산. 출처가 다른 인접 행 사이는
    집계 범위가 달라 차이가 무의미하므로 chg=None."""
    rows = sorted(rows, key=lambda r: r["date"])
    out = []
    for i, r in enumerate(rows):
        chg = None
        if i > 0 and rows[i - 1].get("src") == r.get("src"):
            chg = r["qty"] - rows[i - 1]["qty"]
        out.append(dict(r, chg=chg))
    return out


def short_signal(price_rate: Optional[float],
                 chg_qty: Optional[int]) -> Optional[dict]:
    """당일 주가 등락 × 대차잔고 전일 증감 → 4분면 판정 {text, tone}.

    tone: good(긍정)/warn(경계)/info(참고)/flat(중립) — UI 색상 매핑용."""
    if price_rate is None or chg_qty is None:
        return None
    if price_rate > 0 and chg_qty < 0:
        return {"text": "건강한 상승 (숏 이탈)", "tone": "good"}
    if price_rate > 0 and chg_qty > 0:
        return {"text": "상승 중 숏 축적 (경계)", "tone": "warn"}
    if price_rate < 0 and chg_qty > 0:
        return {"text": "하락 베팅 강화 (경계)", "tone": "warn"}
    if price_rate < 0 and chg_qty < 0:
        return {"text": "숏커버링 가능 구간", "tone": "info"}
    return {"text": "중립 — 뚜렷한 신호 없음", "tone": "flat"}


def expected_latest(today: dt.date) -> dt.date:
    """오늘 기준 '있어야 할' 최신 공시일 = 직전 평일(T+1 공시)."""
    d = today - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


# ── 원격 조회 (엔진/CLI에서만 호출; 테스트는 monkeypatch) ──────

async def _kofia_day(cli, date: dt.date, market: str) -> dict:
    """하루치 시장 단면. market: '1' KOSPI, '2' KOSDAQ."""
    d = date.strftime("%Y%m%d")
    body = {"dmSearch": {"OBJ_NM": _KOFIA_OBJ, "tmpV1": "D",
                         "tmpV45": d, "tmpV46": d,
                         "tmpV74": f"{market},0,,1",
                         "tmpV40": "1", "tmpV41": "1"}}
    r = await cli.post(_KOFIA_URL, json=body,
                       headers=dict(_HEADERS, Referer="https://freesis.kofia.or.kr/"))
    r.raise_for_status()
    return r.json()


async def _seibro_range(cli, code: str, start: dt.date, end: dt.date) -> str:
    body = ('<reqParam action="stksecnslbPList" '
            'task="ksd.safe.bip.cnts.Loan.process.StkSecnSlbPTask">'
            f'<isin value="{code}"/>'
            f'<start_date value="{start.strftime("%Y%m%d")}"/>'
            f'<end_date value="{end.strftime("%Y%m%d")}"/>'
            '<START_PAGE value="1"/><END_PAGE value="250"/>'
            '<MENU_NO value="222"/>'
            '<W2XPATH value="/IPORTAL/user/loan/BIP_CNTS08003V.xml"/>'
            '</reqParam>')
    r = await cli.post(_SEIBRO_URL, content=body.encode("utf-8"),
                       headers=dict(_HEADERS,
                                    **{"Content-Type": "application/xml; charset=UTF-8",
                                       "Referer": "https://seibro.or.kr/"}))
    r.raise_for_status()
    return r.text


async def _fetch_kofia(cli, code: str, need_dates: list,
                       market: Optional[str]) -> tuple:
    """필요 일자들을 하루씩 조회 → (rows, market). 휴일(행 없음)은 건너뜀.

    시장 미확정이면 KOSPI→KOSDAQ 순으로 시도해 처음 발견된 쪽으로 고정.
    3일 연속 양쪽 모두에 없으면 상장 폐지/코드 오류로 보고 포기."""
    rows, misses = [], 0
    for i, d in enumerate(need_dates):
        if i:
            await asyncio.sleep(_SPACING_SEC)
        try:
            found = None
            for mkt in ([market] if market else ["1", "2"]):
                js = await _kofia_day(cli, d, mkt)
                got = parse_kofia(js, code)
                if got:
                    found, market = got, mkt
                    break
        except Exception:
            if rows:  # 중간 실패는 수집분 보존 — 나머지는 다음 스로틀 주기에 이어감
                log.warning("KOFIA %s 조회 중단 — 기수집 %d행 보존", d, len(rows),
                            exc_info=True)
                break
            raise  # 한 행도 못 얻었으면 SEIBro 폴백으로
        if found:
            rows.append({"date": d.isoformat(), "qty": found["qty"],
                         "value": found["value"], "src": "kofia"})
            misses = 0
        else:
            misses += 1
            if misses >= 3 and not rows and market is None:
                raise RuntimeError(f"KOFIA에 {code} 없음(3일 연속)")
    return rows, market


def _load_cache(path: Path) -> dict:
    try:
        c = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(c, dict) and isinstance(c.get("rows"), list):
            return c
    except (OSError, ValueError):
        pass
    return {"fetched": None, "market": None, "rows": []}


async def get_history(code: str, cache_dir: str, days: int = 20) -> dict:
    """최근 N거래일 대차잔고 — 일 단위 캐시, 실패 시 폴백/이전 캐시 유지.

    반환: {rows:[{date,qty,value,chg,src}…오름차순], asof, source, updated}.
    rows가 비면 '데이터 없음'(수집 실패·미공시)이며 화면은 죽지 않아야 한다."""
    path = Path(cache_dir) / f"shortbal_{code}.json"
    cache = _load_cache(path)
    rows = {r["date"]: r for r in cache["rows"]}
    today = dt.date.today()
    exp = expected_latest(today)

    def result() -> dict:
        out = with_changes(list(rows.values()))[-days:]
        return {"rows": out,
                "asof": out[-1]["date"] if out else None,
                "source": out[-1]["src"] if out else None,
                "updated": cache.get("fetched")}

    if rows and max(rows) >= exp.isoformat():
        return result()  # 오늘 몫(직전 평일분)까지 확보됨
    # 재시도 스로틀 — '실패 포함' 마지막 시도 기준(메모리). 실패 시 fetched를 안
    # 찍는 설계라 fetched만 보면 총실패 때 매분 원격 재시도가 됐다(리뷰 확정).
    last_try = _last_try.get(code)
    if last_try is None:
        try:
            last_try = dt.datetime.fromisoformat(cache.get("fetched") or "")
        except ValueError:
            last_try = None
    if last_try and (dt.datetime.now() - last_try).total_seconds() < _RETRY_SEC:
        return result()
    _last_try[code] = dt.datetime.now()

    # 필요 일자: 캐시 다음 날부터 직전 평일까지(빈 캐시면 백필 스캔 구간)
    scan = min(_BACKFILL_SCAN, days + 8)  # 휴일 감안 여유분(하루 1콜이라 예의상 상한)
    start = (dt.date.fromisoformat(max(rows)) + dt.timedelta(days=1)) if rows \
        else exp - dt.timedelta(days=scan * 7 // 5)
    need = []
    d = exp
    while d >= start and len(need) < scan:
        if d.weekday() < 5:
            need.append(d)
        d -= dt.timedelta(days=1)
    need.reverse()

    import httpx
    market = cache.get("market")
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            try:
                got, market = await _fetch_kofia(cli, code, need, market)
            except Exception:
                log.warning("KOFIA 대차잔고 조회 실패 — SEIBro 폴백", exc_info=True)
                got = [r for r in parse_seibro(
                    await _seibro_range(cli, code, need[0], need[-1]))
                    if r["date"] not in rows]
                got = [{"date": r["date"], "qty": r["qty"],
                        "value": r["value"], "src": "seibro"} for r in got]
        for r in got:
            rows[r["date"]] = r
        cache["fetched"] = dt.datetime.now().isoformat(timespec="seconds")
        cache["market"] = market
        cache["rows"] = with_changes(list(rows.values()))[-max(days + 10, _CACHE_KEEP):]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")  # 원자 교체 — CLI·서버 동시 쓰기 찢김 방지
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        # 양쪽 모두 실패 — 이전 캐시로 화면 유지('데이터 없음' 또는 옛 asof 표시)
        log.warning("대차잔고 수집 실패(KOFIA·SEIBro) — 캐시 유지", exc_info=True)
    return result()
