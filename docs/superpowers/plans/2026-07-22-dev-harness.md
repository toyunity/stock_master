# Stock Master 개발 하네스 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** verify·test·eval·ops 4개 서브커맨드를 `python -m harness <cmd>` 단일 진입점으로 묶은, repo에 커밋된 재현 가능한 개발 하네스를 만든다.

**Architecture:** top-level `harness/` 패키지(앱 런타임 `backend`와 분리). 공유 코어(`core/ports`·`core/server`·`core/bake`·`core/cdp`)를 4개 커맨드(`cmd/*`)가 사용한다. 데모서버는 PID 추적으로만 종료해 마스터 실서버(8000)를 구조적으로 보호한다. eval은 순수 판정 매퍼의 `{text,tone}` 골든 회귀, CI(test+eval)는 GitHub Actions.

**Tech Stack:** Python 3.9(stdlib argparse/subprocess/socket/importlib), httpx(기존 의존성), websockets(dev 의존성 신규 — CDP), 헤드리스 Chrome, pytest, node(스모크).

## Global Constraints

- **마스터 실서버(8000) 절대 종료 금지.** 서버 종료는 자기가 spawn한 `Popen` 객체의
  PID로만(`proc.terminate()`/`proc.kill()`). `pkill`/`killall`/포트 문자열 매칭 **금지**.
- **검증 서버는 항상 데모.** 하네스가 띄우는 서버 프로세스 env에 `SM_FLOW_MODE=demo`·
  `SM_AUTH_ENABLED=false`를 **강제 주입**(부모 env보다 우선).
- **KIS 미접촉.** verify/test/eval은 KIS REST/WS를 호출하지 않는다(전부 demo 시드).
- **Python 3.9 호환 문법만.** match문·`X|Y` 타입힌트 금지. `Optional[...]`/`Dict[...]` 사용.
- **앱 런타임 미오염.** `harness/`는 `backend` import 가능하나 그 역은 금지. `pyproject`
  `packages.find include=["backend*"]`가 `harness`를 안 잡음(배포본 미포함) — Task 9에서 검증.
- **산출물 미커밋.** 스크린샷/베이크 HTML은 `harness/artifacts/`(gitignore).
- **인터프리터.** 하네스는 `.venv/bin/python`으로 실행. spawn하는 서버도 `sys.executable`.

---

### Task 1: 패키지 스켈레톤 + `core/ports` + `__main__` 디스패처

**Files:**
- Create: `harness/__init__.py`, `harness/core/__init__.py`, `harness/cmd/__init__.py`
- Create: `harness/core/ports.py`
- Create: `harness/__main__.py`
- Test: `tests/test_harness_ports.py`

**Interfaces:**
- Produces: `harness.core.ports.free_port() -> int` (OS가 준 사용가능 TCP 포트).
- Produces: `python -m harness <verify|test|eval|ops>` argparse 디스패처(각 서브커맨드는
  `harness.cmd.<name>.main(args) -> int` 를 lazy import해 호출, 반환값=exit code).

- [ ] **Step 1: Write the failing test**

`tests/test_harness_ports.py`:
```python
import socket

from harness.core import ports


def test_free_port_is_bindable():
    p = ports.free_port()
    assert 1024 < p < 65536
    # 반환된 포트에 실제로 바인드 가능해야 한다(회수됨)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", p))
    s.close()


def test_free_port_varies():
    # 서로 다른 두 호출이 대체로 다른 포트를 준다(연속 점유 방지)
    a = ports.free_port()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", a))
    b = ports.free_port()
    s.close()
    assert b != a
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_harness_ports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness'`

- [ ] **Step 3: Write minimal implementation**

`harness/__init__.py`, `harness/core/__init__.py`, `harness/cmd/__init__.py`: 빈 파일.

`harness/core/ports.py`:
```python
"""빈 TCP 포트 할당 — 0번 포트에 바인드해 OS가 고른 번호를 회수한다."""
import socket


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
```

`harness/__main__.py`:
```python
"""개발 하네스 진입점: python -m harness <verify|test|eval|ops>."""
import argparse
import importlib
import sys

_COMMANDS = ("verify", "test", "eval", "ops")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="harness", description="Stock Master 개발 하네스")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in _COMMANDS:
        sub.add_parser(name, add_help=False)  # 각 커맨드가 자체 인자 파싱
    args, rest = p.parse_known_args(argv)
    mod = importlib.import_module("harness.cmd." + args.cmd)
    return int(mod.main(rest) or 0)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_harness_ports.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add harness/ tests/test_harness_ports.py
git commit -m "feat(harness): 패키지 스켈레톤 + core.ports + __main__ 디스패처"
```

---

### Task 2: `core/server.py` — 데모서버 수명주기(PID 추적) + 8000 보호

**Files:**
- Create: `harness/core/server.py`
- Test: `tests/test_harness_server.py`

**Interfaces:**
- Consumes: `harness.core.ports.free_port`.
- Produces: `harness.core.server.ServerHandle` (`.port:int`, `.pid:int`, `.base:str`).
- Produces: `harness.core.server.demo_server(port: Optional[int] = None)` —
  `@contextmanager`, `SM_FLOW_MODE=demo`/`SM_AUTH_ENABLED=false` 강제, `/healthz` 200
  대기, 종료 시 spawn한 PID만 terminate. yield `ServerHandle`.

