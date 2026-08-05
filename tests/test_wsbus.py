"""웹소켓 세션 버스 — 연결 1개에 등록 N건. 네트워크 없음(가짜 ws·가짜 클라이언트).

KIS 제약은 '세션 수'(1키 1세션)지 구독 건수가 아니다. 종목마다 연결을 새로 열던
구조에서 뒤에 붙은 엔진이 OPSP8996 ALREADY IN USE로 영구 차단되던 운영 결함
(2026-08-05 실측)을 이 버스가 없앤다.
"""
import asyncio

from backend.flow import wsbus


class _FakeWs:
    def __init__(self, inbox=()):
        self.sent = []
        self._inbox = list(inbox)

    async def send(self, msg):
        self.sent.append(msg)

    async def recv(self):
        if self._inbox:
            return self._inbox.pop(0)
        await asyncio.sleep(3600)          # 더 올 게 없으면 조용히 멈춘다


class _FakeClient:
    def __init__(self):
        self.reset = False

    async def approval_key(self):
        return "KEY"

    def reset_approval(self):
        self.reset = True


def _connected(inbox=()):
    """연결이 성립한 상태의 세션(수신 루프는 띄우지 않는다 — 네트워크 미접촉)."""
    s = wsbus.WsSession(_FakeClient())
    s._ws = _FakeWs(inbox)
    return s, s._ws


def test_register_sends_subscribe_once_per_key():
    """같은 (tr_id, tr_key)에 핸들러가 둘 붙어도 구독 프레임은 한 번만 나간다."""
    s, ws = _connected()
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: None))
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: None))
    assert len(ws.sent) == 1
    assert "H0UNCNT0" in ws.sent[0] and "005930" in ws.sent[0]


def test_register_of_different_keys_each_subscribe():
    """종목·TR이 다르면 각각 구독한다 — 한 연결에 등록 N건이 이 버스의 존재 이유."""
    s, ws = _connected()
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: None))
    asyncio.run(s.register("H0UNCNT0", "000660", lambda rec: None))
    asyncio.run(s.register("H0UNPGM0", "005930", lambda rec: None))
    assert len(ws.sent) == 3


def test_unregister_only_unsubscribes_when_last_handler_leaves():
    s, ws = _connected()
    h1, h2 = (lambda rec: None), (lambda rec: None)
    asyncio.run(s.register("H0UNCNT0", "005930", h1))
    asyncio.run(s.register("H0UNCNT0", "005930", h2))
    asyncio.run(s.unregister("H0UNCNT0", "005930", h1))
    assert len(ws.sent) == 1                       # 아직 해지 안 함
    asyncio.run(s.unregister("H0UNCNT0", "005930", h2))
    assert len(ws.sent) == 2                       # 마지막이 빠질 때만 해지
    assert '"tr_type": "0"' in ws.sent[1]          # 해지 프레임


def test_register_before_connect_is_deferred_to_resubscribe():
    """연결 전 등록은 프레임을 못 보낸다 — 접속 시 재구독이 책임진다."""
    s = wsbus.WsSession(_FakeClient())             # _ws 없음(미연결)
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: None))
    ws = _FakeWs()
    s._ws = ws
    asyncio.run(s._resubscribe_all("KEY"))
    assert len(ws.sent) == 1 and "005930" in ws.sent[0]


def test_resubscribe_all_after_reconnect():
    """재접속하면 살아 있는 등록을 전부 다시 구독해야 한다."""
    s, _ = _connected()
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: None))
    asyncio.run(s.register("H0MFCNT0", "101W09", lambda rec: None))
    ws2 = _FakeWs()
    s._ws = ws2
    asyncio.run(s._resubscribe_all("KEY"))
    assert len(ws2.sent) == 2


def test_resubscribe_clears_sent_marks_so_next_register_still_works():
    """재접속 후에도 신규 등록이 구독 프레임을 낸다 — 이전 연결의 '보냄' 표시가
    남아 있으면 새 연결에서 조용히 구독이 누락된다."""
    s, _ = _connected()
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: None))
    ws2 = _FakeWs()
    s._ws = ws2
    asyncio.run(s._resubscribe_all("KEY"))
    asyncio.run(s.register("H0UNCNT0", "000660", lambda rec: None))
    assert len(ws2.sent) == 2                      # 재구독 1 + 신규 1


def test_dispatch_routes_records_to_matching_handler():
    got = {"stock": [], "futures": []}
    s, _ = _connected()
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: got["stock"].append(rec)))
    asyncio.run(s.register("H0MFCNT0", "101W09", lambda rec: got["futures"].append(rec)))
    s._dispatch("H0UNCNT0", [["005930", "1", "2"]])
    s._dispatch("H0MFCNT0", [["101W09", "9", "8"]])
    s._dispatch("H0STASP0", [["005930", "x"]])      # 등록 안 한 TR은 무시
    s._dispatch("H0UNCNT0", [["000660", "y"]])      # 등록 안 한 종목도 무시
    assert got["stock"] == [["005930", "1", "2"]]
    assert got["futures"] == [["101W09", "9", "8"]]


def test_dispatch_survives_handler_exception():
    """한 종목 화면의 핸들러가 터져도 다른 종목 수신이 멈추면 안 된다."""
    got = []
    s, _ = _connected()

    def boom(rec):
        raise ValueError("핸들러 결함")

    asyncio.run(s.register("H0UNCNT0", "005930", boom))
    asyncio.run(s.register("H0UNCNT0", "005930", lambda rec: got.append(rec)))
    s._dispatch("H0UNCNT0", [["005930", "1"]])
    assert got == [["005930", "1"]]


