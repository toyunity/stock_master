from __future__ import annotations

"""계정별 저장소 — 로그인 이메일 기준으로 관심종목·보유·감시선·위젯토큰 격리.
저장: <cache_dir>/users/<uid>.json. 감시선 검증은 watch.py 재사용. 설계 2026-07-17."""

import hashlib
import json
import os
import re
import secrets
import threading
from pathlib import Path

from backend.config import settings

_LOCK = threading.Lock()
_KR_RE = re.compile(r"^\d{6}$")
_US_RE = re.compile(r"^[A-Z]{1,5}([.][A-Z])?$")
MAX_ITEMS = 10


def norm_email(e) -> str:
    return str(e or "").strip().lower()


def _uid(email) -> str:
    return hashlib.sha256(norm_email(email).encode("utf-8")).hexdigest()[:16]


def _dir() -> Path:
    return Path(settings.cache_dir) / "users"


def _path(email) -> Path:
    return _dir() / (_uid(email) + ".json")


def default_account() -> str:
    if settings.default_account:
        return norm_email(settings.default_account)
    emails = [e.strip() for e in (settings.allowed_emails or "").split(",") if e.strip()]
    return norm_email(emails[0]) if emails else ""


def _load(email) -> dict:
    try:
        with open(_path(email), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(email, data) -> None:
    with _LOCK:
        p = _path(email)
        p.parent.mkdir(parents=True, exist_ok=True)
        data["email"] = norm_email(email)
        tmp = p.with_name(p.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)


def _clean_item(it) -> dict:
    """검증·정규화된 watchlist 항목(무효는 ValueError)."""
    if not isinstance(it, dict):
        raise ValueError("종목 항목 형식이 올바르지 않아요")
    code = str(it.get("code", "")).strip().upper()
    if _KR_RE.match(code):
        market = "KR"
    elif _US_RE.match(code):
        market = "US"
    else:
        raise ValueError("종목 코드는 6자리 숫자(국내) 또는 티커(미국)여야 해요: %s" % code)
    shares = it.get("shares")
    if shares is not None:
        shares = int(shares)
        if shares < 0:
            raise ValueError("보유 수량은 0 이상이어야 해요")
    avg = it.get("avg")
    if avg is not None:
        avg = float(avg)
        if avg <= 0:
            raise ValueError("평균매입가는 0보다 커야 해요")
        if market == "KR":
            avg = int(round(avg))          # 국내는 원 정수
    return {"code": code, "market": market, "shares": shares, "avg": avg}


def get_watchlist(email) -> list:
    email = norm_email(email)
    d = _load(email)
    items = d.get("watchlist")
    if isinstance(items, list):
        out = []
        for it in items:
            try:
                out.append(_clean_item(it))
            except ValueError:
                continue
        return out
    # 파일 없음: 마스터만 config 시드, 그 외 빈
    if email == default_account():
        return [{"code": c, "market": "KR", "shares": None, "avg": None}
                for c in settings.watchlist]
    return []


def set_watchlist(email, items) -> list:
    if not isinstance(items, list):
        raise ValueError("종목 목록(배열)이 필요해요")
    norm, seen = [], set()
    for it in items:
        c = _clean_item(it)
        key = (c["code"], c["market"])
        if key not in seen:
            seen.add(key)
            norm.append(c)
    if not norm:
        raise ValueError("관심종목은 최소 1개 필요해요")
    if len(norm) > MAX_ITEMS:
        raise ValueError("관심종목은 최대 %d개까지 저장할 수 있어요" % MAX_ITEMS)
    d = _load(norm_email(email))
    d["watchlist"] = norm
    _save(email, d)
    return norm


def get_kr_codes(email) -> list:
    return [i["code"] for i in get_watchlist(email) if i["market"] == "KR"]
