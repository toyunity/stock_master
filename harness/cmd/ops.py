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
