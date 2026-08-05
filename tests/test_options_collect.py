"""옵션 배치 수집 — 유량 상한·부분 실패 집계. KIS 미접촉(가짜 클라이언트).

유량이 이 태스크의 전부다. 개인 계정 REST 한도는 초당 10건이고 /live 수급이
이미 2~4건/초를 쓴다 — 옵션 배치가 남은 몫을 다 먹으면 기존 화면이 EGW00201로
깨진다(7.3건/초에서 780건 중 6건 실패, 2026-08-05 실측).
"""
import asyncio
import time

import pytest


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """재시도 백오프를 0으로 — 테스트가 실제로 초를 세며 자지 않게 한다."""
    from backend.api import marketdata as md
    monkeypatch.setattr(md, "_OPT_BACKOFF", 0.0)


class _FakeOptClient:
    """option_quote 호출 시각을 기록하는 가짜 클라이언트. fail_codes는 항상 실패."""

    def __init__(self, fail_codes=(), latency=0.0):
        self.at, self.fail_codes, self.latency = [], set(fail_codes), latency

    async def option_quote(self, code):
        self.at.append(time.monotonic())
        if self.latency:
            await asyncio.sleep(self.latency)
        if code in self.fail_codes:
            return None
        n = int(code[-3:])
        return {"strike": float(n), "price": 1.0, "vol": n, "oi": n * 10,
                "oi_chg": n - 5, "iv": 80.0, "delta": 0.5, "remain_days": 9}


def _rows(n, side="call"):
    """마스터 행 n개. 행사가는 1.0부터 — 0.0은 '값 없음'과 구분이 안 된다."""
    return [{"code": "B0160%03d" % i, "side": side, "strike": float(i)}
            for i in range(1, n + 1)]


def test_collect_chain_attaches_code_and_side():
    from backend.api import marketdata as md
    c = _FakeOptClient()
    rows, failed = asyncio.run(md._collect_chain(c, _rows(3), rate=1000.0, conc=3))
    assert failed == 0 and len(rows) == 3
    assert rows[0]["code"] == "B0160001" and rows[0]["side"] == "call"


def test_collect_chain_never_exceeds_the_rate_cap():
    """40건을 초당 20건 상한으로 — 최소 (40-1)/20초는 걸려야 한다.
    세마포어만으론 응답이 빠를 때 발사량을 못 막는다(페이싱이 따로 필요한 이유)."""
    from backend.api import marketdata as md
    c = _FakeOptClient()
    t0 = time.monotonic()
    rows, failed = asyncio.run(md._collect_chain(c, _rows(40), rate=20.0, conc=3))
    elapsed = time.monotonic() - t0
    assert len(rows) == 40 and failed == 0
    assert elapsed >= 39 / 20.0 * 0.9          # 타이머 오차 10% 여유
    gaps = [b - a for a, b in zip(c.at, c.at[1:])]
    assert max(gaps) < 1.0                      # 상한을 지키되 쓸데없이 느리지도 않다


def test_collect_chain_counts_failures_without_dropping_the_batch():
    from backend.api import marketdata as md
    c = _FakeOptClient(fail_codes=("B0160002", "B0160004"))
    rows, failed = asyncio.run(md._collect_chain(c, _rows(5), rate=1000.0, conc=3))
    assert failed == 2 and len(rows) == 3       # 실패 건만 빠지고 나머지는 산다
    assert {r["code"] for r in rows} == {"B0160001", "B0160003", "B0160005"}


def test_collect_chain_retries_before_giving_up():
    """EGW00201(호출량 초과)은 정상 경로다 — 지수 백오프로 재시도한다."""
    from backend.api import marketdata as md

    class _FlakyOnce(_FakeOptClient):
        def __init__(self):
            super().__init__()
            self.seen = {}

        async def option_quote(self, code):
            self.seen[code] = self.seen.get(code, 0) + 1
            if self.seen[code] == 1:
                return None                     # 첫 시도만 실패
            return await super().option_quote(code)

    c = _FlakyOnce()
    rows, failed = asyncio.run(md._collect_chain(c, _rows(2), rate=1000.0, conc=2))
    assert failed == 0 and len(rows) == 2
    assert all(v == 2 for v in c.seen.values())


