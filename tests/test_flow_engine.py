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
    """_poll_rest 테스트 공통 — 대차잔고 원격 조회 차단(외부 네트워크 금지)."""
    from backend.flow import shortbal

    async def fake(code, cache_dir, days=20):
        return {"rows": [{"date": "2026-07-10", "qty": 14140221,
                          "value": 30825681780000, "chg": -280048,
                          "src": "kofia"}],
                "asof": "2026-07-10", "source": "kofia", "updated": "t"}
    monkeypatch.setattr(shortbal, "get_history", fake)


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


def test_registry_returns_same_engine():
    a = FlowEngine.get("000660")
    b = FlowEngine.get("000660")
    assert a is b
    assert FlowEngine.get("005930") is not a
