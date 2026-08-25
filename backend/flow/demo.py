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
from backend.flow import kst
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


DEMO_NOTE = ("데모 데이터(시뮬레이션) — 실데이터가 아닙니다. "
             "KIS 키 입력 시 라이브 전환.")


class DemoSource:
    """FlowState에 가짜 체결·프로그램·잠정·일별 이벤트를 흘려 넣는다."""

    def __init__(self, state, base_price: Optional[float] = None):
        self.state = state
        self.rng = random.Random(int(state.code) if state.code.isdigit() else 42)
        self.base = int(base_price or lookup_stock(state.code)[1] or 100_000)

    def _seed_panels(self) -> None:
        rng, base = self.rng, self.base
        today = kst.today()
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
        # 기관 세부(데모): 최근 확정일 기관계를 세부 주체로 분배 (실제 스키마와 동일)
        last = daily[0]
        parts, remain = [], last["orgn"]
        names = ["연기금", "투신", "금융투자", "사모펀드", "보험", "은행", "기타금융"]
        for name in names[:-1]:
            q = int(remain * rng.uniform(-0.4, 0.6))
            parts.append({"name": name, "qty": q, "value": q * base})
            remain -= q
        parts.append({"name": names[-1], "qty": remain, "value": remain * base})
        parts.append({"name": "기타법인", "qty": rng.randint(-20_000, 20_000),
                      "value": 0})
        parts.sort(key=lambda r: abs(r["qty"]), reverse=True)
        self.state.set_detail({"date": last["date"], "rows": parts})
        frgn = rng.randint(-200_000, 200_000)
        orgn = rng.randint(-100_000, 100_000)
        self.state.set_estimate([{"asof": "10:00", "frgn": frgn, "orgn": orgn,
                                  "sum": frgn + orgn}])
        # 장중 부분 세부(데모): 잠정 기관계를 5개 주체로 분배
        ed, rem = [], orgn
        for name in ("투신", "연기금", "보험", "은행"):
            q = int(rem * rng.uniform(-0.3, 0.6))
            ed.append({"name": name, "qty": q, "value": q * base})
            rem -= q
        ed.append({"name": "기타금융", "qty": rem, "value": rem * base})
        ed.sort(key=lambda r: abs(r["qty"]), reverse=True)
        etc = rng.randint(-20_000, 20_000)
        self.state.set_estimate_detail({"asof": "10:00", "rows": ed,
                                        "etc_qty": etc, "etc_value": etc * base})
        # 대차잔고(데모): 20거래일 랜덤워크 — 실데이터 스키마와 동일
        srows, bal = [], rng.randint(8_000_000, 15_000_000)
        d = today - dt.timedelta(days=28)
        while d < today:
            if d.weekday() < 5:
                chg = rng.randint(-400_000, 400_000)
                bal = max(0, bal + chg)
                srows.append({"date": d.isoformat(), "qty": bal,
                              "value": bal * base, "chg": chg, "src": "demo"})
            d += dt.timedelta(days=1)
        srows = srows[-20:]
        self.state.set_short({"rows": srows, "asof": srows[-1]["date"],
                              "source": "demo",
                              "updated": kst.now().isoformat(timespec="seconds")})
        # ADR·신용잔고·공매도(데모): 실데이터 스키마와 동일하게 시드
        fx = 1500.0
        self.state.set_adr({"sym": "DEMO", "usd": round(
            base / fx / 10 * (1 + rng.uniform(-0.05, 0.05)), 2),
            "base_usd": round(base / fx / 10, 2), "fx": fx, "ratio": 10.0,
            "us_open": False, "src": "demo",
            "fetched": kst.now().strftime("%H:%M:%S")})
        crows, cbal = [], rng.randint(2_500_000, 4_000_000)
        xrows = []
        d = today - dt.timedelta(days=28)
        while d < today:
            if d.weekday() < 5:
                chg = rng.randint(-120_000, 120_000)
                cbal = max(0, cbal + chg)
                close = int(base * (1 + rng.uniform(-0.03, 0.03)))
                crows.append({"date": d.isoformat(), "qty": cbal,
                              "ratio": round(cbal / 728e6 * 100, 2),
                              "new": max(0, chg), "rdmp": max(0, -chg),
                              "close": close, "value": cbal * close, "chg": chg})
                vol = rng.randint(3_000_000, 8_000_000)
                sq = int(vol * rng.uniform(0.005, 0.06))
                xrows.append({"date": d.isoformat(), "qty": sq, "vol": vol,
                              "ratio": round(sq / vol * 100, 2),
                              "value": sq * close, "close": close})
            d += dt.timedelta(days=1)
        self.state.set_credit({"rows": crows[-20:], "asof": crows[-1]["date"]})
        self.state.set_shortsale({"rows": xrows[-20:], "asof": xrows[-1]["date"]})
        # 거래소별 거래량·거래원(데모): 실데이터 스키마와 동일
        kv, nv = rng.randint(5_000_000, 9_000_000), rng.randint(2_000_000, 6_000_000)
        now_t = kst.now().strftime("%H:%M:%S")
        self.state.set_exvol({
            "krx": {"price": base, "vol": kv, "pbmn": kv * base},
            "nxt": {"price": int(base * 0.998), "vol": nv, "pbmn": nv * base},
            "nxt_share_pct": round(nv / (kv + nv) * 100, 1),
            "sessions": {"pre": int(nv * 0.15), "main": int(nv * 0.65),
                         "after": int(nv * 0.2)},
            "warn": {"move_pct": -0.2, "after_share_pct": 2.5,
                     "text": "시간외 변동 미미", "tone": "flat"},
            "asof": now_t})
        names = [("키움증권", False), ("미래에셋증권", False), ("삼성증권", False),
                 ("JP모간", True), ("모간서울", True), ("KB증권", False),
                 ("NH투자증권", False)]
        def desk_rows():
            picks = rng.sample(names, 5)
            qs = sorted((rng.randint(100_000, 900_000) for _ in picks),
                        reverse=True)
            return [{"name": n, "qty": q, "rlim": round(q / (kv + nv) * 100, 2),
                     "foreign": f} for (n, f), q in zip(picks, qs)]
        sell, buy = desk_rows(), desk_rows()
        g_sell = sum(r["qty"] for r in sell if r["foreign"])
        g_buy = sum(r["qty"] for r in buy if r["foreign"])
        self.state.set_member({"sell": sell, "buy": buy, "basis": "UN",
                               "glob": {"seln": g_sell, "shnu": g_buy,
                                        "ntby": g_buy - g_sell,
                                        "seln_rlim": 0.0, "shnu_rlim": 0.0},
                               "asof": now_t})

    async def run(self, stop: asyncio.Event, note: str = DEMO_NOTE) -> None:
        """note: 호출자가 상단 안내를 갈아끼울 수 있게 — 여기서 set_status를 하므로
        호출자가 미리 써둔 노트는 무조건 덮인다(인증 재시도 중 문구가 이 길로 들어온다)."""
        rng = self.rng
        self._seed_panels()
        self.state.set_status(connected=True, note=note)
        price, acml_vol, acml_value, n, last_est = float(self.base), 0, 0, 0, 0.0
        pgm_qty, pgm_val = 0, 0
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
            now = kst.now().strftime("%H:%M:%S")
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
                pgm_qty += q
                pgm_val += q * tick_px
                # 실제 H0STPGM0 와이어 형식과 동일하게 '당일 누적치'를 보낸다
                self.state.apply_program({"t": now, "sell_qty": max(0, -q),
                                          "sell_value": max(0, -q) * tick_px,
                                          "buy_qty": max(0, q),
                                          "buy_value": max(0, q) * tick_px,
                                          "net_qty": pgm_qty, "net_value": pgm_val})
            elapsed = loop.time() - start
            if elapsed - last_est > 45:  # 잠정치 갱신 시뮬레이션(실제는 하루 4회)
                last_est = elapsed
                rows = list(self.state.snapshot()["estimate"]["rows"])[-4:]
                frgn = rng.randint(-200_000, 200_000)
                orgn = rng.randint(-100_000, 100_000)
                rows.append({"asof": kst.now().strftime("%H:%M"),
                             "frgn": frgn, "orgn": orgn, "sum": frgn + orgn})
                self.state.set_estimate(rows)
            try:
                await asyncio.wait_for(stop.wait(), timeout=rng.uniform(0.2, 0.8))
            except asyncio.TimeoutError:
                pass
