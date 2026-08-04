from __future__ import annotations

"""KRX+NXT 통합(UN/NX) 세션 시간표 — 단일 정의 소스(single source of truth).

market_div이 UN(통합)/NX(NXT)면 프리 08:00 ~ 애프터 20:00까지 NXT 거래 시간을 포함,
J(KRX만)면 정규장 09:00~15:30만. 자정 기준 분(minutes-since-midnight)의
half-open [start,end) 구간으로 표현 — 09:00=540, 15:30=930, 08:00=480, 20:00=1200.

candles._session_window()(KIS 분봉 조회용 문자열)와 cli._kr_market_open()/
report.dashboard.marketPulse()(대시보드 헤더 펄스)가 모두 이 정의를 따른다 —
09:00~15:30 하드코딩을 여러 곳에 중복하지 않기 위한 공유 헬퍼.
공휴일은 모른다(호출부 책임 — flow.market_status가 그 계층을 담당).
"""

_REGULAR = (9 * 60, 15 * 60 + 30)   # 540, 930 — KRX 정규장
_EXTENDED = (8 * 60, 20 * 60)        # 480, 1200 — 프리+정규+애프터(NXT 포함)


def session_minutes(market_div: str) -> tuple:
    """(시작분, 마감분) — 자정 기준, half-open [start,end). UN/NX면 NXT 확장 시간 포함."""
    if market_div in ("UN", "NX"):
        return _EXTENDED
    return _REGULAR


def is_session_open(now, market_div: str) -> bool:
    """주말 제외 + 세션 창(half-open [start,end)) 내부 여부. 공휴일은 모른다."""
    if now.weekday() >= 5:
        return False
    start, end = session_minutes(market_div)
    hm = now.hour * 60 + now.minute
    return start <= hm < end
