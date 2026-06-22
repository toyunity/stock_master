from __future__ import annotations

"""관심종목 ↔ 뉴스/공시 매칭.

정밀도 우선 원칙: 잘못된 회사에 헤드라인을 붙이는 것보다 놓치는 편이 안전하다.
한국어 회사명은 더 긴 회사명의 접두어가 되기 쉬우므로(삼성전자 ⊂ 삼성전자서비스,
현대차 ⊂ 현대차증권) '경계 인식' 매칭으로 별칭이 독립된 회사 지칭일 때만 매칭한다.

이 모듈은 호재/악재 등 감성 태깅을 하지 않으며(이 슬라이스 범위 밖), 네트워킹도 없다.
입력 객체에 대한 순수 함수.
"""

# 조사(particle) 시작 후보. 별칭 바로 뒤에 한글이 오더라도 이 중 하나로 시작하면
# 독립된 명사+조사로 보고 허용한다. 길이 내림차순 정렬로 longest-first 매칭
# (예: '으로'가 '로'보다, '이라는'이 '라'보다 먼저). 누락된 희귀 조사는 안전한 미스만 유발.
_PARTICLES = (
    "는 은 이 가 을 를 의 에 와 과 도 만 로 으로 에서 에게 한테 께 부터 까지 보다 "
    "처럼 같이 마저 조차 나 이나 란 이란 라 이라 라고 이라고 라는 이라는 며 이며 "
    "고 이고 인 밖에 뿐 대로"
).split()
_PARTICLE_PREFIXES = tuple(sorted(_PARTICLES, key=len, reverse=True))


def _is_hangul(ch: str) -> bool:
    """한글 음절(가~힣) 여부. (한글 자모/호환 영역은 회사명에 안 나오므로 음절만 본다.)"""
    return "가" <= ch <= "힣"


def _is_ascii_alnum(ch: str) -> bool:
    """ASCII 영숫자 여부. 주의: 한글도 str.isalnum()은 True이므로 isascii 동반 필수."""
    return ch.isascii() and ch.isalnum()


def _clean_before(title: str, start: int) -> bool:
    """별칭 앞 경계가 깨끗한가. 문자열 시작이거나, 앞 글자가 한글도 ASCII영숫자도 아님."""
    if start == 0:
        return True
    prev = title[start - 1]
    return not _is_hangul(prev) and not _is_ascii_alnum(prev)


def _clean_after(title: str, alias: str, end: int) -> bool:
    """별칭 뒤 경계가 깨끗한가.

    1) 문자열 끝 → 깨끗
    2) 별칭 마지막 글자가 ASCII영숫자이고 다음 글자도 ASCII영숫자 → 거부
       (라틴 단어 경계: NAVER ⊂ NAVERCLOUD 거부)
    3) 다음 글자가 한글 → 조사 시작이면 허용, 아니면 거부(복합어 충돌)
    4) 그 외(공백/문장부호/숫자 등) → 깨끗
    """
    if end >= len(title):
        return True
    nxt = title[end]
    if _is_ascii_alnum(alias[-1]) and _is_ascii_alnum(nxt):
        return False
    if _is_hangul(nxt):
        return title[end:].startswith(_PARTICLE_PREFIXES)
    return True


def _alias_mentioned(title: str, alias: str) -> bool:
    """단일 별칭이 title 안에 독립 회사 지칭으로 등장하는가.

    모든 등장 위치를 검사한다(앞쪽 등장이 복합어라 거부돼도 뒤쪽 독립 등장은 허용).
    라틴 별칭은 대소문자 무시.
    """
    if not alias:
        return False
    hay = title.casefold()
    needle = alias.casefold()
    pos = hay.find(needle)
    while pos != -1:
        end = pos + len(needle)
        # 경계 검사는 원본/별칭 기준(casefold가 길이를 바꾸지 않는 ASCII/한글에 안전).
        if _clean_before(title, pos) and _clean_after(title, alias, end):
            return True
        pos = hay.find(needle, pos + 1)
    return False


def _title_mentions(title: str, aliases: list[str]) -> bool:
    """별칭 중 하나라도 title에 독립 회사 지칭으로 등장하면 True. (독립 테스트용)"""
    return any(_alias_mentioned(title, alias) for alias in aliases)


def attach_issues(news, disclosures, codes, names, *, max_per_stock=5) -> dict:
    """관심종목 코드별로 매칭된 뉴스/공시를 묶어 반환한다.

    반환: {code: {"news": [NewsItem, ...], "disclosures": [Disclosure, ...]}}
      - 모든 code가 키로 존재(매칭 없으면 빈 리스트).
      - 공시: stock_code 정확 일치, rcept_dt(YYYYMMDD) 내림차순, max_per_stock 캡.
      - 뉴스: title만 경계 인식 매칭, 입력 순서(최신순) 보존, max_per_stock 캡.
        한 뉴스가 여러 code에 매칭될 수 있다(각 code에 추가).
    """
    result: dict = {code: {"news": [], "disclosures": []} for code in codes}

    # 공시: stock_code 정확 매칭 → 코드별 모음
    by_code_disc: dict = {code: [] for code in codes}
    for d in disclosures:
        if d.stock_code in by_code_disc:
            by_code_disc[d.stock_code].append(d)
    for code in codes:
        ordered = sorted(by_code_disc[code], key=lambda d: d.rcept_dt, reverse=True)
        result[code]["disclosures"] = ordered[:max_per_stock]

    # 뉴스: 입력 순서 보존하며 코드별 매칭, 캡 도달 시 더 추가 안 함
    for item in news:
        title = item.title or ""
        for code in codes:
            bucket = result[code]["news"]
            if len(bucket) >= max_per_stock:
                continue
            if _title_mentions(title, names.get(code, [])):
                bucket.append(item)

    return result
