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
