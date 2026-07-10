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
_LINGER_SEC = 300    # 구독자 0명 후 소스 유지 시간 — 웹소켓 재연결 churn이
                     # KIS 서버측 절단(EOF)을 유발하므로(실측) 즉시 해체 금지


class FlowEngine:
    _registry: dict = {}

    def __init__(self, code: str, interval: float = 1.0):
        self.code, self.interval = code, interval
        name, _ = lookup_stock(code)
        self.state = FlowState(code, name, self.mode)
        self._subs = 0
        self._task = None
        self._stop = None
        self._stop_task = None   # 지연 정지 예약
        self._client = None      # KisClient 재사용(approval_key 메모리 캐시 유지)

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
        if self._stop_task is not None:
            self._stop_task.cancel()
            self._stop_task = None
        self._ensure_running()
        try:
            yield self.state.snapshot()
            while True:
                await asyncio.sleep(self.interval)
                yield self.state.snapshot()
        finally:
            self._subs -= 1
            if self._subs <= 0:
                self._stop_task = asyncio.get_event_loop().create_task(
                    self._delayed_stop())

    async def _delayed_stop(self) -> None:
        try:
            await asyncio.sleep(_LINGER_SEC)
        except asyncio.CancelledError:
            return
        if self._subs <= 0:
            self._stop_task = None
            await self.shutdown()

    def _ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self.state.mode = self.mode  # 구독 시점 기준으로 모드 확정
            self._stop = asyncio.Event()
            runner = self._run_live if self.mode == "live" else self._run_demo
            self._task = asyncio.get_event_loop().create_task(runner(self._stop))

    async def shutdown(self) -> None:
        if self._stop_task is not None:
            self._stop_task.cancel()
            self._stop_task = None
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
        if self._client is None:  # 재사용 — approval_key 재발급 최소화
            self._client = kis.KisClient(settings.kis_app_key,
                                         settings.kis_app_secret,
                                         settings.cache_dir)
        client = self._client
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
        last_daily = None  # None=아직 안 가져옴(모노토닉 시계는 0 근처에서 시작할 수 있음)
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
            ok = True
            # 추정과 일별은 서로 격리 — 한쪽(간헐 500 관찰됨)이 다른 쪽을 못 막는다
            try:
                rows = await client.estimate(self.code)
                if rows:
                    self.state.set_estimate(rows)
            except Exception:
                ok = False
                log.warning("KIS 추정치 조회 실패 — 재시도 예정", exc_info=True)
            try:
                if last_daily is None or loop.time() - last_daily > _DAILY_SEC:
                    daily = kis.drop_empty_daily(await client.daily_investor(self.code))
                    if daily:
                        self.state.set_daily(daily)
                    detail = await client.investor_detail(self.code)
                    if detail:
                        self.state.set_detail(detail)
                    last_daily = loop.time()  # 성공 시에만 갱신(실패 시 곧 재시도)
            except Exception:
                ok = False
                log.warning("KIS 일별/세부 수급 조회 실패 — 재시도 예정", exc_info=True)
            filled = bool(self.state.snapshot()["estimate"]["rows"])
            if not ok:
                self.state.set_status(note="KIS 조회 일시 실패 — 재시도 중")
            elif self.state.snapshot()["status"]["note"].startswith("KIS 조회"):
                self.state.set_status(note="")
            # 실패했거나 잠정 패널이 아직 비었으면 짧게(60s), 정상 정착 후엔 5분
            timeout = 60 if (not ok or not filled) else _POLL_SEC
            try:
                await asyncio.wait_for(stop.wait(), timeout=timeout)
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
