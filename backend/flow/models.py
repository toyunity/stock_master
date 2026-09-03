from __future__ import annotations

"""종목 하나의 실시간 수급 상태(FlowState) — SSE 스냅샷의 단일 진실원.

이벤트(체결·프로그램·잠정·일별)를 적용(apply/set)하고, 1초마다 snapshot() dict를
그대로 JSON 직렬화해 내보낸다. 프런트 JS는 이 스키마와 1:1로 렌더한다.
"""

import datetime as dt
import time
from collections import deque
from typing import Optional

from backend.config import settings
from backend.flow import kst
from backend.flow.credit import credit_signal
from backend.flow.shortbal import short_signal

_TAPE_MAX = 30     # 체결 테이프 표시 건수
# 프로그램 누적 차트 포인트 상한 — 분 단위 버킷이라 UN 세션(08~20시) 720분 + 여유.
# 예전 200(이벤트 단위)은 활발한 날 최근 몇 분만 남아 Y축이 플랫라인이 됐다(P0-1).
_POINTS_MAX = 780


_SIZE_KEYS = ("s1", "s2", "s3", "s4")  # 1-10 / 11-50 / 51-100 / 100초과 (주)
_SESSIONS = ("pre", "regular", "after")
_KRX_CLOSE_HM = "15:30"  # 이후 KIS div J 현재가는 동결 = 정규장 종가(실측)


def tick_session(t: str) -> str:
    """체결 시각(HH:MM:SS, KST) → 세션. 09:00 정각은 정규장.

    15:30:00 정각은 KRX 마감 단일가 프린트(대량)와 NXT 애프터 첫 체결이 겹치는
    초 — 물량이 압도적인 마감 단일가 쪽(정규장)으로 분류한다. NXT 애프터 첫 초
    일부가 정규로 섞이는 오차는 반대 분류(마감 단일가가 장후로 오인)보다 작다."""
    if t < "09:00:00":
        return "pre"
    if t <= "15:30:00":
        return "regular"
    return "after"


def size_bucket(vol: int) -> str:
    if vol <= 10:
        return "s1"
    if vol <= 50:
        return "s2"
    if vol <= 100:
        return "s3"
    return "s4"


def empty_sizes() -> dict:
    return {ses: {side: {b: {"n": 0, "v": 0} for b in _SIZE_KEYS}
                  for side in ("buy", "sell")} for ses in _SESSIONS}


def size_signal(ses: dict) -> Optional[dict]:
    """한 세션의 체결 규모 분포 → 주체 추정 판정(항상 '추정' — 정확한 주체 식별 불가).

    100주 초과 대금 비중 40%↑ = 기관성, 1-10주 건수 비중 70%↑ = 개인 중심.
    표본 30건 미만은 판정 보류(None) — 얇은 표본의 과판정 방지."""
    tot_v = sum(c["v"] for side in ses.values() for c in side.values())
    tot_n = sum(c["n"] for side in ses.values() for c in side.values())
    if tot_n < 30 or tot_v <= 0:
        return None
    # 양쪽 다 40%를 넘을 수 있다(리뷰 확정) — 순서가 아니라 큰 쪽으로 판정
    sell_big = ses["sell"]["s4"]["v"] / tot_v
    buy_big = ses["buy"]["s4"]["v"] / tot_v
    if max(sell_big, buy_big) >= 0.4:
        if sell_big > buy_big:
            return {"text": "기관성 매도 우세(추정)", "tone": "warn"}
        if buy_big > sell_big:
            return {"text": "기관성 매수 우세(추정)", "tone": "good"}
        return {"text": "기관성 매수·매도 팽팽(추정)", "tone": "info"}
    if (ses["buy"]["s1"]["n"] + ses["sell"]["s1"]["n"]) / tot_n >= 0.7:
        return {"text": "개인 소액 물량 중심(추정)", "tone": "info"}
    return {"text": "혼재 — 뚜렷한 우세 없음", "tone": "flat"}


def reconcile_daily_close(daily: list, trusted: dict) -> list:
    """일별 수급 표의 종가를 신뢰 소스로 통일한다.

    KIS 투자자 TR(FHKST01010900)의 stck_clpr은 같은 날 공매도 TR·신용 TR·FDR
    일봉과 어긋난다(2026-07-23 실측: 7/21 1,872,000 vs 1,836,000, 7/20
    1,841,000 vs 1,764,000). 한 화면에 종가가 두 값으로 나오면 어느 쪽을 믿을지
    알 수 없다 — 다른 패널이 쓰는 값으로 덮고, 그 소스에 없는 날은 비운다
    (틀릴 수 있는 값보다 '–'이 낫다)."""
    return [dict(r, close=trusted.get(r["date"])) for r in daily]