def test_get_returns_one_session_per_process():
    """1키 1세션 — 소비자가 몇이든 연결 소유자는 하나뿐이어야 한다."""
    wsbus.WsSession._inst = None
    try:
        a = wsbus.WsSession.get(_FakeClient())
        b = wsbus.WsSession.get(_FakeClient())
        assert a is b
    finally:
        wsbus.WsSession._inst = None


# ── FlowEngine 연동 — 엔진은 연결을 소유하지 않고 등록만 한다 ──

class _Bus:
    """등록/해제만 기록하는 가짜 버스(연결 없음)."""

    def __init__(self, connected=True, note=""):
        self.reg, self.unreg, self.started = [], [], 0
        self.status = {"connected": connected, "note": note}

    def start(self):
        self.started += 1

    async def register(self, tr_id, tr_key, handler):
        self.reg.append((tr_id, tr_key, handler))

    async def unregister(self, tr_id, tr_key, handler):
        self.unreg.append((tr_id, tr_key))


def _engine(monkeypatch, bus):
    monkeypatch.setattr(wsbus.WsSession, "get", classmethod(lambda cls, client: bus))
    from backend.flow.engine import FlowEngine
    FlowEngine._registry.pop("005930", None)
    return FlowEngine("005930")


def test_engine_registers_both_tr_ids_and_releases_on_stop(monkeypatch):
    """엔진은 체결·프로그램 두 건을 등록하고, 멈출 때 둘 다 해제한다."""
    bus = _Bus()
    eng = _engine(monkeypatch, bus)
    asyncio.run(eng._ws_attach(_FakeClient()))
    assert bus.started == 1
    assert sorted(t for t, _k, _h in bus.reg) == ["H0UNCNT0", "H0UNPGM0"]
    assert {k for _t, k, _h in bus.reg} == {"005930"}
    asyncio.run(eng._ws_detach())
    assert sorted(t for t, _k in bus.unreg) == ["H0UNCNT0", "H0UNPGM0"]


def test_engine_handlers_feed_state(monkeypatch):
    """등록한 핸들러가 실제로 체결·프로그램을 FlowState에 넣는다."""
    bus = _Bus()
    eng = _engine(monkeypatch, bus)
    asyncio.run(eng._ws_attach(_FakeClient()))
    by_tr = {tr: h for tr, _k, h in bus.reg}
    # H0STCNT0 계열 레코드(0=코드, 1=체결시각, 2=현재가 …)
    by_tr["H0UNCNT0"](["005930", "133005", "71000", "2", "500", "0.71",
                       "70500", "71200", "70400", "70900", "71000", "10",
                       "1234567", "890", "1", "2", "3", "4", "5", "6",
                       "7", "8", "120.5"])
    by_tr["H0UNPGM0"](["005930", "133005", "1", "2", "3", "4", "-5", "-6"])
    snap = eng.state.snapshot()
    assert snap["market"]["price"] == 71000        # 체결 반영
    assert snap["program"]["net_qty"] == -5        # 프로그램 반영


def test_engine_mirrors_bus_connection_status(monkeypatch):
    """상태 문구는 버스가 진실이다 — 엔진이 자기 판단으로 '연결됨'을 쓰면
    폴백(_ws_fallback)이 끊긴 줄 모르고 화면을 안 채운다."""
    bus = _Bus(connected=False, note="실시간 연결 끊김 — 30초 후 재접속")
    eng = _engine(monkeypatch, bus)
    asyncio.run(eng._ws_attach(_FakeClient()))
    st = eng.state.snapshot()["status"]
    assert st["connected"] is False and "재접속" in st["note"]

    bus.status = {"connected": True, "note": ""}
    eng._sync_status()
    st2 = eng.state.snapshot()["status"]
    assert st2["connected"] is True and st2["note"] == ""


def test_close_swallows_the_cancellation_it_caused():
    """close()가 자기가 취소한 태스크의 CancelledError를 삼켜야 한다.

    `except Exception`은 이걸 **못 잡는다** — CancelledError는 Python 3.8부터
    BaseException 상속이라 Exception 밖에 있다. 놓치면 FastAPI 종료 훅이
    'Application shutdown failed'로 끝난다(2026-08-05 실서버 재기동 로그에서
    실제로 났다). 프로세스는 어차피 죽지만, 뒤따르는 정리 작업이 통째로 건너뛰어진다.
    """
    async def go():
        s = wsbus.WsSession(_FakeClient())
        s._stop = asyncio.Event()

        async def _forever():
            await asyncio.sleep(3600)

        s._task = asyncio.ensure_future(_forever())
        await asyncio.sleep(0)             # 태스크가 실제로 돌기 시작하게
        await s.close()                    # 여기서 CancelledError가 새면 실패
        assert s._task is None
        assert s.status["connected"] is False

    asyncio.run(go())


def test_close_all_completes_even_when_the_loop_task_is_running():
    """종료 훅 경로 전체 — close_all()이 예외 없이 끝나고 싱글턴이 비워진다."""
    async def go():
        s = wsbus.WsSession.get(_FakeClient())

        async def _forever():
            await asyncio.sleep(3600)

        s._stop = asyncio.Event()
        s._task = asyncio.ensure_future(_forever())
        await asyncio.sleep(0)
        await wsbus.WsSession.close_all()
        assert wsbus.WsSession._inst is None

    asyncio.run(go())