- [ ] **Step 1: Write the failing test**

`tests/test_harness_server.py`:
```python
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
    env = server._child_env()
    assert env["SM_FLOW_MODE"] == "demo"
    assert env["SM_AUTH_ENABLED"] == "false"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_harness_server.py -v`
Expected: FAIL — `AttributeError: module 'harness.core.server' has no attribute ...`

- [ ] **Step 3: Write minimal implementation**

`harness/core/server.py`:
```python
"""데모서버 수명주기 — 빈 포트에 SM_FLOW_MODE=demo로 spawn, PID로만 종료.

마스터 실서버(8000) 보호가 최우선: pkill/포트 문자열 매칭을 절대 쓰지 않고,
자기가 만든 Popen 객체의 PID만 terminate 한다."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_harness_server.py -v`
Expected: PASS (3 passed). node/KIS 불필요.

- [ ] **Step 5: Commit**

```bash
git add harness/core/server.py tests/test_harness_server.py
git commit -m "feat(harness): core.server 데모서버 수명주기 — PID종료·데모강제·8000보호 회귀테스트"
```

---

### Task 3: `core/bake.py` — /live 정적 베이킹

**Files:**
- Create: `harness/core/bake.py`
- Test: `tests/test_harness_bake.py`

**Interfaces:**
- Consumes: `ServerHandle`(base URL).
- Produces: `harness.core.bake.bake_live(base: str, code: str = "000660", expand: bool = True) -> str`
  — 무한 SSE `/live` 페이지 HTML을 받아 `<body>` 직후에 `EventSource`/`fetch` 스텁을 주입한
  **완결 정적 HTML 문자열**을 반환. `expand=True`면 `details` 전개 스크립트도 주입.

- [ ] **Step 1: Write the failing test**

`tests/test_harness_bake.py`:
```python
from harness.core import bake, server


def test_bake_live_injects_stubs():
    with server.demo_server() as h:
        html = bake.bake_live(h.base, "000660")
    assert "window.__SNAP__" in html
    assert "window.EventSource=function" in html
    assert html.count("<body>") == 1  # 스텁이 <body>를 새로 만들지 않음
    # 스냅샷이 빈 객체가 아니라 실제 시드 데이터
    assert "__SNAP__={}" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_harness_bake.py -v`
Expected: FAIL — `AttributeError: module 'harness.core.bake' has no attribute 'bake_live'`

- [ ] **Step 3: Write minimal implementation**

`harness/core/bake.py`:
```python
"""무한 SSE /live 페이지를 정적 HTML로 베이킹 — 스크린샷/오프라인 렌더용.

SSE 1스냅샷과 canned fetch 응답을 window 전역 + EventSource/fetch 스텁으로 <body>
직후에 주입해, 페이지가 네트워크 없이 완전히 렌더되게 만든다."""
import json
import subprocess

import httpx

_FETCH_PATHS = ("/api/candles/%s?tf=5m", "/api/asking/%s", "/api/financials/%s")


def _sse_snapshot(base: str, code: str) -> str:
    # 몇 초 SSE를 받아 마지막 완전한 data 라인을 취한다(첫 이벤트는 시드 전 빈 상태)
    p = subprocess.run(
        ["curl", "-s", "-N", "--max-time", "6", base + "/api/live/%s/stream" % code],
        capture_output=True, text=True)
    last = None
    for line in p.stdout.splitlines():
        if line.startswith("data: "):
            last = line[6:]
    return last or "{}"


def _get(base: str, path: str) -> str:
    try:
        r = httpx.get(base + path, timeout=10)
        return r.text if r.status_code == 200 else "null"
    except Exception:  # noqa: BLE001
        return "null"


def bake_live(base: str, code: str = "000660", expand: bool = True) -> str:
    page = httpx.get(base + "/live/%s" % code, timeout=10).text
    snap = _sse_snapshot(base, code)
    fetch_map = {p % code: _get(base, p % code) for p in _FETCH_PATHS}
    fmap_js = ",".join("%s:%s" % (json.dumps(k), v if v != "null" else "null")
                       for k, v in fetch_map.items())
    stub = (
        "<script>window.__SNAP__=%s;window.__FMAP__={%s};"
        "window.EventSource=function(u){var s=this;this.close=function(){};"
        "this.addEventListener=function(t,f){if(t==='message')s.onmessage=f;};"
        "setTimeout(function(){if(s.onopen)s.onopen({});"
        "if(s.onmessage)s.onmessage({data:JSON.stringify(window.__SNAP__)});},40);};"
        "var _of=window.fetch;window.fetch=function(u,o){var k=''+u;"
        "for(var key in window.__FMAP__){if(k.indexOf(key)>=0){var d=window.__FMAP__[key];"
        "return Promise.resolve({ok:d!=null,status:d!=null?200:404,"
        "json:function(){return Promise.resolve(d);}});}}"
        "return Promise.resolve({ok:false,status:404,"
        "json:function(){return Promise.resolve({});}});};</script>"
    ) % (snap, fmap_js)
    if expand:
        stub += ("<script>setTimeout(function(){"
                 "document.querySelectorAll('details.sec,details.det,details.pro')"
                 ".forEach(function(d){d.open=true;});},400);</script>")
    return page.replace("<body>", "<body>" + stub, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_harness_bake.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add harness/core/bake.py tests/test_harness_bake.py
git commit -m "feat(harness): core.bake — /live 무한SSE 정적 베이킹(build_baked 승격)"
```

