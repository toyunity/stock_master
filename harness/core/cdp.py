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
