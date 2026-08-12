from __future__ import annotations

"""FlowEngine — 종목 하나의 수급 소스(라이브/데모)를 굴리고 스냅샷을 구독자에게 공급.

- 코드별 싱글턴(get). 첫 구독자에서 소스 태스크 lazy 시작, 구독자 0이면 정지.
- 모드: KIS 키가 있으면 live, 없거나 SM_FLOW_MODE=demo면 demo.
- live: 웹소켓(체결 H0STCNT0 + 프로그램 H0STPGM0) 수신 + REST 폴링(잠정 추정·일별)
  + 시작 시 백필(프로그램추이). 끊기면 지수 백오프 재접속.
"""

import asyncio
import datetime as dt
import logging

from backend.config import settings
from backend.flow import adr
from backend.flow import credit
from backend.flow import exvol
from backend.flow import kis
from backend.flow import kst
from backend.flow import member
from backend.flow import scanner
from backend.flow import shortbal
from backend.flow import shortsale
from backend.flow.demo import DemoSource, lookup_stock
from backend.flow.models import FlowState

log = logging.getLogger(__name__)

_POLL_SEC = 60       # 잠정 추정치·장중 세부 폴링 간격(슬롯 발표를 1분 내 반영)
_DAILY_SEC = 1800    # 일별 확정 재조회 간격(장 종료 후 당일분 반영용)
_LINGER_SEC = 300    # 구독자 0명 후 소스 유지 시간 — 웹소켓 재연결 churn이
                     # KIS 서버측 절단(EOF)을 유발하므로(실측) 즉시 해체 금지
_FALLBACK_SEC = 10   # 웹소켓 공백 시 REST 시세 폴백 주기(화면이 비지 않게)
_STATUS_SEC = 1      # 공유 세션(wsbus)의 연결 상태를 화면 상태로 옮겨 적는 주기


