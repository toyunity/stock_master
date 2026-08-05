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


# ── 회차 수집(배치) · 서버는 디스크만 읽음 ────────────────────────────────
import datetime as dt  # noqa: E402

from backend.flow.kst import KST  # noqa: E402

_LIVE = dt.datetime(2026, 8, 5, 11, 0, tzinfo=KST)       # 수요일 장중
_CLOSED = dt.datetime(2026, 8, 5, 16, 30, tzinfo=KST)    # 마감 후


def _reset_opt(md):
    md._opt_mem.update({"mtime": 0.0, "data": None})


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
    monkeypatch.setattr(settings, "options_enabled", True)   # 켠 상태가 이 파일의 기본
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




def test_get_options_serves_the_board_without_a_kis_key(monkeypatch):
    """서버는 KIS 키가 없어도 보드를 보여준다 — 이제 디스크만 읽기 때문이다.

    수집이 웹서버 안에 있던 때는 키가 없으면 아무것도 못 냈다. 배치로 떼어낸 뒤로는
    수집(키 필요)과 표시(키 불필요)가 갈렸다."""
    from backend.api import marketdata as md
    from backend.config import settings
    _install_master(monkeypatch, md, _master_rows())
    asyncio.run(md.collect_options(client=_FakeBoard()))
    _reset_opt(md)
    monkeypatch.setattr(settings, "kis_app_key", None)
    monkeypatch.setattr(md, "_client", lambda: None)
    assert asyncio.run(md.get_options(now=_LIVE))["expiry"] == "202608"


def test_collect_options_writes_the_board_to_disk(monkeypatch):
    """배치 진입점 — 수집 결과가 파일로 남아야 서버가 읽는다."""
    import glob
    import os
    from backend.api import marketdata as md
    from backend.config import settings
    _install_master(monkeypatch, md, _master_rows())
    d = asyncio.run(md.collect_options(client=_FakeBoard()))
    assert d["expiry"] == "202608"
    files = glob.glob(os.path.join(settings.cache_dir, "options_*.json"))
    assert len(files) == 1 and os.path.basename(files[0]) == "options_202608.json"


def test_get_options_never_calls_kis(monkeypatch):
    """**서버는 절대 수집하지 않는다.** 이 파일의 핵심 회귀다.

    수집이 웹 요청 경로에 다시 스며들면 아침 첫 방문자가 2.6분을 기다리고,
    서버를 재기동할 때마다 780건이 다시 나간다."""
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    asyncio.run(md.collect_options(client=_FakeBoard()))     # 배치가 먼저 채워둔다
    _reset_opt(md)
    c = _FakeBoard()
    d = asyncio.run(md.get_options(client=c, now=_LIVE))
    assert d["expiry"] == "202608"
    assert c.at == []                        # KIS를 한 번도 안 불렀다


def test_get_options_returns_empty_without_a_collected_file(monkeypatch):
    """배치가 아직 안 돌았으면 {} — 프론트가 섹션을 통째로 숨긴다(빈 칸 금지)."""
    from backend.api import marketdata as md
    assert asyncio.run(md.get_options(now=_LIVE)) == {}


def test_get_options_marks_stale_when_the_batch_is_late_intraday(monkeypatch):
    """장중인데 배치가 한 시간 넘게 안 돌았으면 '지연'. 마감 후엔 안 붙인다."""
    import time as _t
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    asyncio.run(md.collect_options(client=_FakeBoard()))
    _reset_opt(md)

    # 파일의 수집 시각을 2시간 전으로 조작
    import json
    import os
    from backend.config import settings
    path = os.path.join(settings.cache_dir, "options_202608.json")
    with open(path) as f:
        raw = json.load(f)
    raw["ts"] = _t.time() - 7200
    with open(path, "w") as f:
        json.dump(raw, f)

    assert asyncio.run(md.get_options(now=_LIVE))["stale"] is True
    _reset_opt(md)
    assert asyncio.run(md.get_options(now=_CLOSED))["stale"] is False


def test_get_options_off_hides_even_a_collected_board(monkeypatch):
    """꺼져 있으면 디스크에 보드가 있어도 안 내보낸다 — 화면에서 통째로 사라진다."""
    from backend.api import marketdata as md
    from backend.config import settings
    _install_master(monkeypatch, md, _master_rows())
    asyncio.run(md.collect_options(client=_FakeBoard()))
    _reset_opt(md)
    monkeypatch.setattr(settings, "options_enabled", False)
    assert asyncio.run(md.get_options(now=_LIVE)) is None


def test_get_options_rereads_only_when_the_file_changes(monkeypatch):
    """14KB를 매 요청 재파싱하지 않는다 — mtime이 바뀔 때만 다시 읽는다."""
    from backend.api import marketdata as md
    _install_master(monkeypatch, md, _master_rows())
    asyncio.run(md.collect_options(client=_FakeBoard()))
    _reset_opt(md)
    asyncio.run(md.get_options(now=_LIVE))
    first = md._opt_mem["data"]
    asyncio.run(md.get_options(now=_LIVE))
    assert md._opt_mem["data"] is first      # 같은 객체 = 재파싱 안 함
