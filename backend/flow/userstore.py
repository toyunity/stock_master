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


def market_of(code):
    """티커 문자열의 시장 분류 — 'KR'(6자리 숫자) | 'US'(대문자 티커) | None(무효).
    _clean_item과 동일 규칙·정규식을 재사용(대문자화)해 라우트 존재확인 등에서 규칙이 갈리지 않게 한다."""
    c = str(code or "").strip().upper()
    if _KR_RE.match(c):
        return "KR"
    if _US_RE.match(c):
        return "US"
    return None


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


def get_lines(email, code) -> list:
    """코드의 감시선 목록(계정별). 파일에 코드 키가 있으면 파일값(빈 배열=전부 지운 상태 영속),
    없으면 마스터 계정만 config 시드. 비마스터는 폴백 금지(마스터 실매도가 유출 방지)."""
    from backend.flow import watch
    email = norm_email(email)
    d = _load(email)
    lines = (d.get("watch_lines") or {}).get(code)
    if isinstance(lines, list):
        return watch._clean(lines)
    if email == default_account():
        return watch._clean(settings.watch_lines.get(code) or [])   # 마스터만 config 시드
    return []                                                        # 비마스터: 폴백 금지


def set_lines(email, code, lines) -> list:
    """검증 후 계정 파일에 원자적 저장. 위반 시 ValueError. 빈 배열도 영속."""
    from backend.flow import watch
    norm = watch._validate_lines(lines)
    d = _load(norm_email(email))
    wl = d.get("watch_lines")
    if not isinstance(wl, dict):
        wl = {}
    wl[code] = norm
    d["watch_lines"] = wl
    _save(email, d)
    return norm


# 위젯 토큰 — 단일 진실원 = 유저 파일의 widget_token. 별도 인덱스 파일 없음.
# email_for_token은 users/ 디렉터리를 스캔해 역매핑을 만들고 디렉터리 mtime이
# 변할 때만 재빌드(3계정=3파일). 쓰기 함수는 _save 직후 mtime 캐시를 무효화해
# 동일-초 회전에도 구 토큰이 즉시 사망하도록 보장한다.
_tok_cache = {"mtime": None, "map": {}}


def get_token(email):
    return _load(norm_email(email)).get("widget_token")


def ensure_token(email) -> str:
    email = norm_email(email)
    d = _load(email)
    if not d.get("widget_token"):
        d["widget_token"] = secrets.token_urlsafe(32)
        _save(email, d)
        _tok_cache["mtime"] = None
    return d["widget_token"]


def rotate_token(email) -> str:
    email = norm_email(email)
    d = _load(email)
    d["widget_token"] = secrets.token_urlsafe(32)
    _save(email, d)
    _tok_cache["mtime"] = None
    return d["widget_token"]


def register_env_token(token, email) -> None:
    """마이그레이션 전용 — env SM_WIDGET_TOKEN을 고정 마스터 유저파일에 1회 등록."""
    email = norm_email(email)
    d = _load(email)
    if not d.get("widget_token"):
        d["widget_token"] = token
        _save(email, d)
        _tok_cache["mtime"] = None


def _rebuild_token_map():
    d = _dir()
    try:
        mtime = os.path.getmtime(d)
    except OSError:
        mtime = None
    if mtime != _tok_cache["mtime"]:
        m = {}
        try:
            for f in os.listdir(d):
                if f.endswith(".json"):
                    try:
                        with open(d / f, encoding="utf-8") as fh:
                            j = json.load(fh)
                        tok = j.get("widget_token")
                        if tok:
                            m[tok] = norm_email(j.get("email"))
                    except Exception:
                        continue
        except OSError:
            pass
        _tok_cache["mtime"], _tok_cache["map"] = mtime, m
    return _tok_cache["map"]


def email_for_token(token):
    if not token:
        return None
    return _rebuild_token_map().get(token)


def migrate_globals() -> None:
    """전역 저장물을 마스터 계정 파일로 1회 승격(이미 있으면 건너뜀). 앱 시작 시 호출.
    전역 watchlist.json({"codes":[...]})·watch_lines.json·env 위젯토큰을 마스터 파일로."""
    master = default_account()
    if not master:
        return
    d = _load(master)
    changed = False
    if "watchlist" not in d:
        try:
            with open(Path(settings.cache_dir) / "watchlist.json", encoding="utf-8") as f:
                codes = (json.load(f) or {}).get("codes") or []
            if codes:
                d["watchlist"] = [{"code": c, "market": "KR", "shares": None, "avg": None}
                                  for c in codes if _KR_RE.match(str(c))]
                changed = True
        except Exception:
            pass
    if "watch_lines" not in d:
        try:
            with open(Path(settings.cache_dir) / "watch_lines.json", encoding="utf-8") as f:
                wl = json.load(f)
            if isinstance(wl, dict):
                d["watch_lines"] = wl
                changed = True
        except Exception:
            pass
    if settings.widget_token and not d.get("widget_token"):
        d["widget_token"] = settings.widget_token
        changed = True
    if changed:
        _save(master, d)
        _tok_cache["mtime"] = None
