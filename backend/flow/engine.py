from __future__ import annotations

"""FlowEngine — 종목 하나의 수급 소스(라이브/데모)를 굴리고 스냅샷을 구독자에게 공급.

- 코드별 싱글턴(get). 첫 구독자에서 소스 태스크 lazy 시작, 구독자 0이면 정지.
- 모드: KIS 키가 있으면 live, 없거나 SM_FLOW_MODE=demo면 demo.
- live: 웹소켓(체결 H0STCNT0 + 프로그램 H0STPGM0) 수신 + REST 폴링(잠정 추정·일별)
  + 시작 시 백필(프로그램추이). 끊기면 지수 백오프 재접속.
"""

import asyncio
import logging

from backend.config import settings
from backend.flow import kis
from backend.flow.demo import DemoSource, lookup_stock
from backend.flow.models import FlowState

log = logging.getLogger(__name__)

_POLL_SEC = 300      # 잠정 추정치 폴링 간격(실제 갱신은 하루 4회라 5분이면 충분)
_DAILY_SEC = 1800    # 일별 확정 재조회 간격(장 종료 후 당일분 반영용)


class FlowEngine:
    _registry: dict = {}

    def __init__(self, code: str, interval: float = 1.0):
        self.code, self.interval = code, interval
        name, _ = lookup_stock(code)
        self.state = FlowState(code, name, self.mode)
        self._subs = 0
        self._task = None
        self._stop = None

    @classmethod
    def get(cls, code: str) -> "FlowEngine":
        if code not in cls._registry:
            cls._registry[code] = cls(code)
        return cls._registry[code]

    @property
    def mode(self) -> str:
        if settings.flow_mode == "demo":
            return "demo"
        return "live" if (settings.kis_app_key and settings.kis_app_secret) else "demo"

    # ── 구독 ──────────────────────────────────────────────
    async def subscribe(self):
        """1초(interval)마다 전체 스냅샷 dict를 내보내는 비동기 제너레이터."""
        self._subs += 1
        self._ensure_running()
        try:
            yield self.state.snapshot()
            while True:
                await asyncio.sleep(self.interval)
                yield self.state.snapshot()
        finally:
            self._subs -= 1
            if self._subs <= 0:
                await self.shutdown()

    def _ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self.state.mode = self.mode  # 구독 시점 기준으로 모드 확정
            self._stop = asyncio.Event()
            runner = self._run_live if self.mode == "live" else self._run_demo
            self._task = asyncio.get_event_loop().create_task(runner(self._stop))

    async def shutdown(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    # ── 소스 ──────────────────────────────────────────────
    async def _run_demo(self, stop: asyncio.Event) -> None:
        await DemoSource(self.state).run(stop)

    async def _run_live(self, stop: asyncio.Event) -> None:
        client = kis.KisClient(settings.kis_app_key, settings.kis_app_secret,
                               settings.cache_dir)
        try:
            await client.token()  # 인증 검증 — 실패 시 데모 강등
        except Exception as e:  # noqa: BLE001 — 원인 불문 화면은 살린다
            log.warning("KIS 인증 실패 — 데모로 전환", exc_info=True)
            self.state.mode = "demo"
            self.state.set_status(note=f"KIS 인증 실패({e}) — 데모 데이터로 표시 중")
            await DemoSource(self.state).run(stop)
            return
        await asyncio.gather(self._poll_rest(client, stop),
                             self._ws_loop(client, stop))

    async def _poll_rest(self, client: "kis.KisClient", stop: asyncio.Event) -> None:
        last_daily = 0.0
        loop = asyncio.get_event_loop()
        # 시작 백필: 프로그램추이(장중 재접속 대비) — 실패해도 WS 누적으로 계속
        try:
            pts = await client.program_trend(self.code)
            if pts:
                self.state.set_program_total(pts[-1]["net_qty"],
                                             pts[-1]["net_value"], pts)
        except Exception:
            log.warning("프로그램추이 백필 실패", exc_info=True)
        while not stop.is_set():
            try:
                rows = await client.estimate(self.code)
                if rows:
                    self.state.set_estimate(rows)
                if loop.time() - last_daily > _DAILY_SEC:
                    last_daily = loop.time()
                    daily = await client.daily_investor(self.code)
                    if daily:
                        self.state.set_daily(daily)
            except Exception:
                log.warning("KIS REST 폴링 실패 — 다음 주기에 재시도", exc_info=True)
                self.state.set_status(note="KIS 조회 일시 실패 — 재시도 중")
            try:
                await asyncio.wait_for(stop.wait(), timeout=_POLL_SEC)
            except asyncio.TimeoutError:
                pass

    async def _ws_loop(self, client: "kis.KisClient", stop: asyncio.Event) -> None:
        import websockets
        backoff = 1
        while not stop.is_set():
            try:
                key = await client.approval_key()
                async with websockets.connect(kis.WS_URL, ping_interval=None) as ws:
                    await ws.send(kis.build_subscribe(key, "H0STCNT0", self.code))
                    await ws.send(kis.build_subscribe(key, "H0STPGM0", self.code))
                    self.state.set_status(connected=True, note="")
                    backoff = 1
                    while not stop.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        if kis.is_pingpong(raw):
                            await ws.send(raw)  # 원문 그대로 에코(연결 유지 필수)
                            continue
                        parsed = kis.split_frames(raw)
                        if not parsed:
                            continue
                        kind, payload = parsed
                        if kind != "data":
                            continue
                        tr_id, records = payload
                        for rec in records:
                            if tr_id in ("H0STCNT0", "H0UNCNT0"):
                                self.state.apply_tick(kis.parse_ccnl(rec))
                            elif tr_id in ("H0STPGM0", "H0UNPGM0"):
                                self.state.apply_program(kis.parse_program(rec))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("KIS 웹소켓 끊김 — %ds 후 재접속", backoff, exc_info=True)
                self.state.set_status(connected=False,
                                      note=f"실시간 연결 끊김 — {backoff}초 후 재접속")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60)
