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


def test_registry_returns_same_engine():
    a = FlowEngine.get("000660")
    b = FlowEngine.get("000660")
    assert a is b
    assert FlowEngine.get("005930") is not a
