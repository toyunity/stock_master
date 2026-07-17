from __future__ import annotations

"""감시선(차트 수평 참조선: 절대선·예약매도선·손절선 등) 서버 저장.

한 기기(아이폰 PWA)에서 바꾼 선을 다른 기기(맥)에서도 보게 서버 파일에 영속한다.
저장 파일: <cache_dir>/watch_lines.json = {"000660":[{"price":int,"label":str}, ...]}.
1인용이라 인증/동시성 대신 원자적 쓰기(temp+os.replace)+모듈 Lock으로 부분쓰기만 방지.
실주문 기능은 없다 — 순수 참조선(라벨+가격) 표시·알림용. Python 3.9 호환(실서버 시스템 3.9).
"""

import json
import os
import threading
from pathlib import Path

from backend.config import settings

_LOCK = threading.Lock()
MAX_LINES = 10      # 종목당 감시선 상한
MAX_LABEL = 20      # 라벨 길이 상한


def _path() -> Path:
    return Path(settings.cache_dir) / "watch_lines.json"


def _load_all() -> dict:
    """저장 파일 전체 dict. 부재/손상 시 빈 dict(폴백은 호출부에서 config로)."""
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def _finite_pos(price) -> bool:
    try:
        price = float(price)
    except (TypeError, ValueError):
        return False
    if price != price:                     # NaN
        return False
    if price in (float("inf"), float("-inf")):
        return False
    return price > 0


def _clean(lines) -> list:
    """반환용 정규화 — 무효 줄은 조용히 버림(파일/config 폴백값 방어)."""
    out = []
    for item in (lines or []):
        if not isinstance(item, dict) or not _finite_pos(item.get("price")):
            continue
        label = ("" if item.get("label") is None else str(item.get("label"))).strip()
        if 1 <= len(label) <= MAX_LABEL:
            out.append({"price": int(round(float(item["price"]))), "label": label})
    return out


def get_lines(code: str) -> list:
    """코드의 감시선 목록. 파일에 코드 키가 있으면 파일값(빈 배열 포함=전부 지운 상태 영속),
    없으면 config(settings.watch_lines) 기본값으로 폴백. 항상 정규화된 리스트."""
    d = _load_all()
    if code in d and isinstance(d[code], list):
        return _clean(d[code])
    return _clean(settings.watch_lines.get(code) or [])


def _validate_lines(lines) -> list:
    """감시선 검증·정규화(저장 무관). 위반 시 ValueError(사용자 노출 메시지).
    계정별 저장(userstore)과 전역 저장(set_lines)이 동일 규칙을 공유한다."""
    if not isinstance(lines, list):
        raise ValueError("감시선 목록(배열)이 필요해요")
    if len(lines) > MAX_LINES:
        raise ValueError("감시선은 최대 %d개까지 저장할 수 있어요" % MAX_LINES)
    norm = []
    for i, item in enumerate(lines):
        n = i + 1
        if not isinstance(item, dict):
            raise ValueError("%d번째 줄 형식이 올바르지 않아요" % n)
        if not _finite_pos(item.get("price")):
            raise ValueError("%d번째 줄: 가격은 0보다 큰 숫자여야 해요" % n)
        label = ("" if item.get("label") is None else str(item.get("label"))).strip()
        if not (1 <= len(label) <= MAX_LABEL):
            raise ValueError("%d번째 줄: 라벨은 1~%d자여야 해요" % (n, MAX_LABEL))
        norm.append({"price": int(round(float(item["price"]))), "label": label})
    return norm


def set_lines(code: str, lines) -> list:
    """검증 후 원자적 저장. 위반 시 ValueError(사용자 노출 메시지). 정규화 리스트 반환.
    빈 리스트도 영속(사용자가 전부 지운 상태 유지)."""
    norm = _validate_lines(lines)
    with _LOCK:
        d = _load_all()
        d[code] = norm
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, p)               # 원자적 교체 — 부분쓰기 방지
    return norm
