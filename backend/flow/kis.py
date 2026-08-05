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


def subscribe_error(obj: dict) -> Optional[str]:
    """구독 ACK(JSON)의 실패 메시지. 성공(rt_cd 0)·PINGPONG·기타 정보성이면 None.

    실측(2026-07-10): 이전 프로세스의 좀비 세션이 남아 있으면 rt_cd=9
    OPSP8996 'ALREADY IN USE...'가 오고 서버가 곧바로 연결을 끊는다."""
    body = obj.get("body") or {}
    rt = str(body.get("rt_cd", ""))
    if rt in ("", "0"):
        return None
    return f"{body.get('msg_cd', '')} {body.get('msg1', '')}".strip()


def is_invalid_approval(err: Optional[str]) -> bool:
    """구독 거부가 '승인키 무효'(OPSP0011)인가 — 좀비 세션(ALREADY/OPSP8996)과 구분한다.

    승인키(approval_key)는 커넥션 수명 동안만 메모리 보관되는데, KIS는 일정 시간(≈1일) 뒤
    이를 무효화하고 rt_cd=9 OPSP0011 'invalid approval'을 반환한다(실측 2026-07-22 — 캐시된
    무효 키로 3898회 재접속 실패). 이 경우엔 캐시를 비워 재발급해야 복구되고, 좀비 세션은
    새 승인키로 낫지 않으므로 대기만 한다."""
    e = (err or "").lower()
    return "opsp0011" in e or "invalid approval" in e


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

# 시장구분 → 실시간 (체결가, 프로그램) TR — 필드 배열은 세 변형 모두 동일(공식 리포 검증)
_WS_TRS = {"J": ("H0STCNT0", "H0STPGM0"), "NX": ("H0NXCNT0", "H0NXPGM0"),
           "UN": ("H0UNCNT0", "H0UNPGM0")}


def ws_tr_ids(div: str) -> tuple:
    return _WS_TRS.get(div, _WS_TRS["UN"])


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


def parse_price(js: dict) -> Optional[dict]:
    """FHKST01010100(주식현재가 시세) → 시세 요약. 웹소켓 공백 시 폴백용."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output") or {}
    return {"price": _i(o.get("stck_prpr")),
            "sign": _SIGN.get(str(o.get("prdy_vrss_sign", "")), ""),
            "change": _i(o.get("prdy_vrss")), "rate": _f(o.get("prdy_ctrt")),
            "acml_vol": _i(o.get("acml_vol")),
            "acml_value": _i(o.get("acml_tr_pbmn"))}


def parse_fundamentals(js: dict) -> Optional[dict]:
    """FHKST01010100(주식현재가 시세) output의 밸류 지표 → {per,pbr,eps,bps,w52_high,
    w52_low,w52_pos}. parse_price(시세 요약)와 같은 응답이지만 관심사가 달라 분리한다
    (parse_price는 웹소켓 공백 폴백 전용). 빈값/0인 per·pbr은 None, 적자 eps는 음수 유지."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output") or {}

    def _pos(v):                       # 빈문자/0 → None (per·pbr는 0이 무의미)
        f = _f(v)
        return f if f > 0 else None

    price = _i(o.get("stck_prpr"))
    hi, lo = _i(o.get("w52_hgpr")), _i(o.get("w52_lwpr"))
    pos = round((price - lo) / (hi - lo) * 100, 1) if hi > lo and price else None
    return {"per": _pos(o.get("per")), "pbr": _pos(o.get("pbr")),
            "eps": _f(o.get("eps")) or None, "bps": _f(o.get("bps")) or None,
            "w52_high": hi or None, "w52_low": lo or None, "w52_pos": pos}


def parse_top_view(js: dict) -> list:
    """hts-top-view(HHMCM000100C0) → 조회상위 종목코드 배열(순위순). 코드만 옴(이름 없음)
    → 상위에서 universe로 이름 조인. 실패는 []."""
    if js.get("rt_cd") != "0":
        return []
    rows = js.get("output1") or js.get("output") or []
    out = []
    for r in rows:
        c = str(r.get("mksc_shrn_iscd", "")).strip()
        if c:
            out.append(c)
    return out


