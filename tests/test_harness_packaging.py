import subprocess
import sys


def test_harness_not_in_shipped_packages():
    # setuptools가 잡는 패키지에 harness가 없어야 한다(배포본 미포함)
    out = subprocess.run(
        [sys.executable, "-c",
         "from setuptools import find_packages;"
         "print(find_packages(include=['backend*']))"],
        capture_output=True, text=True).stdout
    assert "harness" not in out
    assert "backend" in out
