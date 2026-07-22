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


def _call(module: str, func: str, kwargs: dict):
    fn = getattr(importlib.import_module(module), func)
    return fn(**kwargs)


def _golden_path(scen_path: str) -> str:
    return os.path.join(os.path.dirname(scen_path), "golden", os.path.basename(scen_path))


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
    gpath = _golden_path(scen_path)
    os.makedirs(os.path.dirname(gpath), exist_ok=True)
    with open(gpath, "w", encoding="utf-8") as f:
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
