"""FlowEngine(데모 모드) 테스트 — 키 없이 스냅샷 스트림이 흘러야 한다."""
import asyncio

from backend.flow import kst
from backend.flow.engine import FlowEngine


def _run(coro, timeout=5.0):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(coro, timeout))
    finally:
        loop.close()


def test_mode_is_demo_without_keys(monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "kis_app_key", None)
    monkeypatch.setattr(settings, "kis_app_secret", None)
    eng = FlowEngine("000660")
    assert eng.mode == "demo"


def test_forced_demo_even_with_keys(monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "kis_app_key", "k")
    monkeypatch.setattr(settings, "kis_app_secret", "s")
    monkeypatch.setattr(settings, "flow_mode", "demo")
    assert FlowEngine("000660").mode == "demo"
    monkeypatch.setattr(settings, "flow_mode", "")
    assert FlowEngine("000660").mode == "live"


def test_demo_subscribe_yields_snapshots(monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "kis_app_key", None)
    monkeypatch.setattr(settings, "kis_app_secret", None)

    async def first_two():
        eng = FlowEngine("000660", interval=0.1)
        gen = eng.subscribe()
        s1 = await gen.__anext__()
        s2 = await gen.__anext__()
        await gen.aclose()
        await eng.shutdown()
        return s1, s2

    s1, s2 = _run(first_two())
    assert s1["code"] == "000660" and s1["mode"] == "demo"
    for key in ("market", "tape", "program", "estimate", "daily", "status"):
        assert key in s1
    assert s2["ts"] >= s1["ts"]
    # 데모 소스가 굴러가면 시장가·일별 확정·기관 세부가 채워진다
    assert s2["daily"], "데모 일별 수급이 비어있음"
    assert s2["detail"]["rows"], "데모 기관 세부가 비어있음"
    assert s2["estimate_detail"]["rows"], "데모 장중 세부가 비어있음"


def test_unsubscribe_lingers_not_immediate_stop(monkeypatch):
    # 구독자 0명이 되어도 즉시 웹소켓/소스를 해체하지 않는다(유예) —
    # 페이지 새로고침마다 KIS 웹소켓 재연결 churn → 서버측 절단 유발(실측 2026-07-10).
    from backend.config import settings
    monkeypatch.setattr(settings, "kis_app_key", None)
    monkeypatch.setattr(settings, "kis_app_secret", None)

    async def go():
        eng = FlowEngine("000660", interval=0.05)
        gen = eng.subscribe()
        await gen.__anext__()
        await gen.aclose()          # 마지막 구독자 이탈
        assert eng._task is not None and not eng._task.done()  # 소스는 유예로 계속
        assert eng._stop_task is not None                       # 지연 정지 예약됨
        gen2 = eng.subscribe()      # 재구독 → 같은 소스 재사용
        await gen2.__anext__()
        assert eng._stop_task is None  # 예약 취소됨
        await gen2.aclose()
        await eng.shutdown()        # 명시 종료는 즉시
        assert eng._task is None

    _run(go())


def _no_shortbal(monkeypatch):
    """_poll_rest 테스트 공통 — 원격 조회 차단(외부 네트워크 금지).

    ADR도 같이 막는다: 가짜 클라이언트엔 `_get`이 없어 adr.get_quote가 네이버
    폴백으로 새는데, 지금까지는 앞서 도는 test_adr.py가 adr._cache를 데워둔 덕에
    가려져 있었다(이 파일만 돌리면 conftest 네트워크 가드에 걸린다)."""
    from backend.flow import adr, shortbal

    async def fake(code, cache_dir, days=20):
        return {"rows": [{"date": "2026-07-10", "qty": 14140221,
                          "value": 30825681780000, "chg": -280048,
                          "src": "kofia"}],
                "asof": "2026-07-10", "source": "kofia", "updated": "t"}
    monkeypatch.setattr(shortbal, "get_history", fake)

    async def no_adr(client, code):
        return None
    monkeypatch.setattr(adr, "get_quote", no_adr)


