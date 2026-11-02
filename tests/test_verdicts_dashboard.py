"""판정 장부 — 홈 렌더(build_dashboard) 쪽 signal 기록·scorecard 베이크. KIS·네트워크 미접촉."""
from __future__ import annotations

import pandas as pd
import pytest

from backend.config import settings
from backend.flow import verdicts


def _df(closes, start="2026-10-01"):
    idx = pd.date_range(start, periods=len(closes), freq="D")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": [1] * len(closes)}, index=idx)


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    from backend import cli
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "flow_mode", "")
    monkeypatch.setattr(cli, "_kr_market_open", lambda: True)
    monkeypatch.setattr(cli, "_live_prices", lambda codes: {c: {"close": 999, "change": 1.0} for c in codes})
    monkeypatch.setattr(cli, "us_market_open", lambda: False)
    monkeypatch.setattr(cli, "_collect_issues", lambda codes, nm=None: {})
    monkeypatch.setattr(cli, "get_universe", lambda d: [])
    return cli, tmp_path


def test_build_dashboard_records_signal_with_live_px(cli_env):
    cli, tmp = cli_env
    src = lambda code, s, e: _df([100.0] * 80)   # noqa: E731
    cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp), source=src,
                        with_news=False, ledger=True)
    d = verdicts.load()
    key = "signal:005930:2026-12-19"                 # 마지막 봉 날짜(80일째)
    assert list(d) == [key]
    from backend.analysis.indicators import add_indicators
    from backend.signals.rules import evaluate_with_gate
    sig = evaluate_with_gate(add_indicators(_df([100.0] * 80)), "005930")   # 엔진이 내는 그대로
    assert d[key]["px"] == 999 and d[key]["dir"] == sig.action and d[key]["advice"] is sig.advice


def test_build_dashboard_same_bar_twice_is_one_key(cli_env):
    cli, tmp = cli_env
    src = lambda code, s, e: _df([100.0] * 80)   # noqa: E731
    for _ in range(2):
        cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp), source=src,
                            with_news=False, ledger=True)
    assert len(verdicts.load()) == 1


def test_build_dashboard_default_no_ledger(cli_env):
    cli, tmp = cli_env
    cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp),
                        source=lambda c, s, e: _df([100.0] * 80), with_news=False)
    assert not verdicts._path().exists()


def test_build_dashboard_empty_frame_records_nothing_and_renders(cli_env, monkeypatch):
    """빈 DataFrame(조회 실패·상장 직후)이면 장부에 쓰지 않는다. 규칙 엔진(rules.evaluate)은
    빈 프레임에서 원래 IndexError가 나는 기존 동작이라 여기선 스텁한다(2026-11-02 실측)."""
    from backend.signals.rules import Signal
    cli, tmp = cli_env
    monkeypatch.setattr(cli, "evaluate_with_gate", lambda df, code: Signal(code, "hold", 1))
    html = cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp),
                               source=lambda c, s, e: _df([]), with_news=False, ledger=True)
    assert "관심종목 분석" in html and not verdicts._path().exists()


def test_build_dashboard_bakes_scorecard_for_master_only(cli_env):
    cli, tmp = cli_env
    # 11-05는 80봉(10-01~12-19) 중 60거래일 창(10-21~) 안이다. 11-05 종가 100 > px 90 → hit
    verdicts.record("outlook", "005930", "2026-11-05", "up", 90)
    src = lambda c, s, e: _df([100.0] * 80)   # noqa: E731
    html = cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp),
                               source=src, with_news=False, ledger=True)
    assert '"scorecard"' in html and '"hit": 1' in html
    other = cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp),
                                source=src, with_news=False)        # 비마스터 홈
    assert '"scorecard": null' in other                              # 마스터 장부 노출 금지


def test_scorecard_none_without_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    assert verdicts.scorecard({"005930": _df([1.0, 2.0])}) is None


def test_build_dashboard_records_kr_only(cli_env):
    """미국 티커의 판정은 장부에 넣지 않는다 — 헤더 '매매판정'은 국내 적중률이고, 미국 봉 날짜가
    60거래일 창 계산에 섞이면 창이 짧아진다(리뷰 2026-11-02)."""
    cli, tmp = cli_env
    src = lambda code, s, e: _df([100.0] * 80)   # noqa: E731
    cli.build_dashboard([{"code": "SKHY", "market": "US"}, {"code": "005930", "market": "KR"}],
                        str(tmp), source=src, with_news=False, ledger=True)
    assert list(verdicts.load()) == ["signal:005930:2026-12-19"]


def test_build_dashboard_off_session_px_from_kis_not_universe_cache(cli_env, monkeypatch):
    """장외엔 pm이 universe 캐시(StockListing, 최대 12h 묵은 전일 종가)라 px로 쓰면 하루 어긋난다 →
    ledger 경로는 장외에도 KIS 현재가(=그날 종가)를 쓴다(리뷰 2026-11-02)."""
    cli, tmp = cli_env
    monkeypatch.setattr(cli, "_kr_market_open", lambda: False)
    monkeypatch.setattr(cli, "get_universe", lambda d: [{"code": "005930", "name": "삼성전자",
                                                        "close": 55555, "change": 0.1}])
    src = lambda code, s, e: _df([100.0] * 80)   # noqa: E731
    cli.build_dashboard([{"code": "005930", "market": "KR"}], str(tmp), source=src,
                        with_news=False, ledger=True)
    assert verdicts.load()["signal:005930:2026-12-19"]["px"] == 999      # _live_prices 값
