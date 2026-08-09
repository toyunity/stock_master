"""eval — 순수 판정 매퍼의 출력을 시나리오별 골든과 비교(의미 드리프트 회귀).

node 스모크가 '렌더가 죽었나'를 잡는다면, 여기서는 '판정 의미가 조용히 바뀌었나'
(톤 warn↔good 뒤집힘, 근월물이 한 달 밀림 등)를 잡는다. 규칙 엔진이라 결정론적
골든 diff로 충분하다. {text,tone}에서 출발했지만 지금은 화면이 그대로 믿는
순수 출력이면 무엇이든 담는다 — 요약 숫자·월물 문자열도 조용히 틀리면 똑같이 위험하다."""
import argparse
import datetime as dt
import glob
import importlib
import json
import os
from typing import List

_SCEN_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scenarios")

# JSON엔 날짜·시각 타입이 없다. 시나리오는 ISO 문자열로 적고 여기서 되살린다.
# ISO처럼 생긴 문자열을 자동으로 바꾸지 않는 이유: 판정 입력에 날짜 모양 텍스트가
# 섞이면 조용히 타입이 뒤바뀐다. 시나리오가 "coerce"로 **지목한 인자만** 바꾼다.
_COERCE = {
    "date": dt.date.fromisoformat,
    "datetime": dt.datetime.fromisoformat,
}


def _call(module: str, func: str, kwargs: dict, coerce: dict = None):
    fn = getattr(importlib.import_module(module), func)
    if coerce:
        kwargs = dict(kwargs)                       # 시나리오 원본을 건드리지 않는다
        for key, kind in coerce.items():
            if kwargs.get(key) is not None:
                kwargs[key] = _COERCE[kind](kwargs[key])
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
        got = _call(scen["module"], scen["func"], case["input"], scen.get("coerce"))
        want = golden.get(case["name"])
        out.append({"name": case["name"], "ok": got == want, "got": got, "want": want})
    return out


def _update_golden(scen_path: str) -> None:
    with open(scen_path, encoding="utf-8") as f:
        scen = json.load(f)
    result = {c["name"]: _call(scen["module"], scen["func"], c["input"],
                               scen.get("coerce"))
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
