from __future__ import annotations

"""한국투자증권(KIS) 오픈API 연동 — 실시간 수급용.

와이어 포맷은 공식 koreainvestment/open-trading-api 리포에서 검증(2026-07-10):
- 웹소켓 데이터 프레임: '0|TRID|N|f1^f2^...' (N개 레코드의 필드 연접, 시세 TR은 평문).
  JSON 프레임은 구독 ACK·PINGPONG. PINGPONG은 받은 원문 그대로 에코해야 한다.
- H0STCNT0(실시간 체결가) 46필드 · H0STPGM0(종목별 프로그램매매) 11필드.
파서는 전부 순수 함수로 두어 픽스처만으로 테스트한다(실연결 불필요).
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_RETRY_BASE_SEC = 0.5  # 5xx 재시도 시작 간격(지수 백오프)


# H0STCNT0 46필드 중 사용 인덱스 (필드 순서는 공식 샘플 ccnl_krx.py 기준)
_CCNL_FIELDS = 46
_PGM_FIELDS = 11

# PRDY_VRSS_SIGN: 1 상한 2 상승 3 보합 4 하한 5 하락
_SIGN = {"1": "up", "2": "up", "3": "flat", "4": "down", "5": "down"}
# CCLD_DVSN: 1 매수 3 장전 5 매도
_SIDE = {"1": "buy", "5": "sell"}


def _hhmmss(v: str) -> str:
    return f"{v[0:2]}:{v[2:4]}:{v[4:6]}" if len(v) >= 6 else v


def _i(v: str) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _f(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def split_frames(raw: str) -> Optional[tuple]:
    """웹소켓 수신 원문 → ('data', (tr_id, [record,...])) | ('json', dict) | None."""
    if raw[:2] in ("0|", "1|"):
        parts = raw.split("|", 3)
        if len(parts) != 4:
            return None
        tr_id, cnt_s, payload = parts[1], parts[2], parts[3]
        n = _i(cnt_s)
        fields = payload.split("^")
        if n <= 0 or len(fields) % n != 0:
            return None
        per = len(fields) // n
        return ("data", (tr_id, [fields[i * per:(i + 1) * per] for i in range(n)]))
    try:
        return ("json", json.loads(raw))
    except (json.JSONDecodeError, ValueError):
        return None


def is_pingpong(raw: str) -> bool:
    parsed = split_frames(raw)
    if not parsed or parsed[0] != "json":
        return False
    return parsed[1].get("header", {}).get("tr_id") == "PINGPONG"


def parse_ccnl(rec: list) -> dict:
    """H0STCNT0 레코드 → 체결 dict."""
    return {
        "t": _hhmmss(rec[1]),
        "price": _i(rec[2]),
        "sign": _SIGN.get(rec[3], ""),
        "change": _i(rec[4]),
        "rate": _f(rec[5]),
        "vol": _i(rec[12]),
        "acml_vol": _i(rec[13]),
        "acml_value": _i(rec[14]),
        "strength": _f(rec[18]),
        "side": _SIDE.get(rec[21], ""),
    }


def parse_program(rec: list) -> dict:
    """H0STPGM0 레코드 → 프로그램매매 dict.

    ⚠️ 값들은 당일 '누적' 체결량/대금이다(실측) — 이벤트별 증분이 아니다."""
    return {
        "t": _hhmmss(rec[1]),
        "sell_qty": _i(rec[2]),
        "sell_value": _i(rec[3]),
        "buy_qty": _i(rec[4]),
        "buy_value": _i(rec[5]),
        "net_qty": _i(rec[6]),
        "net_value": _i(rec[7]),
    }


def build_subscribe(approval_key: str, tr_id: str, code: str, on: bool = True) -> str:
    """웹소켓 구독(tr_type=1)/해지(0) 메시지."""
    return json.dumps({
        "header": {"approval_key": approval_key, "custtype": "P",
                   "tr_type": "1" if on else "0", "content-type": "utf-8"},
        "body": {"input": {"tr_id": tr_id, "tr_key": code}},
    })


# ─────────────────────────── REST ───────────────────────────

REST_BASE = "https://openapi.koreainvestment.com:9443"  # 실전 전용(수급 TR은 모의 미지원)
WS_URL = "ws://ops.koreainvestment.com:21000"

# HHPTJ04160200 bsop_hour_gb(입력구분) → 잠정치 기준 시각
_ESTIMATE_HOURS = {"1": "09:30", "2": "10:00", "3": "11:20", "4": "13:20", "5": "14:30"}


def _date(v: str) -> str:
    return f"{v[0:4]}-{v[4:6]}-{v[6:8]}" if len(v) == 8 else v


def parse_daily_investor(js: dict) -> list:
    """FHKST01010900(주식현재가 투자자) → [{date,prsn,frgn,orgn,close}] (일별 확정)."""
    rows = []
    for r in js.get("output") or []:
        rows.append({"date": _date(r.get("stck_bsop_date", "")),
                     "prsn": _i(r.get("prsn_ntby_qty")),
                     "frgn": _i(r.get("frgn_ntby_qty")),
                     "orgn": _i(r.get("orgn_ntby_qty")),
                     "close": _i(r.get("stck_clpr"))})
    return rows


def parse_estimate(js: dict) -> list:
    """HHPTJ04160200(외인기관 추정가집계) → [{asof,frgn,orgn,sum}] (장중 잠정).

    실API는 최신순으로 내려온다(2026-07-10 실측) → 시간 오름차순으로 정렬해
    '마지막 행=최신' 계약을 보장한다(UI·snapshot이 이에 의존)."""
    rows = []
    for r in js.get("output2") or []:
        gb = str(r.get("bsop_hour_gb", ""))
        rows.append({"asof": _ESTIMATE_HOURS.get(gb, gb),
                     "frgn": _i(r.get("frgn_fake_ntby_qty")),
                     "orgn": _i(r.get("orgn_fake_ntby_qty")),
                     "sum": _i(r.get("sum_fake_ntby_qty"))})
    rows.sort(key=lambda r: r["asof"])
    return rows


def parse_program_trend(js: dict) -> list:
    """FHPPG04650101(프로그램매매추이) → [{t,net_qty,net_value}] 누적 시계열(백필용).

    차트(setData)는 시간 오름차순을 요구 → API 순서와 무관하게 정렬해 보장한다."""
    pts = []
    for r in js.get("output") or []:
        pts.append({"t": _hhmmss(r.get("bsop_hour", "")),
                    "net_qty": _i(r.get("whol_smtn_ntby_qty")),
                    "net_value": _i(r.get("whol_smtn_ntby_tr_pbmn"))})
    pts.sort(key=lambda p: p["t"])
    return pts


# FHPTJ04160001 기관 세부 필드 — 사모·기타법인만 접미사가 _vol (실측 2026-07-10)
_DETAIL_FIELDS = [
    ("연기금", "fund_ntby_qty", "fund_ntby_tr_pbmn"),
    ("투신", "ivtr_ntby_qty", "ivtr_ntby_tr_pbmn"),
    ("금융투자", "scrt_ntby_qty", "scrt_ntby_tr_pbmn"),
    ("사모펀드", "pe_fund_ntby_vol", "pe_fund_ntby_tr_pbmn"),
    ("보험", "insu_ntby_qty", "insu_ntby_tr_pbmn"),
    ("은행", "bank_ntby_qty", "bank_ntby_tr_pbmn"),
    ("기타금융", "mrbn_ntby_qty", "mrbn_ntby_tr_pbmn"),
    ("기타법인", "etc_corp_ntby_vol", "etc_corp_ntby_tr_pbmn"),
]


def parse_investor_detail(js: dict) -> Optional[dict]:
    """FHPTJ04160001(종목별 투자자매매동향 일별) → 최신 확정일 기관 세부.

    {date, rows:[{name,qty(주),value(원)}]} — |순매수| 내림차순.
    장중 오늘 날짜 조회는 HTTP 200 + rt_cd=2('TIME LIMIT')로 오므로 rt_cd 확인 필수."""
    if js.get("rt_cd") != "0":
        return None
    out = js.get("output2") or []
    if not out:
        return None
    r = out[0]  # 최신 확정 거래일
    rows = [{"name": name, "qty": _i(r.get(qf)),
             "value": _i(r.get(vf)) * 1_000_000}  # 금액은 백만원 단위(실측)
            for name, qf, vf in _DETAIL_FIELDS]
    rows.sort(key=lambda x: abs(x["qty"]), reverse=True)
    return {"date": _date(r.get("stck_bsop_date", "")), "rows": rows}


def parse_minute_candles(js: dict) -> list:
    """FHKST03010200(주식당일분봉) output2 → [{t,open,high,low,close,vol}] 오름차순.

    실응답은 최신순·호출당 최대 30봉·당일만 제공(실측 2026-07-10)."""
    bars = []
    for r in js.get("output2") or []:
        bars.append({"t": _hhmmss(r.get("stck_cntg_hour", "")),
                     "open": _i(r.get("stck_oprc")), "high": _i(r.get("stck_hgpr")),
                     "low": _i(r.get("stck_lwpr")), "close": _i(r.get("stck_prpr")),
                     "vol": _i(r.get("cntg_vol"))})
    bars.sort(key=lambda b: b["t"])
    return bars


def drop_empty_daily(rows: list) -> list:
    """일별 확정에서 전부 0인 행 제거 — 당일분은 장 종료 전까지 0으로 내려와(실측)
    초보자가 '수급 없음'으로 오해한다. 확정된 날만 보여준다."""
    return [r for r in rows if r["prsn"] or r["frgn"] or r["orgn"]]


class KisClient:
    """토큰(디스크 캐시) + 수급 REST 3종. httpx 비동기, 실패는 예외로 위임."""

    def __init__(self, appkey: str, appsecret: str, cache_dir: str,
                 base: str = REST_BASE):
        self.appkey, self.appsecret, self.base = appkey, appsecret, base
        self._token_path = Path(cache_dir) / "kis_token.json"
        self._approval: Optional[str] = None

    # 토큰은 24h 유효·발급 1회/분 제한 + 매 발급마다 알림톡 → 캐시가 필수다.
    async def token(self) -> str:
        try:
            c = json.loads(self._token_path.read_text(encoding="utf-8"))
            if c.get("token") and c.get("expires_at", 0) > time.time() + 60:
                return c["token"]
        except (OSError, ValueError):
            pass
        js = await self._issue_token()
        tok = js["access_token"]
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(json.dumps(
            {"token": tok, "expires_at": time.time() + int(js.get("expires_in", 86400))}
        ), encoding="utf-8")
        return tok

    async def _issue_token(self) -> dict:
        import httpx
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.post(f"{self.base}/oauth2/tokenP", json={
                "grant_type": "client_credentials",
                "appkey": self.appkey, "appsecret": self.appsecret})
            r.raise_for_status()
            js = r.json()
        if "access_token" not in js:
            raise RuntimeError(f"KIS 토큰 발급 실패: {js}")
        return js

    async def approval_key(self) -> str:
        if self._approval:
            return self._approval
        import httpx
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.post(f"{self.base}/oauth2/Approval", json={
                "grant_type": "client_credentials",
                "appkey": self.appkey, "secretkey": self.appsecret})  # 필드명 secretkey!
            r.raise_for_status()
            js = r.json()
        key = js.get("approval_key")
        if not key:
            raise RuntimeError(f"KIS approval_key 발급 실패: {js}")
        self._approval = key
        return key

    def _client_factory(self):
        import httpx
        return httpx.AsyncClient(timeout=10)

    async def _get(self, path: str, tr_id: str, params: dict,
                   retries: int = 2) -> dict:
        """KIS는 연속 호출에 간헐 HTTP 500을 반환(실측) → 지수 백오프 재시도."""
        headers = {"authorization": f"Bearer {await self.token()}",
                   "appkey": self.appkey, "appsecret": self.appsecret,
                   "tr_id": tr_id, "custtype": "P"}
        delay = _RETRY_BASE_SEC
        async with self._client_factory() as cli:
            for attempt in range(retries + 1):
                r = await cli.get(f"{self.base}{path}", headers=headers,
                                  params=params)
                if r.status_code >= 500 and attempt < retries:
                    log.debug("KIS %s HTTP %d — %.1fs 후 재시도", tr_id,
                              r.status_code, delay)
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                r.raise_for_status()
                return r.json()

    async def daily_investor(self, code: str) -> list:
        js = await self._get("/uapi/domestic-stock/v1/quotations/inquire-investor",
                             "FHKST01010900",
                             {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        return parse_daily_investor(js)

    async def estimate(self, code: str) -> list:
        js = await self._get("/uapi/domestic-stock/v1/quotations/investor-trend-estimate",
                             "HHPTJ04160200", {"MKSC_SHRN_ISCD": code})
        return parse_estimate(js)

    async def investor_detail(self, code: str) -> Optional[dict]:
        """최신 확정일 기관 세부 분해. 장중엔 오늘 날짜가 rt_cd=2로 거부되므로 전일 폴백."""
        import datetime as dt
        for delta in (0, 1):
            date = (dt.date.today() - dt.timedelta(days=delta)).strftime("%Y%m%d")
            js = await self._get(
                "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily",
                "FHPTJ04160001",
                {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                 "FID_INPUT_DATE_1": date, "FID_ORG_ADJ_PRC": "",
                 "FID_ETC_CLS_CODE": ""})
            d = parse_investor_detail(js)
            if d:
                return d
        return None

    async def program_trend(self, code: str) -> list:
        js = await self._get("/uapi/domestic-stock/v1/quotations/program-trade-by-stock",
                             "FHPPG04650101",
                             {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        return parse_program_trend(js)
