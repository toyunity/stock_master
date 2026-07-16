from __future__ import annotations

# 관심종목 코드 → RSS 본문에서 찾을 회사명(별칭 포함).
# ⚠️ 부분문자열 오매칭 주의: 여기 이름들은 다른 회사명의 접두가 되기 쉽다
#   (삼성전자 ⊂ 삼성전자우 / 삼성SDI·삼성바이오는 별개,
#    현대차 ⊂ 현대차증권 / 현대모비스는 별개,
#    SK하이닉스 ⊂ SK스퀘어는 별개, LG화학 ⊂ LG에너지솔루션은 별개).
# → match.py가 '경계 인식' 매칭으로 이 별칭이 더 긴 회사명의 일부일 때를 배제한다.
STOCK_NAMES: dict[str, list[str]] = {
    "005930": ["삼성전자"],
    "000660": ["SK하이닉스"],
    "035420": ["NAVER", "네이버"],
    "051910": ["LG화학"],
    "005380": ["현대차", "현대자동차"],
}

# 리포트 표시용 대표 종목명(관심종목 외 코드는 코드 그대로).
# 관심종목이 늘면 여기에 추가. (S4 스캐너 단계에서 FDR 종목명으로 일반화 예정.)
_DISPLAY_NAMES: dict[str, str] = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "네이버",
    "051910": "LG화학",
    "005380": "현대차",
}


def display_name(code: str) -> str:
    """리포트에 보여줄 한글 종목명. 모르는 코드는 코드 그대로 반환."""
    return _DISPLAY_NAMES.get(code, code)


def resolve_name(code: str, names=None) -> str:
    """표시 이름 — universe 이름(names dict) 우선, 하드코딩 폴백, 모르면 코드.

    신규 관심종목이 '035720' 숫자로 표시되는 문제의 해소(설계 2026-07-16).
    names는 universe.name_map() 결과를 호출부가 주입(이 모듈은 I/O 없음 유지)."""
    if names:
        n = names.get(code)
        if n:
            return n
    return display_name(code)