---

### Task 4: `core/cdp.py` — 헤드리스 크롬 스크린샷 + dev 의존성

**Files:**
- Create: `harness/core/cdp.py`
- Modify: `pyproject.toml` (dev extras에 `websockets` 추가)
- Test: `tests/test_harness_cdp.py`

**Interfaces:**
- Produces: `harness.core.cdp.chrome(port: Optional[int] = None)` — `@contextmanager`,
  헤드리스 크롬을 `--remote-debugging-port`로 띄우고 종료 시 PID로 kill. yield CDP base URL(str).
- Produces: `harness.core.cdp.shot(cdp_base: str, url: str, out_path: str, scheme: str) -> dict`
  — 390/DSF3/mobile·`prefers-color-scheme=scheme`로 캡처, PNG 저장, `{sw,cw,bh}` 메트릭 반환.
  캡처 후 target 닫음.
- Produces: `harness.core.cdp.find_chrome() -> Optional[str]` — 크롬 실행파일 경로 탐색.

- [ ] **Step 1: Add dev dependency + write the failing test**

`pyproject.toml`의 dev extras를 수정:
```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27", "websockets>=12.0"]
```
설치: `.venv/bin/pip install -e '.[dev]'`

`tests/test_harness_cdp.py`:
```python
import os

import pytest

from harness.core import cdp

pytestmark = pytest.mark.skipif(cdp.find_chrome() is None,
                                reason="헤드리스 크롬 미설치 — CDP 스모크 생략")


def test_shot_of_file_url(tmp_path):
    html = tmp_path / "p.html"
    html.write_text("<!doctype html><meta name=viewport "
                    "content='width=device-width'><body style='margin:0'>"
                    "<div style='width:390px;height:200px;background:#123'>hi</div>",
                    encoding="utf-8")
    out = tmp_path / "shot.png"
    with cdp.chrome() as base:
        m = cdp.shot(base, "file://" + str(html), str(out), "light")
    assert out.exists() and out.stat().st_size > 0
    assert m["sw"] <= 390  # 가로 오버플로 없음
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_harness_cdp.py -v`
Expected: FAIL — `AttributeError: module 'harness.core.cdp' has no attribute 'find_chrome'`
(크롬 미설치 환경이면 collection 단계에서 skip될 수 있음 — 그 경우 구현 후에도 skip 정상)

- [ ] **Step 3: Write minimal implementation**

`harness/core/cdp.py`:
```python
"""헤드리스 크롬 CDP 스크린샷 — 아이폰 폭(390/DSF3) 라이트·다크.

크롬을 원격 디버그 포트로 띄우고 WebSocket으로 CDP 명령을 보낸다. 캡처 후 target을
닫고(누수 방지), 컨텍스트 종료 시 크롬 PID를 직접 kill 한다."""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from typing import Iterator, Optional

import httpx
import websockets

from harness.core import ports

_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def find_chrome() -> Optional[str]:
    for c in _CANDIDATES:
        if os.path.exists(c):
            return c
    return shutil.which("google-chrome") or shutil.which("chromium")


@contextmanager
def chrome(port: Optional[int] = None) -> Iterator[str]:
    exe = find_chrome()
    if not exe:
        raise RuntimeError("헤드리스 크롬을 찾지 못함")
    port = port or ports.free_port()
    proc = subprocess.Popen(
        [exe, "--headless=new", "--disable-gpu", "--no-first-run",
         "--remote-debugging-port=%d" % port, "--user-data-dir=/tmp/harness-chrome-%d" % port,
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    try:
        _wait_cdp(base)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()


def _wait_cdp(base: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(base + "/json/version", timeout=2).status_code == 200:
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    raise RuntimeError("크롬 CDP 미기동")


async def _shot_async(cdp_base: str, url: str, out_path: str, scheme: str) -> dict:
    async with httpx.AsyncClient() as c:
        tgt = (await c.put(cdp_base + "/json/new?about:blank")).json()
    ws_url, tid = tgt["webSocketDebuggerUrl"], tgt["id"]
    try:
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            i = [0]

            async def cmd(method, params=None):
                i[0] += 1
                mid = i[0]
                await ws.send(json.dumps({"id": mid, "method": method,
                                          "params": params or {}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == mid:
                        if "error" in msg:
                            raise RuntimeError(method + ": " + str(msg["error"]))
                        return msg.get("result", {})

            await cmd("Page.enable")
            await cmd("Emulation.setDeviceMetricsOverride",
                      {"width": 390, "height": 844, "deviceScaleFactor": 3, "mobile": True})
            await cmd("Emulation.setEmulatedMedia",
                      {"media": "screen",
                       "features": [{"name": "prefers-color-scheme", "value": scheme}]})
            await cmd("Page.navigate", {"url": url})
            await asyncio.sleep(3.0)  # JS fetch/렌더/차트/SSE스텁 정착
            await cmd("Runtime.evaluate", {"expression":
                "(function(){var s=document.createElement('style');"
                "s.textContent='#tabbar{display:none!important}';"
                "document.head.appendChild(s);})()"})
            ev = await cmd("Runtime.evaluate", {"expression":
                "JSON.stringify({sw:document.documentElement.scrollWidth,"
                "cw:document.documentElement.clientWidth,"
                "bh:document.body.scrollHeight})", "returnByValue": True})
            metrics = json.loads(ev.get("result", {}).get("value", "{}"))
            img = await cmd("Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": True})
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(img["data"]))
            return metrics
    finally:
        async with httpx.AsyncClient() as c:
            await c.get(cdp_base + "/json/close/" + tid)


def shot(cdp_base: str, url: str, out_path: str, scheme: str) -> dict:
    return asyncio.run(_shot_async(cdp_base, url, out_path, scheme))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_harness_cdp.py -v`
