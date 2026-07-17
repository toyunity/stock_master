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
