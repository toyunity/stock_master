from __future__ import annotations

"""한국투자증권(KIS) 오픈API 연동 — 실시간 수급용.

와이어 포맷은 공식 koreainvestment/open-trading-api 리포에서 검증(2026-07-10):
- 웹소켓 데이터 프레임: '0|TRID|N|f1^f2^...' (N개 레코드의 필드 연접, 시세 TR은 평문).
  JSON 프레임은 구독 ACK·PINGPONG. PINGPONG은 받은 원문 그대로 에코해야 한다.
- H0STCNT0(실시간 체결가) 46필드 · H0STPGM0(종목별 프로그램매매) 11필드.
파서는 전부 순수 함수로 두어 픽스처만으로 테스트한다(실연결 불필요).
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


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
    """H0STPGM0 레코드 → 프로그램매매 dict."""
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
    """HHPTJ04160200(외인기관 추정가집계) → [{asof,frgn,orgn,sum}] (장중 잠정)."""
    rows = []
    for r in js.get("output2") or []:
        gb = str(r.get("bsop_hour_gb", ""))
        rows.append({"asof": _ESTIMATE_HOURS.get(gb, gb),
                     "frgn": _i(r.get("frgn_fake_ntby_qty")),
                     "orgn": _i(r.get("orgn_fake_ntby_qty")),
                     "sum": _i(r.get("sum_fake_ntby_qty"))})
    return rows


def parse_program_trend(js: dict) -> list:
    """FHPPG04650101(프로그램매매추이) → [{t,net_qty,net_value}] 누적 시계열(백필용)."""
    pts = []
    for r in js.get("output") or []:
        pts.append({"t": _hhmmss(r.get("bsop_hour", "")),
                    "net_qty": _i(r.get("whol_smtn_ntby_qty")),
                    "net_value": _i(r.get("whol_smtn_ntby_tr_pbmn"))})
    return pts


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

    async def _get(self, path: str, tr_id: str, params: dict) -> dict:
        import httpx
        headers = {"authorization": f"Bearer {await self.token()}",
                   "appkey": self.appkey, "appsecret": self.appsecret,
                   "tr_id": tr_id, "custtype": "P"}
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.get(f"{self.base}{path}", headers=headers, params=params)
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

    async def program_trend(self, code: str) -> list:
        js = await self._get("/uapi/domestic-stock/v1/quotations/program-trade-by-stock",
                             "FHPPG04650101",
                             {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        return parse_program_trend(js)