Expected: PASS (크롬 있으면 1 passed / 없으면 skipped)

- [ ] **Step 5: Commit**

```bash
git add harness/core/cdp.py tests/test_harness_cdp.py pyproject.toml
git commit -m "feat(harness): core.cdp — 헤드리스 크롬 CDP 스크린샷(390/DSF3, 라이트·다크) + websockets dev의존성"
```

---

### Task 5: `cmd/verify.py` — 5화면 × 라이트/다크 + 오버플로 검출

**Files:**
- Create: `harness/cmd/verify.py`
- Create: `harness/artifacts/.gitkeep`
- Test: `tests/test_harness_verify.py`

**Interfaces:**
- Consumes: `demo_server`, `bake_live`, `cdp.chrome`, `cdp.shot`, `cdp.find_chrome`.
- Consumes: `backend.api.auth._LOGIN_HTML`(str), `backend.api.auth._twofa_html()`(호출 시 str).
- Produces: `harness.cmd.verify.SCREENS` — `[(name, kind, source)]` 리스트
  (kind: `"route"`=데모 경로, `"baked"`=/live 베이킹, `"html"`=직접 HTML 문자열).
- Produces: `harness.cmd.verify.main(argv) -> int` — 각 화면×{light,dark}를
  `harness/artifacts/<name>-<scheme>.png`로 저장, 가로 오버플로(sw>390) 있으면 1 반환.

- [ ] **Step 1: Write the failing test**

`tests/test_harness_verify.py`:
```python
from harness.cmd import verify


def test_screens_cover_five():
    names = {s[0] for s in verify.SCREENS}
    assert names == {"live", "dashboard", "scanner", "widget", "login"}


def test_login_html_importable():
    # login 화면 소스가 실제로 임포트되는 HTML 문자열이어야 한다(라우트 미의존)
    src = dict((s[0], s) for s in verify.SCREENS)["login"]
    assert src[1] == "html"
    assert "<!doctype html" in src[2].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_harness_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.cmd.verify'`

- [ ] **Step 3: Write minimal implementation**

`harness/artifacts/.gitkeep`: 빈 파일.

`harness/cmd/verify.py`:
```python
"""verify — 5화면(라이브·대시보드·스캐너·위젯·로그인)을 아이폰 폭 라이트/다크로 캡처하고
가로 오버플로를 검출한다. 데모서버·헤드리스 크롬을 PID로 관리."""
import argparse
import os
import tempfile

from backend.api import auth
from harness.core import bake, cdp, server

_ART = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts")

# (name, kind, source): kind route=데모경로 / baked=/live 베이킹 / html=직접 HTML
SCREENS = [
    ("live", "baked", "/live/000660"),
    ("dashboard", "route", "/"),
    ("scanner", "route", "/scanner"),
    ("widget", "route", "/widget-setup"),
    ("login", "html", auth._LOGIN_HTML),
]


def _write_tmp(html: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".html", dir=_ART)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harness verify")
    ap.add_argument("--only", default="", help="쉼표구분 화면명(기본 전체)")
    ap.add_argument("--theme", choices=["light", "dark", "both"], default="both")
    args = ap.parse_args(argv)
    if cdp.find_chrome() is None:
        print("헤드리스 크롬 미설치 — verify 생략")
        return 0
    os.makedirs(_ART, exist_ok=True)
    only = set(x for x in args.only.split(",") if x)
    schemes = ["light", "dark"] if args.theme == "both" else [args.theme]
    screens = [s for s in SCREENS if not only or s[0] in only]
    bad = []
    with server.demo_server() as h, cdp.chrome() as cdp_base:
        for name, kind, src in screens:
            if kind == "baked":
                url = "file://" + _write_tmp(bake.bake_live(h.base, "000660"))
            elif kind == "route":
                url = h.base + src
            else:  # html
                html = src() if callable(src) else src
                url = "file://" + _write_tmp(html)
            for scheme in schemes:
                out = os.path.join(_ART, "%s-%s.png" % (name, scheme))
                m = cdp.shot(cdp_base, url, out, scheme)
                flag = " ⚠ OVERFLOW" if m.get("sw", 0) > 390 else ""
                print("%-10s %-5s sw=%s bh=%s -> %s%s"
                      % (name, scheme, m.get("sw"), m.get("bh"), out, flag))
                if m.get("sw", 0) > 390:
                    bad.append("%s-%s" % (name, scheme))
    if bad:
        print("가로 오버플로 검출: " + ", ".join(bad))
        return 1
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_harness_verify.py -v`
Expected: PASS (2 passed)