def _program_backfill_ok() -> bool:
    """00~08시(NXT 프리마켓 전, 거래 없음)엔 프로그램 백필 금지 — 이 시간대
    TR 응답이 전일 추이일 가능성(미검증)이 있어 자정 리셋을 되살릴 수 있다."""
    return kst.now().hour >= 8


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
        self._day = kst.today()  # 당일 한정 패널의 기준일(날짜 변경 감지용, KST)
        self._bus = None         # 공유 웹소켓 세션(wsbus) — 연결은 저쪽이 소유
        self._ws_regs = []       # 이 엔진이 버스에 걸어둔 (tr_id, handler)

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
        # 취소가 _ws_link의 finally보다 먼저 닿을 수 있어 여기서 한 번 더 반납한다
        # (_ws_detach는 멱등). 안 하면 화면을 닫은 종목의 구독이 버스에 남는다.
        await self._ws_detach()

    def _rollover_if_new_day(self) -> None:
        """엔진·FlowState는 레지스트리에 영속 → 서버가 주말을 넘겨 떠 있으면
        금요일 잠정/프로그램/테이프가 월요일 화면에 남는다(실사고 2026-07-13).
        장전엔 잠정 TR이 빈 배열이라 'if rows' 가드가 갱신을 건너뛰므로
        날짜가 바뀐 순간 당일 한정 상태를 명시적으로 비운다."""
        today = kst.today()
        if today != self._day:
            self._day = today
            self.state.reset_intraday()
            log.info("날짜 변경(%s) — 당일 한정 패널 초기화", today)

    # ── 소스 ──────────────────────────────────────────────
    async def _run_demo(self, stop: asyncio.Event) -> None:
        await DemoSource(self.state).run(stop)

    async def _run_live(self, stop: asyncio.Event) -> None:
        if self._client is None:  # 재사용 — approval_key 재발급 최소화
            self._client = kis.KisClient(settings.kis_app_key,
                                         settings.kis_app_secret,
                                         settings.cache_dir,
                                         market_div=settings.market_div)
        client = self._client
        try:
            await client.token()  # 인증 검증 — 실패 시 데모 강등
        except Exception as e:  # noqa: BLE001 — 원인 불문 화면은 살린다
            log.warning("KIS 인증 실패 — 데모로 전환", exc_info=True)
            self.state.mode = "demo"
            self.state.set_status(note=f"KIS 인증 실패({e}) — 데모 데이터로 표시 중")
            await DemoSource(self.state).run(stop)
            return
        try:
            await asyncio.gather(self._poll_rest(client, stop),
                                 self._ws_link(client, stop),
                                 self._ws_fallback(client, stop))
        finally:
            # gather는 형제를 죽이지 않는다 — 한 갈래가 예외로 죽으면 나머지 둘도 세운다.
            # 안 세우면 다음 _ensure_running이 self._stop을 새 Event로 갈아치워, 이전
            # Event만 보는 고아 폴러가 재기동 전까지 KIS를 계속 두드린다(재접속마다 배가).
            stop.set()

    async def _poll_rest(self, client: "kis.KisClient", stop: asyncio.Event) -> None:
        last_daily = None  # None=아직 안 가져옴(모노토닉 시계는 0 근처에서 시작할 수 있음)
        loop = asyncio.get_event_loop()
        self._rollover_if_new_day()  # 백필 전에 — 전일 잔재 위에 덧그리지 않게
        # 시작 백필: 프로그램추이(장중 재접속 대비) — 실패해도 WS 누적으로 계속
        try:
            if _program_backfill_ok():
                pts = await client.program_trend(self.code)
                if pts:
                    self.state.set_program_total(pts[-1]["net_qty"],
                                                 pts[-1]["net_value"], pts)
        except Exception:
            log.warning("프로그램추이 백필 실패", exc_info=True)
        while not stop.is_set():
            ok = True
            self._rollover_if_new_day()
            # 추정과 일별은 서로 격리 — 한쪽(간헐 500 관찰됨)이 다른 쪽을 못 막는다
            try:
                rows = await client.estimate(self.code)
                if rows:
                    self.state.set_estimate(rows)
            except Exception:
                ok = False
                log.warning("KIS 추정치 조회 실패 — 재시도 예정", exc_info=True)
            try:
                # 장중 기관 부분 세부 — 가집계 상위30 리스트(60s 공유 캐시)에서 추출
                d = scanner.intraday_detail_for(
                    self.code, await scanner.fit_lists(client))
                if d:
                    self.state.set_estimate_detail(
                        dict(d, asof=kst.now().strftime("%H:%M")))
            except Exception:
                ok = False
                log.warning("가집계 장중 세부 조회 실패 — 재시도 예정", exc_info=True)
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
            try:
                # 대차잔고(T+1) — 매분(_POLL_SEC) 불러도 모듈 내부의 일 캐시 +
                # 실패 포함 1h 스로틀이 원격 조회를 하루 한두 번으로 제한.
                # 최초 백필(빈 캐시)만 ~30초 걸림(1회성, 이 주기 지연 수용).
                # KIS와 무관한 소스라 실패해도 상단 노트는 건드리지 않는다.
                sb = await shortbal.get_history(self.code, settings.cache_dir)
                if sb.get("rows"):
                    self.state.set_short(sb)
            except Exception:
                log.warning("대차잔고 조회 실패 — 다음 주기 재시도", exc_info=True)
            # 아래 셋은 부가 패널 — 각자 격리, 실패해도 ok/노트는 건드리지 않는다.
            # (모듈 내부 TTL 캐시가 원격 호출을 60s/1h로 제한 — 매분 불러도 안전)
            try:
                q = await adr.get_quote(client, self.code)
                if q:
                    self.state.set_adr(q)
            except Exception:
                log.warning("ADR/환율 조회 실패 — 다음 주기 재시도", exc_info=True)
            try:
                cr = await credit.get_history(client, self.code)
                if cr.get("rows"):
                    self.state.set_credit(cr)
            except Exception:
                log.warning("신용잔고 조회 실패 — 다음 주기 재시도", exc_info=True)
            try:
                ss = await shortsale.get_history(client, self.code)
                if ss.get("rows"):
                    self.state.set_shortsale(ss)
            except Exception:
                log.warning("공매도 일별 조회 실패 — 다음 주기 재시도", exc_info=True)
            try:
                xv = await exvol.get_split(client, self.code)
                if xv.get("krx") or xv.get("nxt"):
                    self.state.set_exvol(xv)
            except Exception:
                log.warning("거래소별 거래량 조회 실패 — 다음 주기 재시도", exc_info=True)
            try:
                mb = await member.get_member(client, self.code)
                if mb.get("sell") or mb.get("buy"):
                    self.state.set_member(mb)
            except Exception:
                log.warning("거래원 조회 실패 — 다음 주기 재시도", exc_info=True)
            if not ok:
                self.state.set_status(note="KIS 조회 일시 실패 — 재시도 중")
            elif self.state.snapshot()["status"]["note"].startswith("KIS 조회"):
                self.state.set_status(note="")
            try:
                await asyncio.wait_for(stop.wait(), timeout=_POLL_SEC)
            except asyncio.TimeoutError:
                pass

    async def _ws_fallback(self, client: "kis.KisClient",
                           stop: asyncio.Event) -> None:
        """웹소켓 재접속 창(재시작 직후 1키 1세션 보호 등)에도 화면이 비지 않게
        REST 현재가/프로그램으로 10초 간격 폴백. 연결되면 아무것도 안 한다."""
        n = 0
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=_FALLBACK_SEC)
                return
            except asyncio.TimeoutError:
                pass
            if self.state.snapshot()["status"]["connected"]:
                continue
            self._rollover_if_new_day()  # 자정 직후 이 폴백이 전일 프로그램
            n += 1                       # 누적을 되살리지 않게 기준일 먼저 갱신
            try:
                p = await client.price(self.code)
                if p:
                    self.state.set_market(
                        dict(p, time=kst.now().strftime("%H:%M:%S")))
                # 프로그램 누적은 30초에 한 번이면 충분. 00~08시 생략(_program_backfill_ok)
                if n % 3 == 1 and _program_backfill_ok():
                    pts = await client.program_trend(self.code)
                    if pts:
                        self.state.set_program_total(pts[-1]["net_qty"],
                                                     pts[-1]["net_value"], pts)
            except Exception:
                log.warning("REST 시세 폴백 실패 — 다음 주기 재시도", exc_info=True)

    async def _ws_link(self, client: "kis.KisClient", stop: asyncio.Event) -> None:
        """실시간 등록을 잡고 정지 신호까지 유지한다 — 연결은 wsbus가 단독 소유한다.

        KIS 제약은 세션 수(1키 1세션)라, 예전처럼 엔진마다 웹소켓을 열면 두 번째
        종목이 OPSP8996 ALREADY IN USE로 영구 차단된다(2026-08-05 운영 실측).
        여기선 등록만 하고, 연결 상태는 버스에서 주기적으로 옮겨 적는다."""
        await self._ws_attach(client)
        try:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_STATUS_SEC)
                except asyncio.TimeoutError:
                    self._sync_status()
        finally:
            await self._ws_detach()

    async def _ws_attach(self, client: "kis.KisClient") -> None:
        """세션 버스에 체결·프로그램 두 건을 등록한다(같은 종목코드가 tr_key)."""
        from backend.flow import wsbus
        ccnl_tr, pgm_tr = kis.ws_tr_ids(settings.market_div)
        self._bus = wsbus.WsSession.get(client)
        self._bus.start()
        self._ws_regs = [(ccnl_tr, self._on_ccnl), (pgm_tr, self._on_program)]
        for tr_id, handler in self._ws_regs:
            await self._bus.register(tr_id, self.code, handler)
        self._sync_status()

    async def _ws_detach(self) -> None:
        """등록을 반납한다. 두 번 불러도 안전하다(정지 경로가 둘이라 멱등이어야 한다)."""
        regs, self._ws_regs = self._ws_regs, []
        if self._bus is None:
            return
        for tr_id, handler in regs:
            try:
                await self._bus.unregister(tr_id, self.code, handler)
            except Exception:
                log.warning("웹소켓 등록 반납 실패 — 재접속이 정리함", exc_info=True)

    def _sync_status(self) -> None:
        """연결 상태의 진실은 버스에 있다. 화면 배지와 REST 폴백 판단이 이 값을 본다
        (_ws_fallback가 snapshot()['status']['connected']로 폴백 여부를 정한다)."""
        if self._bus is None:
            return
        self.state.set_status(connected=self._bus.status["connected"],
                              note=self._bus.status["note"])

    def _on_ccnl(self, rec: list) -> None:
        self.state.apply_tick(kis.parse_ccnl(rec))

    def _on_program(self, rec: list) -> None:
        self.state.apply_program(kis.parse_program(rec))
