from __future__ import annotations

"""한국투자증권(KIS) 오픈API 연동 — 실시간 수급용.

와이어 포맷은 공식 koreainvestment/open-trading-api 리포에서 검증(2026-07-10):
- 웹소켓 데이터 프레임: '0|TRID|N|f1^f2^...' (N개 레코드의 필드 연접, 시세 TR은 평문).
  JSON 프레임은 구독 ACK·PINGPONG. PINGPONG은 받은 원문 그대로 에코해야 한다.
- H0STCNT0(실시간 체결가) 46필드 · H0STPGM0(종목별 프로그램매매) 11필드.
파서는 전부 순수 함수로 두어 픽스처만으로 테스트한다(실연결 불필요).
"""

import json
from typing import Optional


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
