from __future__ import annotations

"""판정 장부 — 앱이 내보낸 '내일 예상'(outlook)과 '매매 판정'(signal)을 적어두고 채점한다.

- 마스터가 **실제로 본** 판단만 기록한다(라우트가 마스터 계정일 때만 ledger=True를 넘긴다).
  앱을 안 연 날은 기록이 없고, 그게 맞다 — 보지 않은 예측을 채점할 이유가 없다.
- 채점은 읽을 때 한다(홈 렌더의 일봉 frames로 그 자리에서). 결과를 채우는 두 번째 배치는 없다.
- 데모 모드(settings.flow_mode == "demo")에선 쓰지 않는다 — 하네스 데모 서버가 실계정 data/를
  읽으므로 가짜 판정이 진짜 장부에 섞인다. 읽기(채점·표시)는 허용.
설계: docs/superpowers/specs/2026-11-02-verdict-ledger-design.md (2026-11-02).
저장 파일: <cache_dir>/verdicts.json = {"kind:code:date": {"dir", "px", "at", ...}}. 마지막 기록이 이긴다.
"""

import datetime as dt
import json
import os
import threading
from pathlib import Path

from backend.config import settings
from backend.flow import kst
from backend.flow.watch import _finite_pos

_LOCK = threading.Lock()
KEEP_DAYS = 400     # 저장 보존 기간(달력일). 표시 창(60거래일)보다 넉넉히.


def _path() -> Path:
    return Path(settings.cache_dir) / "verdicts.json"


def load() -> dict:
    """장부 전체 dict. 부재/손상 시 빈 dict — 장부 때문에 홈이 죽으면 안 된다."""
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def record(kind: str, code: str, date: str, direction: str, px, **extra) -> bool:
    """`kind:code:date` 키로 upsert. 저장했으면 True.

    px가 유한 양수가 아니면 기록하지 않는다(채점 불가한 기록은 소음).
    쓰기마다 KEEP_DAYS 넘은 키를 버린다(키 끝의 날짜 기준, 정렬 없이 한 번 훑음).
    """
    if settings.flow_mode == "demo" or not _finite_pos(px):
        return False
    cutoff = (kst.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    entry = {"dir": direction, "px": px, "at": kst.now().isoformat(timespec="seconds")}
    entry.update(extra)
    with _LOCK:
        d = load()
        d["%s:%s:%s" % (kind, code, date)] = entry
        d = {k: v for k, v in d.items() if k.rsplit(":", 1)[-1] >= cutoff}
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, p)
    return True
