from __future__ import annotations

"""데모 소스 — KIS 키 없이 화면 전체를 검증하기 위한 시뮬레이션 스트림.

키 발급 전(또는 SM_FLOW_MODE=demo)에 /live 화면이 실제로 굴러가는지 확인하는 용도.
값은 시드 랜덤워크로 그럴싸하게 만들 뿐 실데이터가 아니며, 화면에 DEMO 배지와
안내 문구가 항상 표시된다. 기준가는 유니버스 캐시(전일 종가)에서 가져온다.
"""

import asyncio
import datetime as dt
import json
import random
from pathlib import Path
from typing import Optional

from backend.config import settings
from backend.news.names import _DISPLAY_NAMES


def _universe_rows() -> list:
    """유니버스 캐시 파일 직접 읽기 — 네트워크·FDR 갱신 로직 없이(테스트 안전)."""
    for name in ("universe_v2.json", "universe.json"):
        p = Path(settings.cache_dir) / name
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, list):
            return data
    return []


def lookup_stock(code: str) -> tuple:
    """(종목명, 전일종가|None). 관심종목 표시명 우선, 다음 유니버스 캐시."""
    name, close = _DISPLAY_NAMES.get(code), None
    for r in _universe_rows():
        if r.get("code") == code:
            name = name or r.get("name")
            close = r.get("close")
            break
    return name or code, close


class DemoSource:
    """FlowState에 가짜 체결·프로그램·잠정·일별 이벤트를 흘려 넣는다."""

    def __init__(self, state, base_price: Optional[float] = None):
        self.state = state
        self.rng = random.Random(int(state.code) if state.code.isdigit() else 42)
        self.base = int(base_price or lookup_stock(state.code)[1] or 100_000)

    def _seed_panels(self) -> None:
        rng, base = self.rng, self.base
        today = dt.date.today()
        daily, d = [], today - dt.timedelta(days=1)
        while len(daily) < 10:
            if d.weekday() < 5:  # 주말 제외
                frgn = rng.randint(-500_000, 500_000)
                orgn = rng.randint(-300_000, 300_000)
                daily.append({"date": d.isoformat(), "prsn": -(frgn + orgn),
                              "frgn": frgn, "orgn": orgn,
                              "close": int(base * (1 + rng.uniform(-0.03, 0.03)))})
            d -= dt.timedelta(days=1)
        self.state.set_daily(daily)
        frgn = rng.randint(-200_000, 200_000)
        orgn = rng.randint(-100_000, 100_000)
        self.state.set_estimate([{"asof": "10:00", "frgn": frgn, "orgn": orgn,
                                  "sum": frgn + orgn}])

    async def run(self, stop: asyncio.Event) -> None:
        rng = self.rng
        self._seed_panels()
        self.state.set_status(connected=True,
                              note="데모 데이터(시뮬레이션) — 실데이터가 아닙니다. KIS 키 입력 시 라이브 전환.")
        price, acml_vol, acml_value, n, last_est = float(self.base), 0, 0, 0, 0.0
        loop = asyncio.get_event_loop()
        start = loop.time()
        while not stop.is_set():
            n += 1
            drift = rng.uniform(-0.002, 0.002)
            price = max(1.0, price * (1 + drift))
            tick_px = int(round(price / 100.0) * 100)  # 호가단위 흉내(대형주 100원)
            vol = rng.randint(1, 500)
            acml_vol += vol
            acml_value += vol * tick_px
            now = dt.datetime.now().strftime("%H:%M:%S")
            rate = (tick_px - self.base) / self.base * 100
            self.state.apply_tick({
                "t": now, "price": tick_px,
                "sign": "up" if rate > 0 else ("down" if rate < 0 else "flat"),
                "change": tick_px - self.base, "rate": round(rate, 2),
                "vol": vol, "acml_vol": acml_vol, "acml_value": acml_value,
                "strength": round(rng.uniform(70, 150), 2),
                "side": "buy" if rng.random() < 0.5 + drift * 100 else "sell",
            })
            if n % 4 == 0:  # 프로그램매매는 체결보다 드문드문
                q = rng.randint(-2_000, 2_000)
                self.state.apply_program({"t": now, "sell_qty": max(0, -q),
                                          "sell_value": max(0, -q) * tick_px,
                                          "buy_qty": max(0, q),
                                          "buy_value": max(0, q) * tick_px,
                                          "net_qty": q, "net_value": q * tick_px})
            elapsed = loop.time() - start
            if elapsed - last_est > 45:  # 잠정치 갱신 시뮬레이션(실제는 하루 4회)
                last_est = elapsed
                rows = list(self.state.snapshot()["estimate"]["rows"])[-4:]
                frgn = rng.randint(-200_000, 200_000)
                orgn = rng.randint(-100_000, 100_000)
                rows.append({"asof": dt.datetime.now().strftime("%H:%M"),
                             "frgn": frgn, "orgn": orgn, "sum": frgn + orgn})
                self.state.set_estimate(rows)
            try:
                await asyncio.wait_for(stop.wait(), timeout=rng.uniform(0.2, 0.8))
            except asyncio.TimeoutError:
                pass