def today_flow(daily: list, estimate_rows: list,
               today_iso: str) -> Optional[dict]:
    """오늘 수급 한 줄 요약이 쓸 값 — 당일 확정 행이 있으면 확정, 없으면 잠정.

    잠정 API(HHPTJ04160200)는 슬롯이 14:30이 마지막이라 마감 후에도 14:30 값에
    멈춘다 — 14:30~15:30 물량이 통째로 빠진다(2026-07-23 실측: 잠정 외인
    +559,000 vs 확정 +689,696). 같은 화면 아래에 확정치가 이미 떠 있는데 상단
    카드만 잠정이면 서로 어긋나 보인다."""
    for r in reversed(daily or []):
        if r.get("date") == today_iso:
            return {"src": "confirmed", "asof": "확정", "prsn": r.get("prsn"),
                    "frgn": r.get("frgn"), "orgn": r.get("orgn")}
    if estimate_rows:
        last = estimate_rows[-1]
        return {"src": "estimate", "asof": last.get("asof"), "prsn": None,
                "frgn": last.get("frgn"), "orgn": last.get("orgn")}
    return None


def market_state(now_kst: dt.datetime, stalled: bool, has_data: bool) -> dict:
    """KST 시각 + 체결 공백 → 시장 상태 배지 추정 {state,label,tone}.

    KIS 장운영 TR 없이 동작하는 보수적 추정. 수신 정지(halt)는 정규장
    (09:00~15:30)에서만 판정 — NXT 프리/애프터마켓은 체결이 원래 뜸해
    90초 공백이 정상이다. 평일 공휴일은 달력이 없어 구분 불가 → 데이터가
    하나도 없으면 halt 대신 '체결 대기'로 표시한다."""
    hm = now_kst.strftime("%H:%M")
    if now_kst.weekday() >= 5:
        return {"state": "closed", "label": "주말 휴장", "tone": "off"}
    if hm < "08:00":
        return {"state": "closed", "label": "장전", "tone": "off"}
    if hm >= "20:00":
        return {"state": "closed", "label": "장마감", "tone": "off"}
    if hm < "09:00":
        return {"state": "pre", "label": "프리마켓(NXT)", "tone": "info"}
    if hm > "15:30":
        return {"state": "after", "label": "애프터마켓(NXT)", "tone": "info"}
    if hm >= "15:20":
        # 장마감 동시호가(15:20~30): 연속 체결이 없는 게 정상 — 매일 15:21:30에
        # 가짜 'VI/CB 의심'이 뜨는 회귀(리뷰 확정)를 여기서 차단한다.
        return {"state": "auction", "label": "장마감 동시호가(15:20~30)",
                "tone": "info"}
    if stalled and has_data:
        return {"state": "halt", "label": "수신 정지 — VI/CB 의심", "tone": "warn"}
    if not has_data:
        return {"state": "open", "label": "정규장 · 체결 대기", "tone": "info"}
    return {"state": "open", "label": "정규장", "tone": "live"}


