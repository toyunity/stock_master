"""데모서버 수명주기 — 빈 포트에 SM_FLOW_MODE=demo로 spawn, PID로만 종료.

마스터 실서버(8000) 보호가 최우선: 프로세스명 기반 강제종료나 포트 문자열
매칭을 절대 쓰지 않고, 자기가 만든 Popen 객체의 PID만 terminate 한다."""
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from typing import Iterator, Optional

import httpx

from harness.core import ports


class ServerHandle:
    def __init__(self, port: int, pid: int):
        self.port = port
        self.pid = pid
        self.base = "http://127.0.0.1:%d" % port


def _child_env() -> dict:
    # 부모 env를 복사하되 데모·인증off를 강제(부모가 live/true여도 덮는다)
    env = dict(os.environ)
    env["SM_FLOW_MODE"] = "demo"
    env["SM_AUTH_ENABLED"] = "false"
    # KIS 미접촉 보장: 키를 비우면 marketdata._client()가 None → asking/financials 등
    # 모든 KIS REST 경로가 차단된다(demo 시드만 사용, 토큰 발급/알림톡 없음)
    env["SM_KIS_APP_KEY"] = ""
    env["SM_KIS_APP_SECRET"] = ""
    return env


def _wait_healthz(base: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = httpx.get(base + "/healthz", timeout=2)
            if r.status_code == 200:
                return
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.2)
    raise RuntimeError("데모서버 /healthz 미응답(%.0fs): %s" % (timeout, last))


@contextmanager
def demo_server(port: Optional[int] = None) -> Iterator[ServerHandle]:
    port = port or ports.free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "backend.cli", "serve",
         "--host", "127.0.0.1", "--port", str(port)],
        env=_child_env())
    try:
        _wait_healthz("http://127.0.0.1:%d" % port)
        yield ServerHandle(port=port, pid=proc.pid)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=4)
