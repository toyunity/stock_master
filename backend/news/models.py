from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class NewsItem:
    """언론사 RSS 1건. 저작권 보호를 위해 제목/요약/링크/시각/출처만 보관하고
    원문은 link로 딥링크한다(본문 미저장)."""

    title: str
    summary: str
    link: str
    published: dt.datetime | None  # 파싱 실패 시 None
    source: str  # 예: "한국경제", "연합뉴스"


@dataclass(frozen=True)
class Disclosure:
    """DART 공시 1건. stock_code로 종목과 정확 매칭한다."""

    corp_name: str
    stock_code: str  # 6자리, 비상장/매칭불가 시 빈 문자열
    report_name: str
    rcept_no: str  # 접수번호(원문 링크 키)
    rcept_dt: str  # YYYYMMDD
    link: str  # https://dart.fss.or.kr/dsaf001/main.do?rcpNo=...
