from __future__ import annotations

"""KIS 웹소켓 세션 버스 — 연결 1개에 등록 N건.

KIS 제약은 **세션 수**(1키 1세션)지 구독 건수가 아니다. 종목 화면마다 연결을 새로 열면
서로를 걷어차, 뒤에 붙은 쪽이 `OPSP8996 ALREADY IN USE appkey`로 영구 차단된다
(2026-08-05 운영 실측: 두 종목을 열어두면 한쪽은 하루 종일 실시간이 오지 않고 10초 REST
폴백으로만 연명 — 화면이 살아 보여서 눈치채기 어려웠다).

그래서 연결은 이 모듈이 단독으로 소유하고, 소비자는 `(tr_id, tr_key)`로 등록만 한다.
재접속 백오프·핑퐁 에코·구독 거부·승인키 만료 처리는 기존 `engine._ws_loop`에서
동작 그대로 옮겨왔다. Python 3.9 호환."""

import asyncio
import logging
import random

from backend.flow import kis

log = logging.getLogger(__name__)

_INITIAL_BACKOFF = 5      # 재시작 직후 KIS가 이전 세션 정리 전까지 EOF로 거부(실측)
_MAX_BACKOFF = 60
_REJECT_BACKOFF = 30      # 구독 거부는 길게 물러난다(짧게 두드리면 보호가 연장됨)
_RECV_TIMEOUT = 60        # 이 시간 무수신이면 죽은 연결로 보고 재접속


