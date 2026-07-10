"""FlowEngine(데모 모드) 테스트 — 키 없이 스냅샷 스트림이 흘러야 한다."""
import asyncio

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
    # 데모 소스가 굴러가면 시장가·일별 확정이 채워진다
    assert s2["daily"], "데모 일별 수급이 비어있음"


def test_poll_rest_daily_survives_estimate_failure():
    # 실운영에서 관찰(2026-07-10): 추정 TR이 간헐 500 → 일별 조회까지 죽으면 안 된다.
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
    assert "재시도" in snap["status"]["note"]  # 실패가 화면에 표시됨


def test_registry_returns_same_engine():
    a = FlowEngine.get("000660")
    b = FlowEngine.get("000660")
    assert a is b
    assert FlowEngine.get("005930") is not a