def test_collect_chain_survives_client_exception():
    from backend.api import marketdata as md

    class _Boom:
        async def option_quote(self, code):
            raise RuntimeError("연결 끊김")

    rows, failed = asyncio.run(md._collect_chain(_Boom(), _rows(2), rate=1000.0, conc=2))
    assert rows == [] and failed == 2


def test_collect_chain_falls_back_to_master_strike_when_response_lacks_it():
    """응답에 행사가가 비면 마스터 값으로 메운다 — 행사가 없는 행은 histogram이
    걸러내 차트에서 통째로 사라진다. 알고 있는 값이 있는데 버릴 이유가 없다."""
    from backend.api import marketdata as md

    class _NoStrike(_FakeOptClient):
        async def option_quote(self, code):
            q = await super().option_quote(code)
            q["strike"] = 0.0                   # 응답에 행사가가 비는 경우
            return q

    rows, _ = asyncio.run(md._collect_chain(_NoStrike(), _rows(1), rate=1000.0, conc=1))
    assert rows[0]["strike"] == 1.0             # 마스터의 행사가로 메워졌다


def test_option_quote_uses_correct_tr_and_params():
    """KisClient.option_quote — TR·경로·파라미터를 고정한다(회귀 방지)."""
    from backend.flow.kis import KisClient

    seen = {}

    class _C(KisClient):
        async def _get(self, path, tr_id, params, retries=2):
            seen.update({"path": path, "tr": tr_id, "params": params})
            return {"rt_cd": "0", "output1": {"acpr": "1000.0", "acml_vol": "5"}}

    c = _C("k", "s", "/tmp")
    q = asyncio.run(c.option_quote("B01608625"))
    assert seen["tr"] == "FHMIF10000000"
    assert seen["path"].endswith("/domestic-futureoption/v1/quotations/inquire-price")
    assert seen["params"] == {"FID_COND_MRKT_DIV_CODE": "O",
                              "FID_INPUT_ISCD": "B01608625"}
    assert q["strike"] == 1000.0 and q["vol"] == 5


# ── 회차 수집 · TTL · 백그라운드 갱신 · 디스크 캐시 ────────────────────────
import datetime as dt  # noqa: E402

from backend.flow.kst import KST  # noqa: E402

_LIVE = dt.datetime(2026, 8, 5, 11, 0, tzinfo=KST)       # 수요일 장중
_CLOSED = dt.datetime(2026, 8, 5, 16, 30, tzinfo=KST)    # 마감 후


def _reset_opt(md):
    md._opt_cache.update({"ts": 0.0, "data": None, "busy": False})


@pytest.fixture(autouse=True)
def _isolate_opt_cache(tmp_path, monkeypatch):
    """디스크 캐시를 격리하고, 페이싱을 끄고, 오늘 날짜를 고정한다.

    날짜 고정이 중요하다 — front_month는 '만기일이 오늘 이후'로 고르므로,
    이걸 안 묶으면 2026-08-13이 지난 날 이 테스트가 갑자기 깨진다.
    (유량 자체는 test_collect_chain_never_exceeds_the_rate_cap이 rate를 직접 넘겨 잰다.)"""
    from backend.api import marketdata as md
    from backend.config import settings
    from backend.flow import kst
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(md, "_OPT_RATE", 1000.0)
    monkeypatch.setattr(kst, "today", lambda: dt.date(2026, 8, 5))
    _reset_opt(md)
    yield
    _reset_opt(md)


class _FakeBoard(_FakeOptClient):
    """마스터 없이 get_options를 돌리기 위한 클라이언트 — index()까지 흉내낸다."""

    async def index(self, iscd="0001"):
        assert iscd == "2001"        # 코스피200 — 계획서 §변경 ②
        return {"price": 1039.35, "rate": 0.5}


def _install_master(monkeypatch, md, rows):
    from backend.flow import optmaster as om
    monkeypatch.setattr(om, "load", lambda cache_dir, force=False, fetch=None: rows)


