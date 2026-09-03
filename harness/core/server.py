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
    # KIS 미접촉 보장: 키를 비운다. 두 겹으로 막힌다 —
    #  (1) marketdata._client()가 None을 돌려줘 asking/financials 등이 안 나간다.
    #  (2) KisClient.token()/approval_key()가 키 없음을 보고 거절한다.
    # (2)가 없던 동안 이 주석은 거짓이었다: candles._get_client()를 직접 쓰는 경로
    # (kospitemp·worldidx)는 (1)을 안 타고, data/cache/kis_token.json의 24시간짜리
    # 캐시 토큰으로 인증이 통과해 verify가 실 KIS를 때렸다(2026-08-12 실측).
    # 회귀 방지: tests/test_flow_kis_rest.py::test_no_key_refuses_even_with_valid_cached_token
    env["SM_KIS_APP_KEY"] = ""
    env["SM_KIS_APP_SECRET"] = ""
    # 토스 미접촉 보장. KIS보다 더 급하다 — 토스는 **client당 토큰 1개**라 재발급이
    # 이전 토큰을 즉시 무효화한다(스펙). 검증 서버가 한 번 발급하면 8000 실서버가
    # 그 자리에서 401이 된다(KIS는 옛 토큰이 만료까지 살아 있었다).
    # 회귀 방지: tests/test_toss.py::test_no_key_refuses_even_with_valid_cached_token
    env["SM_TOSS_CLIENT_ID"] = ""
    env["SM_TOSS_CLIENT_SECRET"] = ""
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