def test_poll_rest_daily_survives_estimate_failure(monkeypatch):
    # 실운영에서 관찰(2026-07-10): 추정 TR이 간헐 500 → 일별 조회까지 죽으면 안 된다.
    _no_shortbal(monkeypatch)
    eng = FlowEngine("000660", interval=0.1)

    class FakeClient:
        async def program_trend(self, code):
            return []

        async def estimate(self, code):
            raise RuntimeError("HTTP 500")

        async def daily_investor(self, code):
            return [{"date": "2026-07-09", "prsn": 1, "frgn": -2, "orgn": 1,
                     "close": 100},
                    {"date": "2026-07-10", "prsn": 0, "frgn": 0, "orgn": 0,
                     "close": 100}]  # 미확정 당일 행은 걸러져야 함

        async def investor_detail(self, code):
            return {"date": "2026-07-09",
                    "rows": [{"name": "연기금", "qty": 48907, "value": 113357000000}]}

    async def fake_fit_lists(client=None):
        return {"frgn_buy": [], "frgn_sell": [
            {"mksc_shrn_iscd": "000660", "hts_kor_isnm": "SK하이닉스",
             "ivtr_ntby_qty": "-120000", "ivtr_ntby_tr_pbmn": "-264000",
             "fund_ntby_qty": "35000", "fund_ntby_tr_pbmn": "77000"}],
            "orgn_buy": [], "orgn_sell": []}
    from backend.flow import scanner as sc
    monkeypatch.setattr(sc, "fit_lists", fake_fit_lists)

    async def go():
        stop = asyncio.Event()
        task = asyncio.get_event_loop().create_task(
            eng._poll_rest(FakeClient(), stop))
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.wait_for(task, 5)

    _run(go())
    snap = eng.state.snapshot()
    assert len(snap["daily"]) == 1 and snap["daily"][0]["date"] == "2026-07-09"
    assert snap["detail"]["rows"][0]["name"] == "연기금"  # 세부도 추정 실패와 무관하게 채워짐
    # 장중 부분 세부: 가집계 상위30 리스트에서 자기 종목을 찾아 추출
    est_d = snap["estimate_detail"]
    assert est_d["rows"] and est_d["rows"][0]["name"] == "투신"
    assert est_d["rows"][0]["qty"] == -120000
    assert "재시도" in snap["status"]["note"]  # 실패가 화면에 표시됨
    assert snap["short"]["rows"][0]["qty"] == 14140221  # 대차잔고도 편입됨


def test_new_day_resets_stale_intraday_panels(monkeypatch):
    # 실사고(2026-07-13 월 아침): 서버가 금요일부터 떠 있으면 금요일 잠정치가
    # 월요일 화면에 남는다 — 장전 잠정 TR은 빈 배열이라 'if rows' 가드가
    # 갱신을 건너뛰기 때문. 날짜 변경 감지 시 당일 한정 상태를 비워야 한다.
    import datetime as dt
    _no_shortbal(monkeypatch)
    eng = FlowEngine("000660", interval=0.1)
    eng.state.set_estimate([{"asof": "14:30", "frgn": -812000, "orgn": 135000,
                             "sum": -677000}])  # 금요일 마지막 슬롯
    eng.state.apply_program({"t": "15:29:00", "sell_qty": 1, "sell_value": 1,
                             "buy_qty": 1, "buy_value": 1,
                             "net_qty": -953000, "net_value": -1})
    eng._day = kst.today() - dt.timedelta(days=3)  # 금요일 기동으로 가장

    class FakeClient:
        async def program_trend(self, code):
            return []

        async def estimate(self, code):
            return []  # 장전 실측(2026-07-13 08:56): output2가 빈 배열로 온다

        async def daily_investor(self, code):
            return []

        async def investor_detail(self, code):
            return None

    async def fake_fit_lists(client=None):
        return {"frgn_buy": [], "frgn_sell": [], "orgn_buy": [], "orgn_sell": []}
    from backend.flow import scanner as sc
    monkeypatch.setattr(sc, "fit_lists", fake_fit_lists)

    async def go():
        stop = asyncio.Event()
        task = asyncio.get_event_loop().create_task(
            eng._poll_rest(FakeClient(), stop))
        await asyncio.sleep(0.2)
        stop.set()
        await asyncio.wait_for(task, 5)

    _run(go())
    snap = eng.state.snapshot()
    assert snap["estimate"]["rows"] == []      # 전일 잠정 잔존 금지
    assert snap["program"]["net_qty"] == 0     # 전일 프로그램 누적도 리셋
    # KST로 비교한다 — 엔진의 기준일은 kst.today()다. 러너가 UTC인 CI에서
    # 한국시각 00~09시에 밀어넣으면 UTC 날짜가 하루 뒤처져 여기서 깨졌다
    # (2026-08-10 08:56 KST 푸시가 UTC 08-09로 잡혀 실제로 빨간불).
    assert eng._day == kst.today()