수동 스모크(크롬 있으면): `.venv/bin/python -m harness verify --only login`
Expected: `login light ... -> .../artifacts/login-light.png` 2줄, 오버플로 없음.

- [ ] **Step 5: Commit**

```bash
git add harness/cmd/verify.py harness/artifacts/.gitkeep tests/test_harness_verify.py
git commit -m "feat(harness): verify — 5화면 라이트/다크 캡처 + 가로 오버플로 검출"
```

---

### Task 6: `cmd/test.py` — pytest + node 스모크 러너

**Files:**
- Create: `harness/cmd/test.py`
- Test: `tests/test_harness_testcmd.py`

**Interfaces:**
- Produces: `harness.cmd.test.main(argv) -> int` — 하네스 자신을 실행한 인터프리터로
  `pytest`를 돌리고 종료코드를 그대로 반환. node 유무를 안내 출력.

- [ ] **Step 1: Write the failing test**

`tests/test_harness_testcmd.py`:
```python
from harness.cmd import test as testcmd


def test_build_argv_targets_pytest():
    argv = testcmd._pytest_argv([])
    assert argv[0].endswith("python") or "python" in argv[0]
    assert "pytest" in argv


def test_build_argv_passthrough():
    argv = testcmd._pytest_argv(["tests/test_config.py", "-k", "foo"])
    assert "tests/test_config.py" in argv and "-k" in argv and "foo" in argv
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_harness_testcmd.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.cmd.test'`

- [ ] **Step 3: Write minimal implementation**

`harness/cmd/test.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_harness_testcmd.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add harness/cmd/test.py tests/test_harness_testcmd.py
git commit -m "feat(harness): test — pytest+node 스모크 단일 러너"
```

---

### Task 7: `cmd/eval.py` + 시나리오·골든 — 판정 회귀

**Files:**
- Create: `harness/cmd/eval.py`
- Create: `harness/scenarios/credit.json`, `harness/scenarios/shortbal.json`, `harness/scenarios/exvol.json`
- Create: `harness/scenarios/golden/credit.json`, `.../shortbal.json`, `.../exvol.json`
- Test: `tests/test_harness_eval.py`

**Interfaces:**
- Consumes: `backend.flow.credit.credit_signal(rows)`, `backend.flow.shortbal.short_signal(price_rate, chg_qty)`,
  `backend.flow.exvol.distortion(nxt_after_price, krx_close, after_vol, total_vol)`.
- Produces: `harness.cmd.eval.run_scenario(path) -> list` — 각 case의 `func(**input)`을
  골든과 비교, `[{name, ok, got, want}]` 반환.
- Produces: `harness.cmd.eval.main(argv) -> int` — 전 시나리오 실행, 불일치 시 diff 출력 +
  exit 1. `--update`면 골든을 실제 출력으로 갱신 후 0.

시나리오 스키마: `{"module": "backend.flow.credit", "func": "credit_signal",
"cases": [{"name": "...", "input": { ...kwargs... }}]}`. 러너는 `func(**input)` 호출.
`credit_signal(rows)`는 `input={"rows":[...]}` → 키워드 인자로 전달됨.

- [ ] **Step 1: Write scenario + golden fixtures + the failing test**

`harness/scenarios/credit.json`:
```json
{
  "module": "backend.flow.credit",
  "func": "credit_signal",
  "cases": [
    {"name": "표본부족", "input": {"rows": [{"qty": 100, "close": 1000}]}},
    {"name": "하락속신용증가_경계", "input": {"rows": [
      {"qty": 100, "close": 1000}, {"qty": 102, "close": 980}]}},
    {"name": "상승속신용확대", "input": {"rows": [
      {"qty": 100, "close": 1000}, {"qty": 102, "close": 1020}]}},
    {"name": "신용상환_완화", "input": {"rows": [
      {"qty": 100, "close": 1000}, {"qty": 98, "close": 1005}]}},
    {"name": "중립", "input": {"rows": [
      {"qty": 100, "close": 1000}, {"qty": 100, "close": 1005}]}}
  ]
}
```

`harness/scenarios/shortbal.json`:
```json
{
  "module": "backend.flow.shortbal",
  "func": "short_signal",
  "cases": [
    {"name": "건강한상승_숏이탈", "input": {"price_rate": 1.5, "chg_qty": -500}},
    {"name": "상승중숏축적_경계", "input": {"price_rate": 1.5, "chg_qty": 500}},
    {"name": "하락베팅강화_경계", "input": {"price_rate": -1.2, "chg_qty": 500}},
    {"name": "숏커버링구간", "input": {"price_rate": -1.2, "chg_qty": -500}},
    {"name": "결측", "input": {"price_rate": null, "chg_qty": 500}}
  ]
}
```

