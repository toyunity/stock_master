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


def scorecard(frames: dict, today=None, window_days: int = 60):
    """홈 렌더용 — 장부를 읽어 frames(code→Close 열·DatetimeIndex DataFrame)로 채점. 장부가 비면 None."""
    entries = load()
    if not entries:
        return None
    closes = {}
    for code, df in frames.items():
        if df is None or len(df) == 0 or "Close" not in df:
            continue
        closes[code] = [(ts.date().isoformat(), float(c)) for ts, c in df["Close"].items() if c == c]
    return score(entries, closes, today or kst.today(), window_days)


HOLD_BARS = 10      # signal 채점 기간(봉) — backtest.py의 hold_days=10과 같은 잣대
MIN_SAMPLE = 10     # 이 미만이면 비율 대신 "표본 부족 (n/10)" (표시용, dashboard.py가 참조)
_UP = {"up": 1, "buy": 1, "down": -1, "sell": -1}   # 적중 방향. neutral/hold/그 외는 skip


def _bucket() -> dict:
    return {"n": 0, "hit": 0, "skip": 0, "pending": 0}


def score(entries: dict, closes: dict, today: dt.date, window_days: int = 60) -> dict:
    """순수 채점. closes[code] = [(date_iso, close), ...] 오름차순.

    창: 모든 봉 날짜 합집합의 뒤에서 window_days번째 날짜 이후 키만(봉이 모자라면 첫 봉,
    봉이 전혀 없으면 today-90일). outlook은 목표일 T 이상 첫 봉, signal은 D 이후 10번째 봉 —
    D 봉 자체는 기록 시점에 부분봉이라 제외(2026-11-02 실측: 일봉 캐시는 첫 로드의 부분봉을
    하루 종일 서빙). 둘 다 **그 다음 봉이 있어야 확정**(FDR 마지막 봉은 진행 중 값), 없으면 pending.
    """
    all_dates = sorted({d for bars in closes.values() for d, _ in bars})
    if all_dates:
        cutoff = all_dates[-window_days] if len(all_dates) >= window_days else all_dates[0]
    else:
        cutoff = (today - dt.timedelta(days=90)).isoformat()
    total = {"outlook": _bucket(), "signal": _bucket()}
    by_code: dict = {}
    for key, e in entries.items():
        try:
            kind, code, date = key.split(":", 2)
        except ValueError:
            continue
        if kind not in total or date < cutoff:
            continue
        b = by_code.setdefault(code, {"outlook": _bucket(), "signal": _bucket()})[kind]
        t = total[kind]
        sign = _UP.get(e.get("dir"))
        if sign is None:
            b["skip"] += 1
            t["skip"] += 1
            continue
        bars = closes.get(code) or []
        if kind == "outlook":
            i = next((k for k, (d, _) in enumerate(bars) if d >= date), None)
        else:
            j = next((k for k, (d, _) in enumerate(bars) if d > date), None)
            i = None if j is None else j + HOLD_BARS - 1
        if i is None or i + 1 >= len(bars):
            b["pending"] += 1
            t["pending"] += 1
            continue
        ret = bars[i][1] / float(e["px"]) - 1
        hit = 1 if ret * sign > 0 else 0        # ret == 0은 miss
        b["n"] += 1
        b["hit"] += hit
        t["n"] += 1
        t["hit"] += hit
    return {"outlook": total["outlook"], "signal": total["signal"], "by_code": by_code}