class FlowState:
    def __init__(self, code: str, name: str, mode: str):
        self.code, self.name, self.mode = code, name, mode
        self._market: dict = {"price": None, "sign": "", "change": None, "rate": None,
                              "vol": None, "value": None, "strength": None, "time": None}
        self._tape: deque = deque(maxlen=_TAPE_MAX)
        self._pgm_net_qty = 0
        self._pgm_net_value = 0
        self._pgm_points: deque = deque(maxlen=_POINTS_MAX)
        # 당일 누적 프로그램 net_value의 전체 min/max — Y축 도메인 고정용(P0-1).
        # 분 버킷으로 접힌 중간 극값까지 반영하려고 포인트와 별도로 추적한다.
        self._pgm_day_min: Optional[int] = None
        self._pgm_day_max: Optional[int] = None
        self._last_rx: Optional[float] = None  # 마지막 실체결/프로그램 수신(벽시계)
        # 그 수신의 '표시용' 거래소 타임스탬프 — 스냅샷 시점의 _market["time"]은
        # REST 폴백이 10초마다 덮어써 정지 시각이 미끄러진다(리뷰 확정)
        self._last_rx_t: Optional[str] = None
        self._estimate_rows: list = []
        self._daily: list = []
        self._detail: dict = {"date": None, "rows": []}  # 기관 세부(최신 확정일)
        # 장중 부분 세부(잠정): 기관 내역 rows + 기타(법인·단체) — 개인 역산용
        self._est_detail: dict = {"asof": None, "rows": [],
                                  "etc_qty": None, "etc_value": None}
        # 대차잔고(T+1 공시): rows=[{date,qty,value,chg,src}…오름차순]
        self._short: dict = {"rows": [], "asof": None, "source": None,
                             "updated": None}
        # ADR/DR 시세 스냅샷(60s 갱신) — 환산·괴리율은 snapshot에서 계산(원주가 틱 변동)
        self._adr: Optional[dict] = None
        # 신용융자 잔고(실질 T+2)·공매도 일별(T+1): rows 오름차순
        self._credit: dict = {"rows": [], "asof": None}
        self._shortsale: dict = {"rows": [], "asof": None}
        # 체결 규모 분포: 세션×방향×구간 {n(건수), v(대금)} — 주체 추정용(당일 한정)
        self._sizes: dict = empty_sizes()
        # 거래소별 거래량·거래원 창구(각 60s 갱신, 실패 시 이전 값 유지)
        self._exvol: Optional[dict] = None
        self._member: Optional[dict] = None
        # 매수 유의사항(토스): [{type,label,tone,exchange,start,end}]. 빈 목록이
        # '지정 없음'이라 다른 패널과 달리 **빈 값도 그대로 반영한다**(아래 set_warnings).
        self._warnings: list = []
        self._status = {"connected": False, "note": ""}

    def apply_tick(self, d: dict) -> None:
        self._market = {"price": d["price"], "sign": d["sign"], "change": d["change"],
                        "rate": d["rate"], "vol": d["acml_vol"], "value": d["acml_value"],
                        "strength": d["strength"], "time": d["t"]}
        self._tape.appendleft({"t": d["t"], "price": d["price"],
                               "vol": d["vol"], "side": d["side"]})
        self._last_rx = time.time()
        self._last_rx_t = d["t"]
        if d["side"] in ("buy", "sell") and d["vol"] > 0:
            c = self._sizes[tick_session(d["t"])][d["side"]][size_bucket(d["vol"])]
            c["n"] += 1
            c["v"] += d["vol"] * d["price"]

    def set_market(self, d: dict) -> None:
        """REST 폴백용 시세 갱신 — 테이프는 건드리지 않고, 미제공 필드는 유지.

        누적 거래량이 '증가'했을 때만 수신으로 인정 — VI/CB 중엔 REST가 정상
        응답해도 신규 체결이 없다(P0-2). 단순 부등(≠) 비교는 자정 카운터 리셋·
        재시작 직후 첫 폴링을 수신으로 오인한다(리뷰 확정)."""
        prev, cur = self._market.get("vol"), d.get("acml_vol")
        if prev is not None and cur is not None and cur > prev:
            self._last_rx = time.time()
            self._last_rx_t = d.get("time") or self._last_rx_t
        self._market.update({
            "price": d.get("price"), "sign": d.get("sign", ""),
            "change": d.get("change"), "rate": d.get("rate"),
            "vol": d.get("acml_vol"), "value": d.get("acml_value"),
            "time": d.get("time", self._market.get("time"))})

    def apply_program(self, d: dict) -> None:
        """프로그램 이벤트의 net_qty/net_value는 당일 '누적' 총계다(KIS 실측 2026-07-10)
        — 더하지 말고 대입한다. 추이 포인트는 분 단위 버킷(같은 분은 마지막 값으로
        교체) — 이벤트 단위로 쌓으면 활발한 날 deque가 최근 몇 분만 남긴다(P0-1)."""
        self._pgm_net_qty = d["net_qty"]
        self._pgm_net_value = d["net_value"]
        self._last_rx = time.time()
        self._last_rx_t = d["t"]
        self._track_pgm_range(d["net_value"])
        pt = {"t": d["t"], "net_qty": d["net_qty"], "net_value": d["net_value"]}
        if self._pgm_points and self._pgm_points[-1]["t"][:5] == d["t"][:5]:
            self._pgm_points[-1] = pt
        else:
            self._pgm_points.append(pt)

    def set_program_total(self, net_qty: int, net_value: int,
                          points: Optional[list] = None) -> None:
        """REST 백필용 — 누적치를 통째로 교체(장중 재접속 시)."""
        self._pgm_net_qty, self._pgm_net_value = net_qty, net_value
        self._track_pgm_range(net_value)
        if points is not None:
            self._pgm_points = deque(points[-_POINTS_MAX:], maxlen=_POINTS_MAX)
            for p in points:
                self._track_pgm_range(p["net_value"])

    _POINTS_SEND_MAX = 240  # SSE 1초마다 전문 재전송 — 720분치 원본이면 ~50KB/s(리뷰)

    def _pgm_points_thin(self) -> list:
        """스냅샷용 추이 곡선 — 240점 초과 시 균등 솎아내기(마지막 점은 보존).
        Y축 도메인은 day_min/max가 별도로 들고 있어 극값 손실 없음."""
        pts = list(self._pgm_points)
        if len(pts) <= self._POINTS_SEND_MAX:
            return pts
        step = -(-len(pts) // self._POINTS_SEND_MAX)  # ceil
        out = pts[::step]
        if out[-1] is not pts[-1]:
            out.append(pts[-1])
        return out

    def _track_pgm_range(self, v: int) -> None:
        if self._pgm_day_min is None or v < self._pgm_day_min:
            self._pgm_day_min = v
        if self._pgm_day_max is None or v > self._pgm_day_max:
            self._pgm_day_max = v

    def set_estimate(self, rows: list) -> None:
        self._estimate_rows = list(rows)

    def set_daily(self, rows: list) -> None:
        self._daily = list(rows)[:10]

    def set_detail(self, d: dict) -> None:
        self._detail = {"date": d.get("date"), "rows": list(d.get("rows") or [])}

    def set_estimate_detail(self, d: dict) -> None:
        self._est_detail = {"asof": d.get("asof"),
                            "rows": list(d.get("rows") or []),
                            "etc_qty": d.get("etc_qty"),
                            "etc_value": d.get("etc_value")}

    def set_short(self, d: dict) -> None:
        self._short = {"rows": list(d.get("rows") or []),
                       "asof": d.get("asof"), "source": d.get("source"),
                       "updated": d.get("updated")}

    def set_adr(self, d: dict) -> None:
        self._adr = dict(d)

    def set_exvol(self, d: dict) -> None:
        self._exvol = dict(d)

    def set_member(self, d: dict) -> None:
        self._member = dict(d)

    def set_credit(self, d: dict) -> None:
        self._credit = {"rows": list(d.get("rows") or []), "asof": d.get("asof")}

    def set_shortsale(self, d: dict) -> None:
        self._shortsale = {"rows": list(d.get("rows") or []), "asof": d.get("asof")}

    def set_warnings(self, rows: list) -> None:
        """매수 유의사항 — **빈 목록도 그대로 덮는다.**

        다른 패널의 '실패 시 이전 값 유지' 관행을 여기 적용하면 안 된다: VI는 2~10분이면
        풀리는데 마지막 값을 붙들면 이미 끝난 VI 배지가 종일 남는다. 조회 실패는
        호출부(engine)가 set 자체를 건너뛰어 처리하고, 여기 도달한 []는 '지정 없음'이다."""
        self._warnings = [dict(r) for r in rows or []]

    def set_status(self, **kw) -> None:
        self._status.update(kw)

    def reset_intraday(self) -> None:
        """날짜가 바뀌면 '당일 한정' 데이터를 비운다 — 서버가 며칠씩 떠 있으면
        전일 잠정치가 오늘 것처럼 화면에 남는 실사고(2026-07-13 월 아침) 방지.
        시세(폴백 10초 내 자가 수정)·일별/세부/대차(여러 날 확정치)는 유지."""
        self._tape.clear()
        self._pgm_net_qty = 0
        self._pgm_net_value = 0
        self._pgm_points.clear()
        self._pgm_day_min = None
        self._pgm_day_max = None
        self._last_rx = None
        self._last_rx_t = None
        self._sizes = empty_sizes()
        self._exvol = None    # 당일 누적 기반 — 전일 것이 남으면 오도(리뷰 확정)
        self._member = None
        self._estimate_rows = []
        self._est_detail = {"asof": None, "rows": [],
                            "etc_qty": None, "etc_value": None}

    def _stall_snapshot(self) -> dict:
        """마지막 실체결/프로그램 수신 후 경과 — 정지 판정은 서버가 한다(P0-2).
        since는 그 수신 시점에 고정한 거래소 타임스탬프(_last_rx_t) — 스냅샷
        시점의 market.time은 REST 폴백이 계속 갱신해 정지 시각이 미끄러진다."""
        if self._last_rx is None:
            return {"stalled": False, "since": None, "sec": None}
        sec = int(time.time() - self._last_rx)
        return {"stalled": sec >= settings.stall_sec,
                "since": self._last_rx_t, "sec": sec}

    def snapshot(self) -> dict:
        est_asof = self._estimate_rows[-1]["asof"] if self._estimate_rows else None
        now = kst.now()
        stall = self._stall_snapshot()
        return {
            "code": self.code, "name": self.name, "mode": self.mode,
            "ts": time.time(),
            "kst_date": now.strftime("%Y-%m-%d"),
            "kst_time": now.strftime("%H:%M:%S"),
            "stall": stall,
            "market_state": market_state(now, stall["stalled"],
                                         self._last_rx is not None),
            "market": dict(self._market),
            "tape": list(self._tape),
            "program": {"net_qty": self._pgm_net_qty, "net_value": self._pgm_net_value,
                        "day_min": self._pgm_day_min, "day_max": self._pgm_day_max,
                        "points": self._pgm_points_thin()},
            "estimate": {"asof": est_asof, "rows": list(self._estimate_rows)},
            "today_flow": today_flow(self._daily, self._estimate_rows,
                                     now.strftime("%Y-%m-%d")),
            "estimate_detail": {"asof": self._est_detail["asof"],
                                "rows": list(self._est_detail["rows"]),
                                "etc_qty": self._est_detail["etc_qty"],
                                "etc_value": self._est_detail["etc_value"]},
            "daily": reconcile_daily_close(self._daily,
                                           self._trusted_closes(now)),
            "detail": {"date": self._detail["date"],
                       "rows": list(self._detail["rows"])},
            "short": self._short_snapshot(),
            "sizes": {**{ses: {side: dict(b) for side, b in sides.items()}
                         for ses, sides in self._sizes.items()},
                      "signals": {ses: size_signal(self._sizes[ses])
                                  for ses in _SESSIONS}},
            "adr": self._adr_snapshot(),
            "exvol": self._exvol,
            "member": self._member,
            "credit": {"rows": list(self._credit["rows"]),
                       "asof": self._credit["asof"],
                       "signal": credit_signal(self._credit["rows"])},
            "shortsale": {"rows": list(self._shortsale["rows"]),
                          "asof": self._shortsale["asof"]},
            "warnings": list(self._warnings),
            "status": dict(self._status),
        }

    def _trusted_closes(self, now: dt.datetime) -> dict:
        """공매도(T+1)·신용(T+2) 패널이 쓰는 종가 맵 — FDR 일봉과 일치 확인
        (2026-07-23, 20거래일 전수). 공매도가 더 최신이라 신용 위에 덮는다.

        오늘 행은 두 소스 모두 아직 없다(공매도 공표는 16시 이후, 신용은 T+2) —
        정규장이 끝났으면 거래소별 패널의 KRX 현재가로 메운다. div J는 15:30 이후
        동결돼 그 값이 정규장 종가고, 해외·거래소 판정도 같은 값을 쓴다(실측)."""
        m = {r["date"]: r["close"] for r in self._credit["rows"] if r.get("close")}
        m.update({r["date"]: r["close"] for r in self._shortsale["rows"]
                  if r.get("close")})
        krx = ((self._exvol or {}).get("krx") or {}).get("price")
        if krx and now.strftime("%H:%M") >= _KRX_CLOSE_HM:
            m.setdefault(now.strftime("%Y-%m-%d"), krx)   # 확정치가 오면 그쪽 우선
        return m

    def _adr_snapshot(self) -> Optional[dict]:
        """DR 시세 × 비율 × 환율 = 환산가, 원주 현재가 대비 괴리율 — 원주가가
        틱마다 변하므로 스냅샷 시점에 계산한다(대차 판정과 동일 패턴)."""
        a = self._adr
        if not a:
            return None
        conv = a["usd"] * a["ratio"] * a["fx"]
        price = self._market.get("price")
        return dict(a, converted=int(round(conv)), ord_price=price,
                    premium_pct=(round((conv / price - 1) * 100, 2)
                                 if price else None))

    def _short_snapshot(self) -> dict:
        """대차잔고 + 판정 시그널. 시그널은 '당일 등락률 × 최신 잔고 증감'이라
        틱마다 변할 수 있어 스냅샷 시점에 계산한다."""
        rows = self._short["rows"]
        last_chg = rows[-1].get("chg") if rows else None
        return {"rows": list(rows), "asof": self._short["asof"],
                "source": self._short["source"],
                "updated": self._short["updated"],
                "signal": short_signal(self._market.get("rate"), last_chg)}