`harness/scenarios/exvol.json`:
```json
{
  "module": "backend.flow.exvol",
  "func": "distortion",
  "cases": [
    {"name": "왜곡경고", "input": {"nxt_after_price": 1020, "krx_close": 1000,
      "after_vol": 50, "total_vol": 100000}},
    {"name": "유의미변동_거래동반", "input": {"nxt_after_price": 1020, "krx_close": 1000,
      "after_vol": 5000, "total_vol": 100000}},
    {"name": "변동미미", "input": {"nxt_after_price": 1002, "krx_close": 1000,
      "after_vol": 5000, "total_vol": 100000}},
    {"name": "결측", "input": {"nxt_after_price": null, "krx_close": 1000,
      "after_vol": 5000, "total_vol": 100000}}
  ]
}
```

골든 3개는 **Step 3 이후 `--update`로 생성**한다(초기엔 존재하지 않음). 아래 테스트는
그 흐름을 검증한다.

`tests/test_harness_eval.py`:
```python
import json

from harness.cmd import eval as ev


def test_run_scenario_matches_golden(tmp_path):
    # 임시 시나리오 + 골든으로 통과/불일치 양쪽 확인
    scen = tmp_path / "s.json"
    scen.write_text(json.dumps({
        "module": "backend.flow.shortbal", "func": "short_signal",
        "cases": [{"name": "c1", "input": {"price_rate": 1.5, "chg_qty": -500}}]
    }), encoding="utf-8")
    gdir = tmp_path / "golden"
    gdir.mkdir()
    (gdir / "s.json").write_text(json.dumps({
        "c1": {"text": "건강한 상승 (숏 이탈)", "tone": "good"}}), encoding="utf-8")
    res = ev.run_scenario(str(scen))
    assert res == [{"name": "c1", "ok": True,
                    "got": {"text": "건강한 상승 (숏 이탈)", "tone": "good"},
                    "want": {"text": "건강한 상승 (숏 이탈)", "tone": "good"}}]


def test_run_scenario_detects_drift(tmp_path):
    scen = tmp_path / "s.json"
    scen.write_text(json.dumps({
        "module": "backend.flow.shortbal", "func": "short_signal",
        "cases": [{"name": "c1", "input": {"price_rate": 1.5, "chg_qty": -500}}]
    }), encoding="utf-8")
    gdir = tmp_path / "golden"
    gdir.mkdir()
    (gdir / "s.json").write_text(json.dumps({
        "c1": {"text": "틀린 문구", "tone": "warn"}}), encoding="utf-8")
    res = ev.run_scenario(str(scen))
    assert res[0]["ok"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_harness_eval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.cmd.eval'`

- [ ] **Step 3: Write minimal implementation**

`harness/cmd/eval.py`:
```python
"""eval — 순수 판정 매퍼의 {text,tone} 출력을 시나리오별 골든과 비교(의미 드리프트 회귀).

node 스모크가 '렌더가 죽었나'를 잡는다면, 여기서는 '판정 의미가 조용히 바뀌었나'
(톤 warn↔good 뒤집힘 등)를 잡는다. 규칙 엔진이라 결정론적 골든 diff로 충분."""
import argparse
import glob
import importlib
import json
import os
from typing import List

_SCEN_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scenarios")
_GOLDEN_DIR = os.path.join(_SCEN_DIR, "golden")


def _call(module: str, func: str, kwargs: dict):
    fn = getattr(importlib.import_module(module), func)
    return fn(**kwargs)


def _golden_path(scen_path: str) -> str:
    return os.path.join(_GOLDEN_DIR, os.path.basename(scen_path))


def run_scenario(scen_path: str) -> List[dict]:
    with open(scen_path, encoding="utf-8") as f:
        scen = json.load(f)
    gpath = _golden_path(scen_path)
    golden = {}
    if os.path.exists(gpath):
        with open(gpath, encoding="utf-8") as f:
            golden = json.load(f)
    out = []
    for case in scen["cases"]:
        got = _call(scen["module"], scen["func"], case["input"])
        want = golden.get(case["name"])
        out.append({"name": case["name"], "ok": got == want, "got": got, "want": want})
    return out


def _update_golden(scen_path: str) -> None:
    with open(scen_path, encoding="utf-8") as f:
        scen = json.load(f)
    result = {c["name"]: _call(scen["module"], scen["func"], c["input"])
              for c in scen["cases"]}
    os.makedirs(_GOLDEN_DIR, exist_ok=True)
    with open(_golden_path(scen_path), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harness eval")
    ap.add_argument("--update", action="store_true", help="골든을 실제 출력으로 갱신")
    args = ap.parse_args(argv)
    scenarios = sorted(glob.glob(os.path.join(_SCEN_DIR, "*.json")))
    if args.update:
        for s in scenarios:
            _update_golden(s)
            print("갱신:", os.path.basename(s))
        return 0
    failed = 0
    for s in scenarios:
        for r in run_scenario(s):
            tag = "ok " if r["ok"] else "FAIL"
            print("[%s] %s::%s" % (tag, os.path.basename(s), r["name"]))
            if not r["ok"]:
                failed += 1
                print("   got :", r["got"])
                print("   want:", r["want"])
    if failed:
        print("판정 드리프트 %d건 — 의도된 변경이면 `harness eval --update`" % failed)
        return 1
    print("판정 골든 일치 ✓")
    return 0
```

