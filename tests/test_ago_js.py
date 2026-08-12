"""상대시간 포맷터 실행 테스트 — 분기가 있는 유일한 신규 로직이라 node로 돌린다."""
import shutil
import subprocess

import pytest

from backend.report.theme import AGO_JS

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node 미설치 — JS 실행 테스트 생략")

CASES = [
    (0, "방금"),
    (-30 * 1000, "30초 전"),
    (-90 * 1000, "1분 전"),
    (-59 * 60 * 1000, "59분 전"),
    (-3 * 60 * 60 * 1000, "13:00"),      # NOW가 16:00 KST 고정이라 3시간 전 = 13:00
    (+2 * 60 * 60 * 1000, "2시간 뒤"),
    (+26 * 60 * 60 * 1000, "내일"),
    (+3 * 24 * 60 * 60 * 1000, "3일 뒤"),
]


@needs_node
@pytest.mark.parametrize("delta,expected", CASES)
def test_ago_formats(tmp_path, delta, expected):
    # 2026-08-12 16:00 KST(= 07:00 UTC). 고정 NOW로 테스트가 시계에 안 흔들리게 한다.
    # 실측 확인: TZ=Asia/Seoul 에서 이 epoch는 16:00 정각이다(2026-08-12).
    now = 1786518000000
    js = tmp_path / "ago.js"
    js.write_text(AGO_JS + "\nconsole.log(ago(%d, %d));" % (now + delta, now),
                  encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected
