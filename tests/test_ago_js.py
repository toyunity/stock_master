"""상대시간 포맷터 실행 테스트 — 분기가 있는 유일한 신규 로직이라 node로 돌린다."""
import os
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
    (-5000, "5초 전"),           # 경계: 5초는 '방금'이 아니다
    (-60000, "1분 전"),          # 경계: 60초는 '초 전'이 아니다
    (-3600000, "15:00"),         # 경계: 60분은 '분 전'이 아니라 시각 표기
    (+86400000, "내일"),          # 경계: 정확히 24시간 뒤 → 2026-08-13 16:00
    (+36 * 3600 * 1000, "2일 뒤"),  # 착지 2026-08-14 04:00 → 달력 2일
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
    r = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=15,
                       env=dict(os.environ, TZ="Asia/Seoul"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected


@needs_node
@pytest.mark.parametrize("now,delta_h,expected", [
    (1786461000000, 36, "내일"),    # now=2026-08-12 00:10 → 착지 08-13 12:10 = 달력상 내일
    (1786543200000, 30, "2일 뒤"),  # now=2026-08-12 23:00 → 착지 08-14 05:00 = 달력상 모레
])
def test_ago_uses_calendar_days_not_elapsed_hours(tmp_path, now, delta_h, expected):
    """'내일'은 달력 날짜지 경과 24시간이 아니다.
    경과시간으로 세면 지금이 몇 시냐에 따라 내일이 '2일 뒤'가 되고 모레가 '내일'이 된다."""
    js = tmp_path / "ago.js"
    js.write_text(AGO_JS + "\nconsole.log(ago(%d, %d));" % (now + delta_h * 3600 * 1000, now),
                  encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=15,
                       env=dict(os.environ, TZ="Asia/Seoul"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected
