from __future__ import annotations

"""토스증권 Open API — KIS에 없는 것만 (한국 국채 금리 · 대차거래 · 매수 유의사항).

도입 범위는 2026-09-03 공식 스펙 실사로 확정했다(openapi.json **v1.2.14** 엔드포인트
33개 / asyncapi.json **1.2.2** 채널 3개를 전수 열거 — "없다"는 표본이 아니라 전수다).

**KIS를 대체하지 않는다. 세 가지가 막는다:**
1. 파생이 아예 없다 — 지수선물·코스피200 옵션 엔드포인트 0개. futures/options 대체 불가.
2. 실시간 체결 프레임이 `price·volume·timestamp·currency` **4필드뿐**이다. /live가 쓰는
   체결강도·매수/매도 구분·누적거래량이 없고, 스펙이 직접 "수신 프레임 합산으로 누적
   거래량을 재구성할 수 없습니다"라고 못박았다. 시세 채널은 LOSSY(유실 감지 sequence
   미제공)에 구독 직후 스냅샷도 없다.
3. `/api/v1/prices`도 `symbol·timestamp·lastPrice·currency` 4필드다 — 등락률·전일대비·
   시가총액이 없어 KIS FHKST01010100 한 콜을 대신하지 못한다.
그래서 실시간은 계속 KIS이고, 이 모듈은 REST 조회만 한다.

**⚠️ 토큰은 client당 1개다. 재발급하면 이전 토큰이 즉시 무효화된다**(스펙 원문:
"client 당 유효한 access token 은 1 개입니다. 재발급 시 이전에 발급된 token 은 즉시
무효화됩니다"). KIS는 새로 받아도 옛 토큰이 만료까지 살아 있었지만, 토스는 그 순간
401이다 — 검증 서버가 한 번 발급하면 8000 실서버가 즉사한다. 두 겹으로 막는다:
  (1) 키가 비면 **캐시 토큰조차 쓰지 않는다** — 하네스가 SM_TOSS_*를 비워 미접촉을 보장.
  (2) 발급은 프로세스 전역 락 + 이중검사로 한 번만 — kis.token()과 같은 사유·같은 락
      (둘 다 드물어 서로 기다려도 손해가 없고, 임계구역이 겹치지 않아 교착이 없다).

**⚠️ 허용 IP 미등록이면 토큰 발급부터 403이다** (WTS 설정 > Open API > 허용 IP 관리).
REST와 웹소켓이 같은 목록을 쓴다. 집 ISP 공인 IP가 바뀌면 전부 죽는다.

**2026-09-03 라이브 실측**(마스터 키·허용 IP 등록 후 첫 호출):
- 허용 IP 등록돼 있으면 403 없이 통과. 토큰 `expires_in=86399`(24h).
- 응답 헤더 `X-RateLimit-Limit` 실측치가 문서 표와 **일치**했다:
  AUTH 5 · STOCK 5 · STOCK_TRADING_TREND 10 · MARKET_DATA 15 ·
  MARKET_INDICATOR 10 · MARKET_INDICATOR_CHART 5 · MARKET_INFO 3.
- 호가는 **10단**(asks/bids 각 10) — KIS와 같다. 스펙엔 배열 길이 제한이 없어 미상이었다.
- **미국 시세는 실시간이다.** AAPL 최근 체결 3회 샘플(KST 15:23, 미국 데이마켓):
  조회 시각 대비 102초 / **4.2초** / 29초. 4.2초가 나온 이상 15분 지연 피드가 아니고,
  들쭉날쭉한 값은 데이마켓의 체결 공백이다. 정규장(KST 22:30~05:00)은 미측정.
  → KIS는 해외 실시간에 거래소 신청 권한이 필요해 막혔던 자리다(worldidx 주석 참조).
- 국채는 **전일 확정치만** 온다. 09-03 15:23 조회에 캔들 최신 봉이 09-02였고,
  `/market-indicators/prices`의 `timestamp`는 null에 값이 09-02 종가와 같았다
  (장 마감 후 당일이 채워지는지는 미측정).

Rate limit은 그룹별 **초당** 제한이고 문서값은 "사전 공지 없이 조정될 수 있으며 현재
허용 한도는 응답 헤더 `X-RateLimit-Limit`"이다 — 표를 코드에 박지 않는다. 여기서 쓰는
그룹: MARKET_INDICATOR_CHART(5/s) · STOCK_TRADING_TREND(10/s) · STOCK(5/s) · AUTH(5/s).

Python 3.9 호환.
"""

import asyncio
import datetime as dt
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from backend.flow.kis import _issue_lock_for_running_loop

log = logging.getLogger(__name__)

REST_BASE = "https://openapi.tossinvest.com"
_TIMEOUT = 10.0
_RETRY_BASE_SEC = 1.0     # 429 권고: Retry-After 대기 + 지수 백오프(1→2→4)

# 시장 지표 심볼 카탈로그는 8종이 전부다(KOSPI·KOSDAQ·KR_BOND_2/3/5/10/20/30Y).
# 밖은 400 unsupported-symbol — 미국채·금·유가·S&P·나스닥·VIX는 **없다**.
BOND_SYMBOLS = ("KR_BOND_2Y", "KR_BOND_3Y", "KR_BOND_5Y",
                "KR_BOND_10Y", "KR_BOND_20Y", "KR_BOND_30Y")

# 매수 유의사항 코드 → 한글 라벨. 스펙이 "클라이언트는 unknown code 를 허용하도록
# 구현해야 합니다"라고 명시하므로 모르는 코드도 **버리지 않고** 코드 그대로 띄운다.
WARNING_LABELS = {
    "LIQUIDATION_TRADING": "정리매매",
    "OVERHEATED": "단기과열",
    "INVESTMENT_WARNING": "투자경고",
    "INVESTMENT_RISK": "투자위험",
    "VI_STATIC_AND_DYNAMIC": "VI 발동(정적+동적)",
    "VI_STATIC": "VI 발동(정적)",
    "VI_DYNAMIC": "VI 발동(동적)",
    "STOCK_WARRANTS": "신주인수권",
}

# 색 판정은 백엔드가 한다(이 리포의 관행 — 프런트는 칠하기만 한다).
# VI는 '지금 2~10분 멈춘다'는 사실 통지라 info다. 나머지는 돈이 걸린 경고 —
# 정리매매는 상장폐지 절차이고, 투자경고/위험은 매수 증거금·신용이 막힌다.
# **모르는 코드는 warn**이 기본값이다: 새 유형이 생겼을 때 조용히 회색으로 묻히면,
# 초보자가 봐야 할 경고가 화면에서 사라진다(안전측).
_WARN_TONES = {"VI_STATIC": "info", "VI_DYNAMIC": "info",
               "VI_STATIC_AND_DYNAMIC": "info", "STOCK_WARRANTS": "info"}


def _num(v) -> Optional[float]:
    """숫자로 못 읽히면 None — 0.0으로 뭉개면 결측이 값처럼 보인다(worldidx와 같은 계약).

    토스는 모든 수치를 **문자열 decimal**로 내린다(`"72000"`, `"2.73"`)."""
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    return None if f != f else f      # NaN 제외


def _int(v) -> Optional[int]:
    f = _num(v)
    return None if f is None else int(f)


def _date(v) -> Optional[str]:
    """ISO 8601 date-time 또는 date → 'YYYY-MM-DD'. 못 읽으면 None."""
    s = str(v or "")[:10]
    try:
        dt.date.fromisoformat(s)
    except ValueError:
        return None
    return s


def unwrap(js: dict):
    """성공 envelope의 `result`. 실패(`error`)는 예외로 올린다.

    스펙: 200은 `{"result": …}`, 4xx/5xx는 `{"error": {"code","message",…}}`이고
    둘이 동시에 나오지 않는다. 실패를 빈 값으로 조용히 흡수하면 화면이 '데이터 없음'과
    '원천 고장'을 구분하지 못한다 — 이 앱이 반복해서 데인 자리다."""
    if not isinstance(js, dict):
        raise RuntimeError("토스 응답이 객체가 아니다: %r" % (js,))
    err = js.get("error")
    if err:
        raise RuntimeError("토스 %s: %s" % (err.get("code", "?"),
                                           err.get("message", "")))
    return js.get("result")


# ── 순수 파서 ─────────────────────────────────────────────────────────────

