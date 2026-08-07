"""헤드리스 크롬 CDP 스크린샷 — 아이폰 폭(390/DSF3) 라이트·다크.

크롬을 원격 디버그 포트로 띄우고 WebSocket으로 CDP 명령을 보낸다. 캡처 후 target을
닫고(누수 방지), 컨텍스트 종료 시 크롬 PID를 직접 kill 한다."""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
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


def _ci_flags() -> list:
    """CI 컨테이너 전용 플래그. **마스터의 맥에서는 붙이지 않는다.**

    우분투 24.04는 AppArmor로 비특권 user namespace를 막아서 크롬 샌드박스가
    zygote를 못 띄우고 그대로 죽는다 — CDP 포트가 영영 안 열려 '미기동'으로만 보인다
    (2026-08-07 CI 실패). 이 하니스는 우리가 만든 로컬 파일·localhost만 여니
    CI에서 샌드박스를 끄는 대가가 없다. `/dev/shm`이 작은 컨테이너 대비도 함께."""
    return ["--no-sandbox", "--disable-dev-shm-usage"] if os.environ.get("CI") else []


@contextmanager
def chrome(port: Optional[int] = None) -> Iterator[str]:
    exe = find_chrome()
    if not exe:
        raise RuntimeError("헤드리스 크롬을 찾지 못함")
    port = port or ports.free_port()
    user_data_dir = "/tmp/harness-chrome-%d" % port
    # stderr를 버리지 않는다 — 크롬이 죽은 이유가 여기에만 남는다. DEVNULL로 삼키면
    # 실패가 '미기동' 한 줄로만 보여 CI에서 원인을 못 찾는다(2026-08-07 실패로 드러남).
    err = tempfile.NamedTemporaryFile(prefix="harness-chrome-", suffix=".log",
                                      delete=False)
    proc = subprocess.Popen(
        [exe, "--headless=new", "--disable-gpu", "--no-first-run",
         "--remote-debugging-port=%d" % port, "--user-data-dir=" + user_data_dir,
         *_ci_flags(), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=err)
    base = "http://127.0.0.1:%d" % port
    try:
        _wait_cdp(base, proc=proc, err_path=err.name)
        yield base
    finally:
        err.close()
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(user_data_dir, ignore_errors=True)
        try:
            os.unlink(err.name)     # 실패 시 tail은 이미 예외 메시지에 실렸다
        except OSError:
            pass


def _chrome_stderr(err_path: Optional[str], limit: int = 600) -> str:
    if not err_path or not os.path.exists(err_path):
        return ""
    try:
        with open(err_path, encoding="utf-8", errors="replace") as f:
            tail = f.read().strip()[-limit:]
    except OSError:
        return ""
    return ("\n크롬 stderr: " + tail) if tail else "\n크롬 stderr: (비어 있음)"


def _wait_cdp(base: str, timeout: float = 40.0, proc=None,
              err_path: Optional[str] = None) -> None:
    """CDP 포트가 열릴 때까지 대기. 크롬이 **먼저 죽으면 즉시** 사유와 함께 실패한다.

    타임아웃이 15초였을 때 CI(2코어·부하)에서 콜드 스타트를 못 견뎠고, 죽은 경우에도
    끝까지 기다렸다가 이유 없는 '미기동'만 남겼다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(base + "/json/version", timeout=2).status_code == 200:
                return
        except Exception:  # noqa: BLE001
            pass
        if proc is not None and proc.poll() is not None:
            raise RuntimeError("크롬이 기동 중 종료됨(exit=%s)%s"
                               % (proc.returncode, _chrome_stderr(err_path)))
        time.sleep(0.2)
    raise RuntimeError("크롬 CDP 미기동(%.0f초 대기)%s"
                       % (timeout, _chrome_stderr(err_path)))


async def _shot_async(cdp_base: str, url: str, out_path: str, scheme: str) -> dict:
    async with httpx.AsyncClient() as c:
        tgt = (await c.put(cdp_base + "/json/new?about:blank")).json()
    tid = tgt.get("id")
    try:
        ws_url = tgt["webSocketDebuggerUrl"]
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            i = [0]

            async def cmd(method, params=None):
                i[0] += 1
                mid = i[0]
                await ws.send(json.dumps({"id": mid, "method": method,
                                          "params": params or {}}))
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    msg = json.loads(raw)
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
        if tid:
            async with httpx.AsyncClient() as c:
                await c.get(cdp_base + "/json/close/" + tid)


def shot(cdp_base: str, url: str, out_path: str, scheme: str) -> dict:
    return asyncio.run(_shot_async(cdp_base, url, out_path, scheme))
