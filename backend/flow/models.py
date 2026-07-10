from __future__ import annotations

"""종목 하나의 실시간 수급 상태(FlowState) — SSE 스냅샷의 단일 진실원.

이벤트(체결·프로그램·잠정·일별)를 적용(apply/set)하고, 1초마다 snapshot() dict를
그대로 JSON 직렬화해 내보낸다. 프런트 JS는 이 스키마와 1:1로 렌더한다.
"""

import time
from collections import deque
from typing import Optional

_TAPE_MAX = 30     # 체결 테이프 표시 건수
_POINTS_MAX = 200  # 프로그램 누적 차트 포인트 상한


class FlowState:
    def __init__(self, code: str, name: str, mode: str):
        self.code, self.name, self.mode = code, name, mode
        self._market: dict = {"price": None, "sign": "", "change": None, "rate": None,
                              "vol": None, "value": None, "strength": None, "time": None}
        self._tape: deque = deque(maxlen=_TAPE_MAX)
        self._pgm_net_qty = 0
        self._pgm_net_value = 0
        self._pgm_points: deque = deque(maxlen=_POINTS_MAX)
        self._estimate_rows: list = []
        self._daily: list = []
        self._detail: dict = {"date": None, "rows": []}  # 기관 세부(최신 확정일)
        # 장중 부분 세부(잠정): 기관 내역 rows + 기타(법인·단체) — 개인 역산용
        self._est_detail: dict = {"asof": None, "rows": [],
                                  "etc_qty": None, "etc_value": None}
        self._status = {"connected": False, "note": ""}

    def apply_tick(self, d: dict) -> None:
        self._market = {"price": d["price"], "sign": d["sign"], "change": d["change"],
                        "rate": d["rate"], "vol": d["acml_vol"], "value": d["acml_value"],
                        "strength": d["strength"], "time": d["t"]}
        self._tape.appendleft({"t": d["t"], "price": d["price"],
                               "vol": d["vol"], "side": d["side"]})

    def apply_program(self, d: dict) -> None:
        """프로그램 이벤트의 net_qty/net_value는 당일 '누적' 총계다(KIS 실측 2026-07-10)
        — 더하지 말고 대입한다. 추이 차트에는 그 시점 누적을 append."""
        self._pgm_net_qty = d["net_qty"]
        self._pgm_net_value = d["net_value"]
        self._pgm_points.append({"t": d["t"], "net_qty": self._pgm_net_qty,
                                 "net_value": self._pgm_net_value})

    def set_program_total(self, net_qty: int, net_value: int,
                          points: Optional[list] = None) -> None:
        """REST 백필용 — 누적치를 통째로 교체(장중 재접속 시)."""
        self._pgm_net_qty, self._pgm_net_value = net_qty, net_value
        if points is not None:
            self._pgm_points = deque(points[-_POINTS_MAX:], maxlen=_POINTS_MAX)

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

    def set_status(self, **kw) -> None:
        self._status.update(kw)

    def snapshot(self) -> dict:
        est_asof = self._estimate_rows[-1]["asof"] if self._estimate_rows else None
        return {
            "code": self.code, "name": self.name, "mode": self.mode,
            "ts": time.time(),
            "market": dict(self._market),
            "tape": list(self._tape),
            "program": {"net_qty": self._pgm_net_qty, "net_value": self._pgm_net_value,
                        "points": list(self._pgm_points)},
            "estimate": {"asof": est_asof, "rows": list(self._estimate_rows)},
            "estimate_detail": {"asof": self._est_detail["asof"],
                                "rows": list(self._est_detail["rows"]),
                                "etc_qty": self._est_detail["etc_qty"],
                                "etc_value": self._est_detail["etc_value"]},
            "daily": list(self._daily),
            "detail": {"date": self._detail["date"],
                       "rows": list(self._detail["rows"])},
            "status": dict(self._status),
        }
