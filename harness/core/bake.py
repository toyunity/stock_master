"""무한 SSE /live 페이지를 정적 HTML로 베이킹 — 스크린샷/오프라인 렌더용.

SSE 1스냅샷과 canned fetch 응답을 window 전역 + EventSource/fetch 스텁으로 <body>
직후에 주입해, 페이지가 네트워크 없이 완전히 렌더되게 만든다."""
import json
import subprocess

import httpx

_FETCH_PATHS = ("/api/candles/%s?tf=5m", "/api/asking/%s")


def _js_safe(s: str) -> str:
    # <script> 조기 종료 방지: JSON 문자열 안의 </ 를 <\/ 로 이스케이프(JS·JSON 동등)
    return s.replace("</", "<\\/")


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
    fmap_js = ",".join("%s:%s" % (json.dumps(k), _js_safe(v))
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
    ) % (_js_safe(snap), fmap_js)
    if expand:
        stub += ("<script>setTimeout(function(){"
                 "document.querySelectorAll('details.sec,details.det,details.pro')"
                 ".forEach(function(d){d.open=true;});},400);</script>")
    return page.replace("<body>", "<body>" + stub, 1)