def parse_asking(js: dict) -> Optional[dict]:
    """inquire-asking-price-exp-ccn(output1) → {asks,bids(각 price/qty 사다리),total_ask,
    total_bid,bid_ratio}. 실시간 H0STASP0와 동일 데이터의 REST 스냅샷(WS 세션 회피)."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output1") or {}

    def ladder(pfx):
        out = []
        for i in range(1, 11):
            p = _i(o.get("%sp%d" % (pfx, i)))
            if p <= 0:
                break                                 # 빈 상위 레벨에서 중단
            out.append({"price": p, "qty": _i(o.get("%sp_rsqn%d" % (pfx, i)))})
        return out

    ta, tb = _i(o.get("total_askp_rsqn")), _i(o.get("total_bidp_rsqn"))
    ratio = round(tb / (ta + tb) * 100, 1) if (ta + tb) > 0 else None
    return {"asks": ladder("ask"), "bids": ladder("bid"),
            "total_ask": ta, "total_bid": tb, "bid_ratio": ratio}


def parse_index(js: dict) -> Optional[dict]:
    """inquire-index-price(FHPUP02100000) → {price,change,rate,sign}. 코스피/코스닥 지수."""
    if js.get("rt_cd") != "0":
        return None
    o = js.get("output") or {}
    return {"price": _f(o.get("bstp_nmix_prpr")),
            "change": _f(o.get("bstp_nmix_prdy_vrss")),
            "rate": _f(o.get("bstp_nmix_prdy_ctrt")),
            "sign": _SIGN.get(str(o.get("prdy_vrss_sign", "")), "")}


def parse_financials(js: dict) -> list:
    """financial-ratio(FHKST66430300) output → 최근 분기 배열(신순). 초보용 핵심만:
    period(YYYY-MM)·roe·eps·debt(부채비율)·sales_growth(매출성장률). 실패는 []."""
    if js.get("rt_cd") != "0":
        return []
    out = []
    for r in js.get("output") or []:
        ym = str(r.get("stac_yymm", ""))
        period = (ym[:4] + "-" + ym[4:6]) if len(ym) >= 6 else ym
        out.append({"period": period, "roe": _f(r.get("roe_val")),
                    "eps": _f(r.get("eps")), "debt": _f(r.get("lblt_rate")),
                    "sales_growth": _f(r.get("grs"))})
    return out


def parse_latest_trade_date(js: dict):
    """FHKST01010400(일자별 시세) output 첫 행 stck_bsop_date → 'YYYY-MM-DD'.

    위젯의 open/asof 판정용 — 최신 행이 곧 최신 거래일이다(공휴일이면 전 거래일).
    형식 불량/실패는 None(호출부가 벽시계로 폴백)."""
    if js.get("rt_cd") != "0":
        return None
    rows = js.get("output") or []
    d = str((rows[0] if rows else {}).get("stck_bsop_date") or "")
    if len(d) != 8 or not d.isdigit():
        return None
    return "%s-%s-%s" % (d[:4], d[4:6], d[6:])


def parse_minute_candles(js: dict, date: Optional[str] = None) -> list:
    """FHKST03010200(주식당일분봉) output2 → [{t,open,high,low,close,vol}] 오름차순.

    실응답은 최신순·호출당 최대 30봉(실측 2026-07-10). date(YYYYMMDD)를 주면
    다른 날짜 행을 제거한다 — 마감 후 조회에서 KIS가 전일 봉을 같은 시각
    라벨로 '간헐적으로' 되감아 반환(실사고 2026-07-13 21:53: 금요일 19:5x
    2,20만원대 봉이 월요일 −16% 차트 꼬리에 급반등처럼 붙음)."""
    bars = []
    for r in js.get("output2") or []:
        d = str(r.get("stck_bsop_date", ""))
        if date and d and d != date:
            continue
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
                 base: str = REST_BASE, market_div: str = "UN"):
        self.appkey, self.appsecret, self.base = appkey, appsecret, base
        self.div = market_div  # UN=KRX+NXT 통합(기본), J=KRX 전용, NX=NXT 전용
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

    def reset_approval(self) -> None:
        """무효 승인키(OPSP0011)를 폐기 — 다음 approval_key()가 /oauth2/Approval로 재발급한다.

        승인키는 파일 캐시가 아니라 메모리(self._approval)에만 있어, 만료 시 이 리셋이 유일한
        재발급 경로다. WS 재접속 루프가 OPSP0011을 만나면 호출한다(wsbus.WsSession._run)."""
        self._approval = None

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
                             {"FID_COND_MRKT_DIV_CODE": self.div, "FID_INPUT_ISCD": code})
        return parse_daily_investor(js)

    async def estimate(self, code: str) -> list:
        js = await self._get("/uapi/domestic-stock/v1/quotations/investor-trend-estimate",
                             "HHPTJ04160200", {"MKSC_SHRN_ISCD": code})
        return parse_estimate(js)

    async def price(self, code: str) -> Optional[dict]:
        js = await self._get("/uapi/domestic-stock/v1/quotations/inquire-price",
                             "FHKST01010100",
                             {"FID_COND_MRKT_DIV_CODE": self.div, "FID_INPUT_ISCD": code})
        return parse_price(js)

    async def fundamentals(self, code: str) -> Optional[dict]:
        """밸류 지표(PER/PBR/EPS/BPS/52주) — price()와 같은 TR이지만 관심사가 달라 분리 조회.
        시세와 달리 일 단위로만 바뀌므로 상위에서 길게 캐시(대시보드/상세용)."""
        js = await self._get("/uapi/domestic-stock/v1/quotations/inquire-price",
                             "FHKST01010100",
                             {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        return parse_fundamentals(js)

    async def top_view(self) -> list:
        """조회상위(HTS 기준 많이 본 종목) 코드 배열 — 발굴용. 이름은 상위에서 조인."""
        js = await self._get("/uapi/domestic-stock/v1/ranking/hts-top-view",
                             "HHMCM000100C0", {})
        return parse_top_view(js)

    async def asking_price(self, code: str) -> Optional[dict]:
        """호가 사다리 스냅샷(REST) — 실시간 H0STASP0 대신(1키1세션 회피). /live 폴링용."""
        js = await self._get("/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
                             "FHKST01010200",
                             {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        return parse_asking(js)

    async def index(self, iscd: str = "0001") -> Optional[dict]:
        """지수 시세 — 코스피(0001)/코스닥(1001)/코스피200(2001)."""
        js = await self._get("/uapi/domestic-stock/v1/quotations/inquire-index-price",
                             "FHPUP02100000",
                             {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": iscd})
        return parse_index(js)

    async def futures_board(self, cls_code: str) -> list:
        """지수선물 전광판 — 월물 목록과 시세가 한 콜에 같이 온다(FHPIF05030200).
        cls_code: ""=정규(대형), MKI=미니(G1 실측 확정, 2026-07-31)."""
        from backend.flow import futures as _fx      # 순환 임포트 회피(모듈 로드 시점 분리)
        js = await self._get("/uapi/domestic-futureoption/v1/quotations/display-board-futures",
                             "FHPIF05030200",
                             {"FID_COND_MRKT_DIV_CODE": "F",
                              "FID_COND_SCR_DIV_CODE": "20503",
                              "FID_COND_MRKT_CLS_CODE": cls_code})
        return _fx.parse_board(js)

    async def financials(self, code: str) -> list:
        """재무비율(최근 분기 신순) — ROE·EPS·부채비율·매출성장. 분기 갱신이라 길게 캐시."""
        js = await self._get("/uapi/domestic-stock/v1/finance/financial-ratio",
                             "FHKST66430300",
                             {"FID_DIV_CLS_CODE": "0", "fid_cond_mrkt_div_code": "J",
                              "fid_input_iscd": code})
        return parse_financials(js)

    async def latest_trade_date(self, code: str = "005930"):
        """최신 거래일(YYYY-MM-DD) — 일자별 시세 첫 행. 위젯 장상태 판정용.

        div는 J 고정: 거래일은 거래소 공통이고 이 TR의 UN 지원이 불확실(실측 전 안전값)."""
        js = await self._get("/uapi/domestic-stock/v1/quotations/inquire-daily-price",
                             "FHKST01010400",
                             {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                              "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"})
        return parse_latest_trade_date(js)

    async def holidays(self, bass_dt: str) -> dict:
        """국내 개장일 달력 — {'YYYYMMDD': 개장여부}. bass_dt부터 수십일치(CTCA0903R)."""
        from backend.flow import market_status
        js = await self._get("/uapi/domestic-stock/v1/quotations/chk-holiday",
                             "CTCA0903R",
                             {"BASS_DT": bass_dt, "CTX_AREA_FK": "", "CTX_AREA_NK": ""})
        return market_status.parse_holidays(js)

    async def investor_detail(self, code: str) -> Optional[dict]:
        """최신 확정일 기관 세부 분해. 장중엔 오늘 날짜가 rt_cd=2로 거부되므로 전일 폴백."""
        import datetime as dt
        for delta in (0, 1):
            date = (dt.date.today() - dt.timedelta(days=delta)).strftime("%Y%m%d")
            js = await self._get(
                "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily",
                "FHPTJ04160001",
                {"FID_COND_MRKT_DIV_CODE": self.div, "FID_INPUT_ISCD": code,
                 "FID_INPUT_DATE_1": date, "FID_ORG_ADJ_PRC": "",
                 "FID_ETC_CLS_CODE": ""})
            d = parse_investor_detail(js)
            if d:
                return d
        return None

    async def program_trend(self, code: str) -> list:
        js = await self._get("/uapi/domestic-stock/v1/quotations/program-trade-by-stock",
                             "FHPPG04650101",
                             {"FID_COND_MRKT_DIV_CODE": self.div, "FID_INPUT_ISCD": code})
        return parse_program_trend(js)
