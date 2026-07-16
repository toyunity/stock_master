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

_CACHE_NAME = "universe_v2.json"  # ETF 포함 버전(기존 캐시 무효화)
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


def _row(r):
    """FDR 한 행 → {code,name,close,change}. 주식/ETF 목록의 상이한 컬럼명을 흡수.

    주식(KRX): Code, Name, Close, ChagesRatio(철자 오타) /
    ETF(ETF/KR): Symbol, Name, Price, ChangeRate."""
    code = str(r.get("Code") or r.get("Symbol") or "").strip()
    name = str(r.get("Name") or "").strip()
    if not code or not name:
        return None
    close = None
    for k in ("Close", "Price"):
        if close is None:
            close = _to_float(r.get(k))
    change = None
    for k in ("ChagesRatio", "ChangeRate", "ChangeRatio", "Changes"):
        if change is None:
            change = _to_float(r.get(k))
    return {"code": code, "name": name, "close": close, "change": change}


def _fetch_listing() -> list:
    """FDR 주식(KRX) + ETF(ETF/KR)를 합쳐 [{code,name,close,change}].

    한쪽 수집이 실패해도 다른 쪽은 살린다. 주식이 먼저라 코드 중복 시 주식이 우선."""
    import FinanceDataReader as fdr

    rows, seen = [], set()
    for market in ("KRX", "ETF/KR"):
        try:
            df = fdr.StockListing(market)
        except Exception:
            log.warning("StockListing(%s) 수집 실패", market, exc_info=True)
            continue
        for _, r in df.iterrows():
            row = _row(r)
            if row and row["code"] not in seen:
                seen.add(row["code"])
                rows.append(row)
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


def get_cached(cache_dir=None) -> list:
    """캐시 파일만 읽는다(나이 무시·수집 트리거 없음) — 위젯 폴백/이름 조회 전용.

    위젯 요청은 어떤 경우에도 FDR 동기 스크랩을 대기하지 않는다(설계 불변식:
    수 초짜리 수집이 iOS 위젯 시간예산을 태우고 sync 함수가 이벤트루프를 멈춤)."""
    cache_dir = cache_dir or settings.cache_dir
    return _read_cache(_cache_path(cache_dir), check_age=False) or []


def price_map(universe: list) -> dict:
    """code → {close, change} 빠른 조회용."""
    return {u["code"]: {"close": u.get("close"), "change": u.get("change")}
            for u in universe}
