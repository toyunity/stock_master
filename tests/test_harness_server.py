import inspect
import socket

import httpx

from harness.core import server


def test_source_has_no_pkill():
    """8000 보호: 종료 로직이 pkill/killall/포트 문자열 매칭을 쓰지 않는다(구조적 보장)."""
    src = inspect.getsource(server)
    for banned in ("pkill", "killall", "os.system", "shell=True"):
        assert banned not in src, "금지된 종료 수단: %s" % banned


def test_demo_server_up_and_down():
    with server.demo_server() as h:
        assert h.base.startswith("http://127.0.0.1:")
        r = httpx.get(h.base + "/healthz", timeout=10)
        assert r.status_code == 200 and r.json() == {"ok": True}
        pid, port = h.pid, h.port
    # 컨텍스트 종료 후: 포트가 풀렸고(=프로세스 죽음) 그 PID로 재바인드 가능
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.close()


def test_forces_demo_env(monkeypatch):
    """부모 env가 live/auth=true라도 데모/인증off로 덮어써 spawn한다."""
    monkeypatch.setenv("SM_FLOW_MODE", "live")
    monkeypatch.setenv("SM_AUTH_ENABLED", "true")
    monkeypatch.setenv("SM_KIS_APP_KEY", "REALKEY")
    monkeypatch.setenv("SM_KIS_APP_SECRET", "REALSECRET")
    monkeypatch.setenv("SM_TOSS_CLIENT_ID", "REALID")
    monkeypatch.setenv("SM_TOSS_CLIENT_SECRET", "REALSECRET")
    env = server._child_env()
    assert env["SM_FLOW_MODE"] == "demo"
    assert env["SM_AUTH_ENABLED"] == "false"
    assert env["SM_KIS_APP_KEY"] == ""
    assert env["SM_KIS_APP_SECRET"] == ""
    # 토스는 재발급이 이전 토큰을 즉시 죽인다 — 검증 서버가 한 번 발급하면
    # 8000 실서버가 그 자리에서 401이다. KIS보다 더 급하게 비워야 한다.
    assert env["SM_TOSS_CLIENT_ID"] == ""
    assert env["SM_TOSS_CLIENT_SECRET"] == ""