def _master_rows():
    return [{"code": "B0160%03d" % i, "side": "call", "expiry": "202608",
             "strike": 1000.0 + i} for i in range(1, 4)] + \
           [{"code": "B0165%03d" % i, "side": "put", "expiry": "202608",
             "strike": 1000.0 + i} for i in range(1, 4)]


def test_get_options_collects_and_shapes_payload(monkeypatch):
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    d = asyncio.run(md._collect_options(_FakeBoard()))
    assert d["expiry"] == "202608" and d["label"] == "8월물"
    assert d["spot"] == 1039.35 and d["remain_days"] == 9
    assert d["cols"] == ["strike", "oi", "oi_chg"]
    assert len(d["calls"]) == 3 and len(d["calls"][0]) == 3
    assert d["failed"] == 0
    assert "call_wall" not in d["summary"]      # 정직성 규칙


def test_get_options_returns_none_without_master(monkeypatch):
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, [])
    assert asyncio.run(md._collect_options(_FakeBoard())) is None


def test_get_options_serves_cache_immediately_and_refreshes_in_background(monkeypatch):
    """한 회차가 3.5분이라 요청을 붙잡으면 안 된다 — 즉시 직전값 + collecting:True."""
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    md._opt_cache["data"] = {"expiry": "202607", "calls": [], "puts": [], "summary": {}}
    md._opt_cache["ts"] = 0.0                   # 만료

    async def _run():
        d = await md.get_options(client=_FakeBoard(), now=_LIVE)
        assert d["expiry"] == "202607"          # 직전값을 곧바로 준다
        assert d["collecting"] is True and d["stale"] is True
        for _ in range(200):                    # 백그라운드가 끝날 때까지 양보
            if not md._opt_cache["busy"]:
                break
            await asyncio.sleep(0.01)
        d2 = await md.get_options(client=_FakeBoard(), now=_LIVE)
        assert d2["expiry"] == "202608" and d2["collecting"] is False
        assert d2["stale"] is False

    asyncio.run(_run())


def test_get_options_does_not_refresh_outside_session(monkeypatch):
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    md._opt_cache["data"] = {"expiry": "202608", "calls": [], "puts": [], "summary": {}}
    md._opt_cache["ts"] = 0.0
    c = _FakeBoard()
    d = asyncio.run(md.get_options(client=c, now=_CLOSED))
    assert d["collecting"] is False and c.at == []    # 마감 후엔 한 건도 안 부른다
    assert d["stale"] is False                        # 마감은 '지연'이 아니다


def test_get_options_returns_empty_when_cold_and_collecting(monkeypatch):
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    md._opt_cache["busy"] = True                      # 이미 첫 수집 중
    assert asyncio.run(md.get_options(client=_FakeBoard(), now=_LIVE)) == {}


def test_get_options_none_without_key(monkeypatch):
    from backend.api import marketdata as md
    monkeypatch.setattr(md, "_client", lambda: None)
    assert asyncio.run(md.get_options(now=_LIVE)) is None


def test_get_options_survives_disk_and_keeps_last_board(monkeypatch, tmp_path):
    """서버를 재기동해도 직전 보드를 보여준다 — 장외엔 새로 못 받는다."""
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    asyncio.run(md._opt_refresh(_FakeBoard()))
    saved = md._opt_cache["data"]
    assert saved is not None
    _reset_opt(md)                                     # 재기동 흉내
    d = asyncio.run(md.get_options(client=_FakeBoard(), now=_CLOSED))
    assert d["expiry"] == saved["expiry"] and len(d["calls"]) == len(saved["calls"])


def test_get_options_failure_keeps_previous_board(monkeypatch):
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    md._opt_cache["data"] = {"expiry": "202608", "calls": [], "puts": [], "summary": {}}
    md._opt_cache["ts"] = time.time()

    class _Boom(_FakeBoard):
        async def option_quote(self, code):
            raise RuntimeError("KIS 죽음")      # 전 종목 실패 → 회차가 통째로 무산

    asyncio.run(md._opt_refresh(_Boom()))
    assert md._opt_cache["data"]["expiry"] == "202608"   # 직전값 유지
    assert md._opt_cache["busy"] is False                # 실패해도 잠금은 풀린다