def parse_indicator_candles(js: dict) -> list:
    """시장 지표 캔들 → [{date, open, high, low, close}] **오름차순**.

    응답은 최신순이다(스펙 예제 실물). 국채는 close가 수익률(%) — `3.25`면 3.25%다.
    국채(KR_BOND_*)는 일봉만 지원하고 분봉은 400 invalid-request다."""
    result = js.get("result") if isinstance(js, dict) else None
    rows = []
    for c in (result or {}).get("candles") or []:
        date, close = _date(c.get("timestamp")), _num(c.get("closePrice"))
        if date is None or close is None:
            continue
        rows.append({"date": date, "close": close,
                     "open": _num(c.get("openPrice")),
                     "high": _num(c.get("highPrice")),
                     "low": _num(c.get("lowPrice"))})
    rows.sort(key=lambda r: r["date"])
    return rows


def parse_lending(js: dict) -> list:
    """대차거래 동향 → [{date, qty, exec, rdmp, value, chg}] 오름차순.

    `chg`(전일 대비 잔고)를 여기서 계산하는 게 이 API를 들이는 이유다 — shortbal은
    KOFIA/SEIBro 이종 원천이 섞여(집계 범위가 달라 절대치 불일치, 실측 14.1M vs 11.1M주)
    전일 대비를 계산할 수 없었다. 단일 원천이면 그냥 뺄셈이다.

    `value`(balanceAmount)는 응답이 주는 원 단위 정수라 credit.py처럼 종가로 산출할
    필요가 없다 — '≈' 라벨도 필요 없다.
    데이터 적시성(스펙): 일별 확정치는 **해당 일자 저녁**에 반영된다."""
    result = js.get("result") if isinstance(js, dict) else None
    rows = []
    for r in (result or {}).get("records") or []:
        date, qty = _date(r.get("date")), _int(r.get("balanceQuantity"))
        if date is None or qty is None:
            continue
        rows.append({"date": date, "qty": qty,
                     "exec": _int(r.get("executionQuantity")),
                     "rdmp": _int(r.get("repaymentQuantity")),
                     "value": _int(r.get("balanceAmount")),
                     "updated": r.get("updatedAt")})
    rows.sort(key=lambda r: r["date"])
    return [dict(r, chg=(r["qty"] - rows[i - 1]["qty"]) if i else None)
            for i, r in enumerate(rows)]


def parse_warnings(js: dict) -> list:
    """매수 유의사항 → [{type, label, exchange, start, end}].

    모르는 코드도 버리지 않는다(스펙 지시). 라벨이 없으면 코드를 그대로 쓴다 —
    빈 문자열을 내리면 화면에 글자 없는 배지가 뜬다."""
    result = js.get("result") if isinstance(js, dict) else None
    rows = []
    for w in result or []:
        code = str(w.get("warningType") or "").strip()
        if not code:
            continue
        rows.append({"type": code, "label": WARNING_LABELS.get(code, code),
                     "tone": _WARN_TONES.get(code, "warn"),
                     "exchange": w.get("exchange"),
                     "start": _date(w.get("startDate")),
                     "end": _date(w.get("endDate"))})
    return rows


# ── 클라이언트 ────────────────────────────────────────────────────────────