class WsSession:
    """프로세스에 하나뿐인 KIS 웹소켓 연결. `get()`으로만 얻는다."""

    _inst = None

    def __init__(self, client):
        self._client = client
        self._subs = {}        # (tr_id, tr_key) -> [handler, ...]
        self._sent = set()     # 지금 연결에서 구독 프레임을 보낸 키(중복 구독 방지)
        self._ws = None
        self._task = None
        self._stop = None
        self.status = {"connected": False, "note": ""}

    @classmethod
    def get(cls, client) -> "WsSession":
        if cls._inst is None:
            cls._inst = cls(client)
        return cls._inst

    # ── 수명 ──────────────────────────────────────────────
    def start(self) -> None:
        """수신 루프를 (없으면) 띄운다. 실행 중인 이벤트 루프 안에서 호출할 것.

        등록과 분리한 이유: register가 연결을 띄우면 테스트가 등록만 검증하려 해도
        실제 소켓을 열게 된다(테스트는 네트워크 미접촉이 규칙)."""
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._task = asyncio.ensure_future(self._run())

    async def close(self) -> None:
        """클로즈 프레임과 함께 연결을 정리한다 — 좀비 세션을 남기지 않는다."""
        if self._stop is not None:
            self._stop.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except Exception:  # noqa: BLE001 — 정리 경로에선 원인 불문 넘어간다
                pass
        self._ws, self._sent = None, set()
        self.status = {"connected": False, "note": ""}

    @classmethod
    async def close_all(cls) -> None:
        """프로세스 종료 훅용 — 세션을 닫고 싱글턴을 비운다."""
        inst, cls._inst = cls._inst, None
        if inst is not None:
            await inst.close()

    # ── 등록 ──────────────────────────────────────────────
    async def register(self, tr_id: str, tr_key: str, handler) -> None:
        """`handler(record: list) -> None`을 (tr_id, tr_key)에 붙인다.

        같은 키에 핸들러가 여럿 붙어도 구독 프레임은 처음 한 번만 나간다."""
        key = (tr_id, tr_key)
        self._subs.setdefault(key, []).append(handler)
        await self._ensure_subscribed(key)

    async def unregister(self, tr_id: str, tr_key: str, handler) -> None:
        """마지막 핸들러가 빠질 때만 구독을 해지한다."""
        key = (tr_id, tr_key)
        handlers = self._subs.get(key)
        if not handlers:
            return
        if handler in handlers:
            handlers.remove(handler)
        if handlers:
            return
        self._subs.pop(key, None)
        if self._ws is not None and key in self._sent:
            self._sent.discard(key)
            try:
                await self._send_sub(key, False)
            except Exception:  # noqa: BLE001 — 해지 실패는 재접속이 정리한다
                log.warning("구독 해지 실패 — 재접속 시 정리됨", exc_info=True)

    async def _ensure_subscribed(self, key) -> None:
        """이 연결에서 아직 안 보낸 키만 구독 프레임을 보낸다.

        `_sent` 표시는 await **전에** 찍는다 — 그래야 전송 중에 같은 키가 다시
        등록돼도 프레임이 두 번 나가지 않는다."""
        if self._ws is None or key in self._sent:
            return
        self._sent.add(key)
        try:
            await self._send_sub(key, True)
        except Exception:
            self._sent.discard(key)
            raise

    async def _send_sub(self, key, on: bool) -> None:
        approval = await self._client.approval_key()
        await self._ws.send(kis.build_subscribe(approval, key[0], key[1], on))

    async def _resubscribe_all(self, approval_key: str) -> None:
        """재접속 직후 — 살아 있는 등록을 전부 다시 구독한다.

        이전 연결의 `_sent` 표시를 반드시 비운다. 남겨두면 새 연결에서 구독이
        조용히 누락돼 '연결은 됐는데 데이터가 안 오는' 상태가 된다."""
        self._sent = set()
        for key in list(self._subs):
            self._sent.add(key)
            await self._ws.send(kis.build_subscribe(approval_key, key[0], key[1], True))

    def _dispatch(self, tr_id: str, records: list) -> None:
        """레코드의 0번 필드가 tr_key(종목·종목선물 코드)다 — 등록된 핸들러에만 넘긴다."""
        for rec in records:
            tr_key = rec[0] if rec else ""
            for handler in list(self._subs.get((tr_id, tr_key), [])):
                try:
                    handler(rec)
                except Exception:  # noqa: BLE001 — 한 화면의 결함이 전체 수신을 못 멈춘다
                    log.warning("웹소켓 핸들러 예외 — 건너뜀", exc_info=True)

    # ── 수신 루프 ─────────────────────────────────────────
    async def _run(self) -> None:
        import websockets

        backoff = _INITIAL_BACKOFF
        while not self._stop.is_set():
            try:
                approval = await self._client.approval_key()
                async with websockets.connect(kis.WS_URL, ping_interval=None) as ws:
                    self._ws = ws
                    await self._resubscribe_all(approval)
                    self.status = {"connected": True, "note": ""}
                    backoff = _INITIAL_BACKOFF
                    while not self._stop.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=_RECV_TIMEOUT)
                        if kis.is_pingpong(raw):
                            await ws.send(raw)   # 원문 그대로 에코(연결 유지 필수)
                            continue
                        parsed = kis.split_frames(raw)
                        if not parsed:
                            continue
                        kind, payload = parsed
                        if kind == "json":
                            err = kis.subscribe_error(payload)
                            if err:               # 구독 거부 — 길게 물러나 재시도
                                backoff = max(backoff, _REJECT_BACKOFF)
                                # 승인키 만료(OPSP0011)면 캐시 폐기 → 다음 접속서 재발급.
                                # 좀비 세션(ALREADY)은 새 승인키로 안 나으므로 대기만.
                                if kis.is_invalid_approval(err):
                                    self._client.reset_approval()
                                raise RuntimeError("구독 거부: %s" % err)
                            continue
                        if kind == "data":
                            self._dispatch(payload[0], payload[1])
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — 원인 불문 재접속(화면은 폴백이 채운다)
                self._ws, self._sent = None, set()
                log.warning("KIS 웹소켓 끊김 — %ds 후 재접속", backoff, exc_info=True)
                self.status = {"connected": False,
                               "note": "실시간 연결 끊김 — %d초 후 재접속" % backoff}
                try:
                    await asyncio.wait_for(self._stop.wait(),
                                           timeout=backoff + random.uniform(0, 3))
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, _MAX_BACKOFF)
        self._ws, self._sent = None, set()
        self.status = {"connected": False, "note": ""}
