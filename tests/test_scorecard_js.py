"""홈 적중률 문구(scText) 실행 테스트 — 분기(표본 부족·톤 임계·묶음 생략)가 있어 node로 돌린다."""
import json
import shutil
import subprocess

import pytest

from backend.report.dashboard import SCORECARD_JS

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node 미설치")


def _b(**kw):
    return dict({"n": 0, "hit": 0, "skip": 0, "pending": 0}, **kw)


def _run(tmp_path, sc):
    js = tmp_path / "sc.js"
    js.write_text(SCORECARD_JS + "\nconsole.log(JSON.stringify(scText(%s)));" % json.dumps(sc),
                  encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
def test_sctext_full_sample(tmp_path):
    out = _run(tmp_path, {"outlook": _b(n=30, hit=17, skip=12), "signal": _b(n=5, hit=3),
                          "by_code": {"005930": {"outlook": _b(n=9, hit=6, pending=1), "signal": _b()}}})
    assert out["head"] == "내일예상 적중 17/30 · 매매판정 3/5 (10일) · 중립 12"
    assert out["tone"] == "good"                       # 17/30 = 56.7% ≥ 55%
    assert out["cards"] == {"005930": "예상 적중 6/9 · 대기 1"}


@needs_node
@pytest.mark.parametrize("hit,n,tone", [(13, 30, "bad"), (15, 30, "flat"), (17, 30, "good")])
def test_sctext_tone_thresholds(tmp_path, hit, n, tone):
    out = _run(tmp_path, {"outlook": _b(n=n, hit=hit), "signal": _b(), "by_code": {}})
    assert out["tone"] == tone


@needs_node
def test_sctext_small_sample_and_empty_parts(tmp_path):
    out = _run(tmp_path, {"outlook": _b(n=4, hit=3), "signal": _b(),
                          "by_code": {"005930": {"outlook": _b(), "signal": _b()}}})
    assert out["head"] == "내일예상 표본 부족 (4/10)" and out["tone"] == "flat"
    assert out["cards"] == {"005930": ""}             # n+pending == 0 → 비움


@needs_node
def test_sctext_null(tmp_path):
    assert _run(tmp_path, None)["head"] is None
