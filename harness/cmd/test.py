"""test — pytest 전체(48파일) + node 스모크를 한 커맨드로. node는 pytest 내부에서
subprocess로 실행되며, 미설치 시 해당 테스트는 skip된다."""
import shutil
import subprocess
import sys
from typing import List


def _pytest_argv(rest: List[str]) -> List[str]:
    return [sys.executable, "-m", "pytest"] + (rest or ["-q"])


def main(argv=None) -> int:
    rest = list(argv or [])
    if shutil.which("node") is None:
        print("※ node 미설치 — JS 렌더 스모크는 skip됩니다(설치 시 자동 포함).")
    else:
        print("※ node 감지 — JS 렌더 스모크 포함.")
    return subprocess.call(_pytest_argv(rest))