def test_ws_fallback_fills_market_while_disconnected(monkeypatch):
    # 웹소켓 재접속 창(서버 재시작 직후 등)에도 화면이 비지 않도록 REST 폴백
    import backend.flow.engine as engmod
    monkeypatch.setattr(engmod, "_FALLBACK_SEC", 0.05)
    # 프로그램 백필의 00~08시 가드와 무관하게 검증(테스트 결정성)
    monkeypatch.setattr(engmod, "_program_backfill_ok", lambda: True)
    eng = FlowEngine("000660", interval=0.05)

    class FakeClient:
        async def price(self, code):
            return {"price": 2244000, "sign": "up", "change": 58000,
                    "rate": 2.65, "acml_vol": 3317403,
                    "acml_value": 7371903475500}

        async def program_trend(self, code):
            return [{"t": "13:00:00", "net_qty": -550000, "net_value": -1}]

    async def go():
        stop = asyncio.Event()
        task = asyncio.get_event_loop().create_task(
            eng._ws_fallback(FakeClient(), stop))
        await asyncio.sleep(0.2)
        stop.set()
        await asyncio.wait_for(task, 5)

    _run(go())
    snap = eng.state.snapshot()
    assert snap["market"]["price"] == 2244000          # 시세 채워짐
    assert snap["program"]["net_qty"] == -550000       # 프로그램도 백필
    assert snap["tape"] == []                          # 테이프는 오염 안 됨


def test_run_live_stops_siblings_when_one_branch_dies(monkeypatch):
    """gather 한 갈래가 죽으면 나머지 둘도 세운다.

    asyncio.gather는 형제 태스크를 죽이지 않는다 — 세우지 않으면 다음 구독의
    _ensure_running이 self._stop을 새 Event로 갈아치워, 고아 폴러가 재기동 전까지
    영원히 산다. /live를 다시 열 때마다 한 벌씩 쌓여 KIS 호출이 2배·3배가 된다
    (감사 2026-08-12 인프로세스 재현). 도달 경로는 _ws_link의 _ws_attach 실패다.
    """
    eng = FlowEngine("000660", interval=0.05)
    ticks = {"n": 0}

    class FakeClient:
        async def token(self):
            return "T"

    async def boom(client, stop):
        raise RuntimeError("구독 거부 — _ws_attach 실패")

    async def poller(client, stop):
        while not stop.is_set():
            ticks["n"] += 1
            await asyncio.sleep(0.01)

    eng._client = FakeClient()
    monkeypatch.setattr(eng, "_ws_link", boom)
    monkeypatch.setattr(eng, "_poll_rest", poller)
    monkeypatch.setattr(eng, "_ws_fallback", poller)

    async def go():
        stop = asyncio.Event()
        try:
            await eng._run_live(stop)
        except RuntimeError:
            pass
        n = ticks["n"]
        assert stop.is_set(), "형제 갈래를 세울 stop이 서지 않았다"
        await asyncio.sleep(0.05)
        assert ticks["n"] == n, "러너가 죽었는데 폴러가 계속 돈다(고아 폴러)"

    _run(go())


def test_registry_returns_same_engine():
    a = FlowEngine.get("000660")
    b = FlowEngine.get("000660")
    assert a is b
    assert FlowEngine.get("005930") is not a


async def _until(pred, timeout=3.0):
    """pred()가 참이 될 때까지 짧게 폴링 — 재시도 타이밍에 sleep을 못박지 않는다."""
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


def test_auth_failure_retries_then_recovers_live(monkeypatch):
    """인증 실패는 '영구 데모 강등'이 아니라 주기적 재시도여야 한다.

    2026-08-25 08:56 실사고: 토큰 24h 만료 순간의 403 한 번으로 FlowEngine이
    데모로 내려앉았고, 구독자가 붙어 있어 _delayed_stop도 안 걸려 마스터가
    장 시작부터 오후까지 시뮬레이션 난수를 실시간 시세로 봤다."""
    from backend.config import settings
    from backend.flow import engine as engmod
    monkeypatch.setattr(settings, "kis_app_key", "k")
    monkeypatch.setattr(settings, "kis_app_secret", "s")
    monkeypatch.setattr(engmod, "_AUTH_RETRY_SEC", 0.05)

    calls = {"n": 0}

    class FakeClient:
        async def token(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("403 EGW00133 1분당 1회")
            return "T"

    eng = FlowEngine("000660", interval=0.05)
    eng._client = FakeClient()

    async def idle(client, stop):
        await stop.wait()

    for name in ("_poll_rest", "_ws_link", "_ws_fallback"):
        monkeypatch.setattr(eng, name, idle)

    async def go():
        stop = asyncio.Event()
        before = set(asyncio.all_tasks())
        task = asyncio.get_event_loop().create_task(eng._run_live(stop))
        note = lambda: eng.state.snapshot()["status"]["note"]           # noqa: E731
        assert await _until(lambda: "재시도" in note()), \
            "재시도 중임이 노트에 안 보인다: %r" % note()
        assert eng.state.mode == "demo", "실패 직후 데모가 아니다"
        assert eng.state.snapshot()["tape"], "재시도 대기 중 화면이 죽었다(데모 미공급)"
        assert await _until(lambda: eng.state.mode == "live"), "재인증 후 라이브 복귀 실패"
        assert note() == "", "복구 후 노트가 안 비었다: %r" % note()
        snap = eng.state.snapshot()
        assert not snap["tape"] and not snap["daily"], \
            "복구 후에도 데모 시드가 라이브 배지 아래 남았다"
        stop.set()
        await asyncio.wait_for(task, 1.0)
        leftover = [t for t in asyncio.all_tasks()
                    if t not in before and not t.done()]
        assert not leftover, "정지 후 데모 태스크가 남았다: %r" % leftover

    _run(go())


def test_no_retry_without_keys(monkeypatch):
    """키가 아예 없으면 재시도하지 않는다 — 하네스(harness/core/server.py)가
    키를 비워 'KIS 미접촉'을 보장하는 경로다. 여기서 재시도하면 그 보장이 깨진다."""
    from backend.config import settings
    from backend.flow import engine as engmod
    monkeypatch.setattr(settings, "kis_app_key", "")
    monkeypatch.setattr(settings, "kis_app_secret", "")
    monkeypatch.setattr(engmod, "_AUTH_RETRY_SEC", 0.02)

    calls = {"n": 0}

    class FakeClient:
        async def token(self):
            calls["n"] += 1
            raise RuntimeError("KIS 키 없음 — 호출 차단")

    eng = FlowEngine("000660", interval=0.05)
    eng._client = FakeClient()

    async def go():
        stop = asyncio.Event()
        task = asyncio.get_event_loop().create_task(eng._run_live(stop))
        await asyncio.sleep(0.3)            # 재시도 간격의 10배 이상
        assert calls["n"] == 1, "키가 없는데 발급을 다시 시도했다(%d회)" % calls["n"]
        assert eng.state.mode == "demo"
        stop.set()
        await asyncio.wait_for(task, 1.0)

    _run(go())


# ── 매수 유의사항(토스) 폴링 ──────────────────────────────────────────────

class _MinimalClient:
    """_poll_rest가 부르는 KIS 메서드만 가진 최소 클라이언트(전부 빈 결과)."""

    async def program_trend(self, code):
        return []

    async def estimate(self, code):
        return []

    async def daily_investor(self, code):
        return []

    async def investor_detail(self, code):
        return {}

    async def _get(self, *a, **k):      # 부가 패널(거래원·거래소별 등)이 직접 쓴다
        return {}


async def _drive_poll(eng, client, seconds=0.3):
    stop = asyncio.Event()
    task = asyncio.get_event_loop().create_task(eng._poll_rest(client, stop))
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.wait_for(task, 5)


def test_poll_rest_fills_buy_warnings_from_toss(monkeypatch):
    _no_shortbal(monkeypatch)
    from backend.flow import toss

    class FakeToss:
        async def warnings(self, code):
            return [{"type": "VI_STATIC", "label": "VI 발동(정적)",
                     "tone": "info", "exchange": "KRX",
                     "start": None, "end": None}]
    monkeypatch.setattr(toss, "get_client", lambda: FakeToss())
    eng = FlowEngine("000660", interval=0.1)
    _run(_drive_poll(eng, _MinimalClient()))
    assert [w["label"] for w in eng.state.snapshot()["warnings"]] \
        == ["VI 발동(정적)"]


def test_poll_rest_without_a_toss_key_leaves_warnings_empty(monkeypatch):
    """키가 없으면 조용히 빈 채로 둔다 — 나머지 패널은 그대로 돈다."""
    _no_shortbal(monkeypatch)
    from backend.flow import toss
    monkeypatch.setattr(toss, "get_client", lambda: None)
    eng = FlowEngine("000660", interval=0.1)
    _run(_drive_poll(eng, _MinimalClient()))
    assert eng.state.snapshot()["warnings"] == []


def test_poll_rest_survives_a_toss_failure(monkeypatch):
    """토스가 죽어도 폴링 루프는 계속 돈다(다른 부가 패널과 같은 격리)."""
    _no_shortbal(monkeypatch)
    from backend.flow import toss

    class BoomToss:
        async def warnings(self, code):
            raise RuntimeError("토스 403 — 허용 IP 미등록")
    monkeypatch.setattr(toss, "get_client", lambda: BoomToss())
    eng = FlowEngine("000660", interval=0.1)
    _run(_drive_poll(eng, _MinimalClient()))     # 예외가 새면 여기서 터진다
    assert eng.state.snapshot()["warnings"] == []
