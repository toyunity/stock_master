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
