from __future__ import annotations

"""관심종목 서버 저장 — 단일 진실 원천(설계 2026-07-16).

저장 파일: <cache_dir>/watchlist.json = {"codes": ["005930", ...]}.
소비자 5곳(대시보드·/api/prices·/api/widget·CLI report·MCP tools)은 전부
get_watchlist()를 경유한다 — settings.watchlist 직접 참조 금지(시드 전용 격하).
감시선(watch.py)과 동일 패턴: 원자적 쓰기 + 모듈 Lock, 부재/손상 시 시드 폴백.
순서 = 저장 순서 = 표시 순서(새 종목은 UI가 맨 앞에 넣는다). Python 3.9 호환."""

import json
import os
import re
import threading
from pathlib import Path

from backend.config import settings

_LOCK = threading.Lock()
_CODE_RE = re.compile(r"^\d{6}$")
MAX_CODES = 10   # 대시보드 렌더·KIS 동시 호출·위젯 공간 모두 커버(설계)


def _path() -> Path:
    return Path(settings.cache_dir) / "watchlist.json"


def get_watchlist() -> list:
    """현재 관심종목 코드 목록 — 파일값 우선, 부재/손상/무효면 config 시드."""
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        codes = d.get("codes") if isinstance(d, dict) else None
        if isinstance(codes, list):
            valid = [c for c in codes if isinstance(c, str) and _CODE_RE.match(c)]
            if valid:
                return valid
    except Exception:
        pass
    return list(settings.watchlist)


def set_watchlist(codes) -> list:
    """검증 후 원자적 저장. 위반 시 ValueError(사용자 노출 메시지). 저장 목록 반환."""
    if not isinstance(codes, list):
        raise ValueError("종목 코드 목록(배열)이 필요해요")
    norm, seen = [], set()
    for c in codes:
        c = str(c).strip()
        if not _CODE_RE.match(c):
            raise ValueError("종목 코드는 6자리 숫자여야 해요: %s" % c)
        if c not in seen:
            seen.add(c)
            norm.append(c)
    if not norm:
        raise ValueError("관심종목은 최소 1개 필요해요")
    if len(norm) > MAX_CODES:
        raise ValueError("관심종목은 최대 %d개까지 저장할 수 있어요" % MAX_CODES)
    with _LOCK:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"codes": norm}, f, ensure_ascii=False)
        os.replace(tmp, p)   # 원자적 교체 — 부분쓰기 방지
    return norm
