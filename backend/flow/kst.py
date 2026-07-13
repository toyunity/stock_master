from __future__ import annotations

"""Asia/Seoul 고정 시계 — 표시 시각은 전부 거래소 타임존(KST) 기준.

서버가 어느 타임존/어느 클라이언트에서 돌아도 화면 시각이 흔들리지 않도록
naive `datetime.now()`/`date.today()` 대신 이 모듈을 쓴다(P0-3 타임스탬프 통일).
"""

import datetime as dt
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now() -> dt.datetime:
    return dt.datetime.now(KST)


def today() -> dt.date:
    return now().date()