class TossClient:
    """토큰(디스크 캐시) + REST 조회 3종. httpx 비동기, 실패는 예외로 위임."""

    def __init__(self, client_id: str, client_secret: str, cache_dir: str,
                 base: str = REST_BASE):
        self.client_id, self.client_secret, self.base = (
            client_id, client_secret, base)
        self._token_path = Path(cache_dir) / "toss_token.json"

    # ── 토큰 ──────────────────────────────────────────────────────────
    def _cached_token(self) -> Optional[str]:
        try:
            c = json.loads(self._token_path.read_text(encoding="utf-8"))
            if c.get("token") and c.get("expires_at", 0) > time.time() + 60:
                return c["token"]
        except (OSError, ValueError):
            pass
        return None

    async def _issue_token(self) -> dict:
        import httpx
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            r = await cli.post(self.base + "/oauth2/token",
                               data={"grant_type": "client_credentials",
                                     "client_id": self.client_id,
                                     "client_secret": self.client_secret})
            if r.status_code == 403:
                raise RuntimeError(
                    "토스 토큰 403 — 허용 IP 미등록이다. WTS 설정 > Open API > "
                    "허용 IP 관리에 이 서버의 공인 IP를 등록해야 한다")
            r.raise_for_status()
            js = r.json()
        if "access_token" not in js:
            raise RuntimeError("토스 토큰 발급 실패: %s" % (js,))
        return js

    async def token(self) -> str:
        """캐시된 접근토큰. 만료됐으면 **한 번만** 발급한다.

        키가 비면 캐시 토큰도 쓰지 않는 이유와 락으로 발급을 한 번만 하는 이유는
        모듈 docstring의 ⚠️ 문단에 있다 — 재발급이 이전 토큰을 즉시 죽이므로,
        여기서 새는 발급 한 번이 실서버의 401 한 번이다."""
        if not (self.client_id and self.client_secret):
            raise RuntimeError(
                "토스 키 없음 — 호출 차단(캐시 토큰도 쓰지 않는다)")
        tok = self._cached_token()
        if tok:
            return tok
        async with _issue_lock_for_running_loop():
            tok = self._cached_token()      # 대기 중에 남이 받아왔을 수 있다
            if tok:
                return tok
            js = await self._issue_token()
            tok = js["access_token"]
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._token_path.with_name(self._token_path.name + ".tmp")
            tmp.write_text(json.dumps(
                {"token": tok,
                 "expires_at": time.time() + int(js.get("expires_in", 86400))}
            ), encoding="utf-8")
            os.replace(tmp, self._token_path)   # 원자적 — 반쪽 파일을 읽지 않게
            return tok

    # ── 조회 ──────────────────────────────────────────────────────────
    async def _get(self, path: str, params: Optional[dict] = None,
                   retries: int = 2) -> dict:
        """GET + 429 백오프. 스펙 권고대로 `Retry-After`를 먼저 존중하고,
        없으면 지수 백오프(1→2→4)로 물러난다. 5xx도 같은 경로를 탄다."""
        import httpx
        headers = {"Authorization": "Bearer %s" % await self.token()}
        delay = _RETRY_BASE_SEC
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            for attempt in range(retries + 1):
                r = await cli.get(self.base + path, headers=headers,
                                  params=params or {})
                if r.status_code in (429, 500, 502, 503) and attempt < retries:
                    wait = _num(r.headers.get("Retry-After")) or delay
                    log.debug("토스 %s HTTP %d — %.1fs 후 재시도",
                              path, r.status_code, wait)
                    await asyncio.sleep(wait)
                    delay *= 2
                    continue
                r.raise_for_status()
                return r.json()

    async def bond_candles(self, symbol: str, count: int = 2) -> list:
        """한국 국채 수익률 일봉. count는 최대 200(스펙)."""
        js = await self._get("/api/v1/market-indicators/%s/candles" % symbol,
                             {"interval": "1d", "count": count})
        unwrap(js)                       # 실패 envelope이면 여기서 터진다
        return parse_indicator_candles(js)

    async def lending(self, code: str, count: int = 20) -> list:
        """국내 종목 대차거래 동향. count는 최대 100(스펙). KR 전용 — 미국 종목은
        400 unsupported-market."""
        js = await self._get("/api/v1/stocks/%s/securities-lending" % code,
                             {"count": count})
        unwrap(js)
        return parse_lending(js)

    async def warnings(self, code: str) -> list:
        """매수 유의사항(정리매매·단기과열·투자경고/위험·VI·신주인수권)."""
        js = await self._get("/api/v1/stocks/%s/warnings" % code)
        unwrap(js)
        return parse_warnings(js)


_client: Optional[TossClient] = None


def get_client() -> Optional[TossClient]:
    """설정에 키가 있으면 프로세스 공용 클라이언트, 없으면 None.

    None을 돌려주는 것이 '토스 기능 꺼짐'의 단일 신호다 — 호출부는 None이면
    그 섹션을 통째로 생략한다(빈 껍데기 금지, worldidx와 같은 관행)."""
    global _client
    from backend.config import settings
    cid = settings.toss_client_id or ""
    sec = settings.toss_client_secret or ""
    if not (cid and sec):
        return None
    if _client is None or _client.client_id != cid:
        _client = TossClient(cid, sec, settings.cache_dir)
    return _client