- [ ] **Step 4: Run test to verify it passes, then generate real goldens**

Run: `.venv/bin/python -m pytest tests/test_harness_eval.py -v`
Expected: PASS (2 passed)

골든 생성: `.venv/bin/python -m harness eval --update`
Expected: `갱신: credit.json` / `shortbal.json` / `exvol.json` 3줄.
검증: `.venv/bin/python -m harness eval`
Expected: 전 케이스 `[ok ]` + `판정 골든 일치 ✓`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add harness/cmd/eval.py harness/scenarios/ tests/test_harness_eval.py
git commit -m "feat(harness): eval — 판정 매퍼 {text,tone} 골든 회귀(credit·shortbal·exvol)"
```

---

### Task 8: `cmd/ops.py` — 읽기전용 운영 점검

**Files:**
- Create: `harness/cmd/ops.py`
- Test: `tests/test_harness_ops.py`

**Interfaces:**
- Produces: `harness.cmd.ops.local_status() -> dict` — 8000 리스너 PID 유무 + `/healthz`.
- Produces: `harness.cmd.ops.public_status(base) -> dict` — 공개 URL 200 + 미인증 302 확인.
- Produces: `harness.cmd.ops.main(argv) -> int` — 상태를 출력(읽기전용). `restart`
  서브명령은 이 Task 범위 밖(비목표: 자동 재기동 없음) — 대신 수동 절차를 안내 출력만 한다.

- [ ] **Step 1: Write the failing test**

`tests/test_harness_ops.py`:
```python
from harness.cmd import ops


def test_local_status_shape():
    st = ops.local_status()
    assert set(st.keys()) == {"listening", "pid", "healthz"}
    assert isinstance(st["listening"], bool)


