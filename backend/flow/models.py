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
        self._status = {"connected": False, "note": ""}

    def apply_tick(self, d: dict) -> None:
        self._market = {"price": d["price"], "sign": d["sign"], "change": d["change"],
                        "rate": d["rate"], "vol": d["acml_vol"], "value": d["acml_value"],
                        "strength": d["strength"], "time": d["t"]}
        self._tape.appendleft({"t": d["t"], "price": d["price"],
                               "vol": d["vol"], "side": d["side"]})
        self._last_rx = time.time()
        self._last_rx_t = d["t"]

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

    def set_credit(self, d: dict) -> None:
        self._credit = {"rows": list(d.get("rows") or []), "asof": d.get("asof")}

    def set_shortsale(self, d: dict) -> None:
        self._shortsale = {"rows": list(d.get("rows") or []), "asof": d.get("asof")}

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
            "estimate_detail": {"asof": self._est_detail["asof"],
                                "rows": list(self._est_detail["rows"]),
                                "etc_qty": self._est_detail["etc_qty"],
                                "etc_value": self._est_detail["etc_value"]},
            "daily": list(self._daily),
            "detail": {"date": self._detail["date"],
                       "rows": list(self._detail["rows"])},
            "short": self._short_snapshot(),
            "adr": self._adr_snapshot(),
            "credit": {"rows": list(self._credit["rows"]),
                       "asof": self._credit["asof"],
                       "signal": credit_signal(self._credit["rows"])},
            "shortsale": {"rows": list(self._shortsale["rows"]),
                          "asof": self._shortsale["asof"]},
            "status": dict(self._status),
        }

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
