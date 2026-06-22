from __future__ import annotations

"""종목 유니버스(검색용): 전체 KRX 종목의 코드·이름·현재가·등락률.

FDR StockListing('KRX')은 간헐적으로 깨진다(설계 §7.3, 오픈 이슈 다수) →
12시간 디스크 캐시 + 실패 시 캐시 폴백으로 상위(대시보드)를 보호한다.
fetch는 주입 가능(테스트용)."""

import datetime as dt
import json
import logging
import os

from backend.config import settings

log = logging.getLogger(__name__)

_CACHE_NAME = "universe.json"
_MAX_AGE = dt.timedelta(hours=12)


def _cache_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, _CACHE_NAME)


def _to_float(v):
    """NaN/None을 None으로, 그 외 float."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN 제거


def _fetch_listing() -> list:
    """FDR StockListing('KRX') → [{code,name,close,change}]."""
    import FinanceDataReader as fdr

    df = fdr.StockListing("KRX")
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("Code") or "").strip()
        name = str(r.get("Name") or "").strip()
        if not code or not name:
            continue
        rows.append({"code": code, "name": name,
                     "close": _to_float(r.get("Close")),
                     "change": _to_float(r.get("ChagesRatio"))})  # FDR 철자: ChagesRatio
    return rows


def get_universe(cache_dir=None, *, force: bool = False, fetch=_fetch_listing) -> list:
    """[{code,name,close,change}] 반환. 신선 캐시 우선 → 수집 → 실패 시 캐시 폴백."""
    cache_dir = cache_dir or settings.cache_dir
    path = _cache_path(cache_dir)

    if not force:
        cached = _read_cache(path, check_age=True)
        if cached is not None:
            return cached

    try:
        uni = fetch()
    except Exception:
        log.warning("StockListing 수집 실패 — 캐시 폴백", exc_info=True)
        return _read_cache(path, check_age=False) or []

    _write_cache(path, cache_dir, uni)
    return uni


def _read_cache(path: str, *, check_age: bool):
    try:
        if check_age:
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(path))
            if dt.datetime.now() - mtime > _MAX_AGE:
                return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else None
    except (OSError, ValueError):
        return None


def _write_cache(path: str, cache_dir: str, uni: list) -> None:
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(uni, f, ensure_ascii=False)
    except OSError:
        log.warning("universe 캐시 기록 실패: %s", cache_dir)


def price_map(universe: list) -> dict:
    """code → {close, change} 빠른 조회용."""
    return {u["code"]: {"close": u.get("close"), "change": u.get("change")}
            for u in universe}