def test_main_readonly_returns_zero():
    # 읽기전용 점검은 서버 유무와 무관하게 정상 종료(0)
    assert ops.main(["--no-public"]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_harness_ops.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.cmd.ops'`

- [ ] **Step 3: Write minimal implementation**

`harness/cmd/ops.py`:
```python
"""ops — 운영 상태 읽기전용 점검(로컬 8000·공개 Funnel·인증 게이트).

재기동은 하지 않는다(비목표). 자동 재기동 금지 — 필요 시 수동 절차만 안내한다."""
import argparse
import subprocess

import httpx

_FUNNEL = "https://YOUR-MAC.YOUR-TAILNET.ts.net"


def _listener_pid(port: int = 8000):
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        return int(out.splitlines()[0]) if out else None
    except Exception:  # noqa: BLE001
        return None


def local_status() -> dict:
    pid = _listener_pid(8000)
    healthz = None
    if pid is not None:
        try:
            healthz = httpx.get("http://127.0.0.1:8000/healthz", timeout=3).json()
        except Exception:  # noqa: BLE001
            healthz = "unreachable"
    return {"listening": pid is not None, "pid": pid, "healthz": healthz}


def public_status(base: str = _FUNNEL) -> dict:
    try:
        root = httpx.get(base + "/", timeout=8, follow_redirects=False)
        api = httpx.get(base + "/api/scanner", timeout=8, follow_redirects=False)
        return {"root_status": root.status_code, "api_status": api.status_code,
                "auth_gate": api.status_code in (302, 401)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harness ops")
    ap.add_argument("--no-public", action="store_true", help="공개 URL 점검 생략")
    args = ap.parse_args(argv)
    st = local_status()
    print("로컬 8000: listening=%s pid=%s healthz=%s"
          % (st["listening"], st["pid"], st["healthz"]))
    if not args.no_public:
        ps = public_status()
        print("공개 Funnel:", ps)
    print("※ 재기동은 자동으로 하지 않습니다. 필요 시 마스터 확인 후 수동 절차로.")
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_harness_ops.py -v`
Expected: PASS (2 passed)

수동 스모크: `.venv/bin/python -m harness ops --no-public`
Expected: `로컬 8000: listening=... ` 1줄 + 안내. **8000을 죽이지 않음**.

- [ ] **Step 5: Commit**

```bash
git add harness/cmd/ops.py tests/test_harness_ops.py
git commit -m "feat(harness): ops — 로컬/공개/인증게이트 읽기전용 점검(재기동 없음)"
```

---

### Task 9: Makefile + CI + README + gitignore + verify 스킬 갱신

**Files:**
- Create: `Makefile`, `.github/workflows/test.yml`, `harness/README.md`
- Modify: `.gitignore`(신규 생성 가능), `.claude/skills/verify/SKILL.md`
- Test: `tests/test_harness_packaging.py`

**Interfaces:**
- Produces: `make verify|test|eval|ops|ci` 별칭 + CI가 `harness test`+`harness eval` 실행.
- 검증: `harness`가 배포 패키지에 포함되지 않음(`packages.find include=["backend*"]`).

- [ ] **Step 1: Write the failing test**

`tests/test_harness_packaging.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails (or passes trivially — then still add configs)**

Run: `.venv/bin/python -m pytest tests/test_harness_packaging.py -v`
Expected: PASS(이미 include가 backend*만이라 통과) — 이 태스크는 회귀 방어 테스트 고정 +
설정 파일 추가가 목적.

- [ ] **Step 3: Add config + docs**

`Makefile`:
```makefile
PY := .venv/bin/python

.PHONY: verify test eval eval-update ops ci
verify:      ; $(PY) -m harness verify
test:        ; $(PY) -m harness test
eval:        ; $(PY) -m harness eval
eval-update: ; $(PY) -m harness eval --update
ops:         ; $(PY) -m harness ops
ci: test eval
```

`.github/workflows/test.yml`:
```yaml
name: test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.9"
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: pip install -e '.[dev]'
      - run: python -m harness test
      - run: python -m harness eval
```

`.gitignore`에 추가(없으면 생성):
```
harness/artifacts/*
!harness/artifacts/.gitkeep
```

`harness/README.md`:
```markdown
# 개발 하네스

`python -m harness <verify|test|eval|ops>` — 또는 `make verify|test|eval|ops`.

- **verify** 5화면(라이브·대시보드·스캐너·위젯·로그인)을 아이폰 폭(390/DSF3) 라이트/
  다크로 캡처하고 가로 오버플로를 검출. 산출물 `harness/artifacts/` (미커밋). 헤드리스
  크롬 필요.
- **test** pytest 전체 + node 렌더 스모크(node 없으면 해당 테스트 skip).
- **eval** 순수 판정 매퍼의 `{text,tone}`를 골든과 비교(의미 드리프트 회귀). 의도된
  변경이면 `make eval-update`.
- **ops** 로컬 8000·공개 Funnel·인증 게이트 읽기전용 점검(재기동 안 함).

## 안전
- 데모서버는 항상 `SM_FLOW_MODE=demo`·`SM_AUTH_ENABLED=false`로 뜨고, 하네스가 spawn한
  PID로만 종료한다. **마스터 실서버(8000)를 절대 건드리지 않는다.**
- KIS는 접촉하지 않는다(전부 demo 시드).
```

`.claude/skills/verify/SKILL.md` 갱신 — "뒷정리" 섹션 위에 아래를 추가:
```markdown
## 하네스(권장 · scratchpad 대체)

시각/테스트/판정/운영 검증은 이제 repo에 커밋된 하네스로 재현한다:

```bash
.venv/bin/python -m harness verify   # 5화면 라이트/다크 샷 + 오버플로 검출
.venv/bin/python -m harness test     # pytest + node 스모크
.venv/bin/python -m harness eval     # 판정 {text,tone} 골든 회귀
.venv/bin/python -m harness ops --no-public  # 8000 읽기전용 점검
```

데모서버·크롬은 하네스가 PID로 자동 정리한다(8000 미접촉).
```

- [ ] **Step 4: Run full suite to verify nothing regressed**

Run: `.venv/bin/python -m harness test`
Expected: 기존 428+ 테스트 + 신규 harness 테스트 모두 green(크롬/node 없으면 해당만 skip).

- [ ] **Step 5: Commit**

```bash
git add Makefile .github/workflows/test.yml harness/README.md .gitignore \
        .claude/skills/verify/SKILL.md tests/test_harness_packaging.py
git commit -m "feat(harness): Makefile·CI(test+eval)·README·gitignore + verify 스킬 갱신"
```

---

## Self-Review (작성자 점검 결과)

**Spec coverage:**
- 공유 코어(ports/server/bake/cdp) → Task 1~4 ✓
- verify/test/eval/ops → Task 5~8 ✓
- 8000 보호(PID종료·pkill금지) → Task 2 구조 + `test_source_has_no_pkill` ✓
- 데모/인증off 강제 → Task 2 `_child_env` + 테스트 ✓
- eval 대상(credit/shortbal/exvol 판정) → Task 7 구체 시나리오·골든 ✓
- CI(test+eval), verify 로컬전용 → Task 9 `test.yml` ✓
- gitignore artifacts / packages.find 미포함 → Task 9 ✓
- 하네스 자체 테스트 → 각 Task의 `tests/test_harness_*.py` ✓
- verify 스킬 갱신 → Task 9 ✓
- 비목표(LLM심판·자동재기동·전체HTML골든) → 미구현(의도) ✓

**Placeholder scan:** "TBD/TODO/적절히" 없음. 모든 코드 스텝에 실제 코드 포함.

**Type consistency:** `demo_server`→`ServerHandle(.base/.pid/.port)`가 Task 3·5에서
동일 사용. `cdp.chrome`(yield base)·`cdp.shot(base,url,out,scheme)→dict{sw,cw,bh}`가
Task 5에서 동일 시그니처. `run_scenario`→`[{name,ok,got,want}]`가 Task 7 테스트와 일치.

**참고(구현 중 확인):** 스펙의 eval "node 2차 경로(#today-line·타이밍 알약)"는 이 플랜에
포함하지 않았다(파이썬 판정 백본으로 충분, node 경로는 유지비 대비 후순위 — 비목표에
준함). 필요 시 별도 태스크로 추가.
