from __future__ import annotations

from backend.news.match import attach_issues, _title_mentions
from backend.news.models import Disclosure, NewsItem

NAMES = {
    "005930": ["삼성전자"],
    "000660": ["SK하이닉스"],
    "035420": ["NAVER", "네이버"],
    "051910": ["LG화학"],
    "005380": ["현대차", "현대자동차"],
}
CODES = list(NAMES.keys())


def _news(title: str) -> NewsItem:
    return NewsItem(title=title, summary="", link="https://x/" + title, published=None, source="t")


def _disc(stock_code: str, rcept_dt: str, rcept_no: str = "1") -> Disclosure:
    return Disclosure(
        corp_name="회사",
        stock_code=stock_code,
        report_name="보고서",
        rcept_no=rcept_no,
        rcept_dt=rcept_dt,
        link="https://dart/" + rcept_no,
    )


# --------------------------------------------------------------------------
# Disclosure matching (exact, by stock_code)
# --------------------------------------------------------------------------

def test_disclosure_lands_under_its_code_only():
    d = _disc("005930", "20260601")
    out = attach_issues([], [d], CODES, NAMES)
    assert out["005930"]["disclosures"] == [d]
    for code in CODES:
        if code != "005930":
            assert out[code]["disclosures"] == []


def test_disclosure_unknown_stock_code_lands_nowhere():
    d = _disc("999999", "20260601")  # not in CODES
    out = attach_issues([], [d], CODES, NAMES)
    for code in CODES:
        assert out[code]["disclosures"] == []


def test_disclosures_sorted_newest_first_by_rcept_dt():
    old = _disc("005930", "20260101", "old")
    mid = _disc("005930", "20260301", "mid")
    new = _disc("005930", "20260601", "new")
    out = attach_issues([], [old, new, mid], CODES, NAMES)
    assert out["005930"]["disclosures"] == [new, mid, old]


def test_disclosures_capped_at_max_per_stock():
    discs = [_disc("005930", f"202601{day:02d}", str(day)) for day in range(1, 9)]
    out = attach_issues([], discs, CODES, NAMES, max_per_stock=3)
    got = out["005930"]["disclosures"]
    assert len(got) == 3
    # newest three (days 08,07,06)
    assert [d.rcept_dt for d in got] == ["20260108", "20260107", "20260106"]


# --------------------------------------------------------------------------
# News matching — ACCEPT cases
# --------------------------------------------------------------------------

def test_accept_comma_boundary():
    out = attach_issues([_news("삼성전자, 사상 최대 실적")], [], CODES, NAMES)
    assert len(out["005930"]["news"]) == 1


def test_accept_particle_ga():
    out = attach_issues([_news("삼성전자가 보여준 반도체")], [], CODES, NAMES)
    assert len(out["005930"]["news"]) == 1


def test_accept_particle_ui():
    out = attach_issues([_news("현대차의 신차 공개")], [], CODES, NAMES)
    assert len(out["005380"]["news"]) == 1


def test_accept_particle_neun():
    out = attach_issues([_news("현대차는 내년 목표")], [], CODES, NAMES)
    assert len(out["005380"]["news"]) == 1


def test_accept_spaces_around_alias():
    out = attach_issues([_news("오늘 네이버 주가 급등")], [], CODES, NAMES)
    assert len(out["035420"]["news"]) == 1


def test_accept_latin_alias_comma():
    out = attach_issues([_news("NAVER, 신규 서비스")], [], CODES, NAMES)
    assert len(out["035420"]["news"]) == 1


def test_accept_alias_at_end_of_title():
    out = attach_issues([_news("분기 실적 발표한 삼성전자")], [], CODES, NAMES)
    assert len(out["005930"]["news"]) == 1


# --------------------------------------------------------------------------
# News matching — REJECT cases (the substring traps)
# --------------------------------------------------------------------------

def test_reject_hyundai_securities():
    # 증 is not a particle → different company
    out = attach_issues([_news("현대차증권 리포트 발간")], [], CODES, NAMES)
    assert out["005380"]["news"] == []


def test_reject_hyundai_group():
    # 그 is not a particle → group, not the listed firm
    out = attach_issues([_news("현대차그룹 지배구조 개편")], [], CODES, NAMES)
    assert out["005380"]["news"] == []


def test_reject_naver_webtoon():
    # 웹 is not a particle
    out = attach_issues([_news("네이버웹툰 일본 상장")], [], CODES, NAMES)
    assert out["035420"]["news"] == []


def test_reject_naver_financial():
    out = attach_issues([_news("네이버파이낸셜 흑자 전환")], [], CODES, NAMES)
    assert out["035420"]["news"] == []


def test_reject_samsung_electronics_service():
    # 서 is not a particle (에서 begins with 에, not 서)
    out = attach_issues([_news("삼성전자서비스 노조 협상")], [], CODES, NAMES)
    assert out["005930"]["news"] == []


def test_reject_navercloud_latin_boundary():
    out = attach_issues([_news("NAVERCLOUD 신규 리전")], [], CODES, NAMES)
    assert out["035420"]["news"] == []


def test_title_with_no_watchlist_names_matches_nothing():
    out = attach_issues([_news("코스피 코스닥 동반 상승")], [], CODES, NAMES)
    for code in CODES:
        assert out[code]["news"] == []


# --------------------------------------------------------------------------
# Cross-cutting
# --------------------------------------------------------------------------

def test_empty_inputs_yield_full_skeleton():
    out = attach_issues([], [], CODES, NAMES)
    assert set(out.keys()) == set(CODES)
    for code in CODES:
        assert out[code] == {"news": [], "disclosures": []}


def test_news_matching_two_codes_appears_under_both():
    item = _news("삼성전자와 현대차, 전기차 협력")
    out = attach_issues([item], [], CODES, NAMES)
    assert out["005930"]["news"] == [item]
    assert out["005380"]["news"] == [item]


def test_news_preserves_input_order():
    a = _news("삼성전자, 첫 소식")
    b = _news("삼성전자가 두 번째")
    out = attach_issues([a, b], [], CODES, NAMES)
    assert out["005930"]["news"] == [a, b]


def test_news_capped_at_max_per_stock():
    items = [_news(f"삼성전자, 소식 {n}") for n in range(7)]
    out = attach_issues(items, [], CODES, NAMES, max_per_stock=4)
    assert len(out["005930"]["news"]) == 4
    assert out["005930"]["news"] == items[:4]  # input order preserved, first 4


def test_alias_via_second_occurrence_after_rejected_first():
    # first occurrence is a compound (rejected), second is standalone at end
    out = attach_issues([_news("네이버웹툰과 네이버")], [], CODES, NAMES)
    assert len(out["035420"]["news"]) == 1


# --------------------------------------------------------------------------
# Helper-level unit tests (boundary rule, directly)
# --------------------------------------------------------------------------

def test_helper_latin_case_insensitive():
    assert _title_mentions("naver, 소식", ["NAVER"]) is True


def test_helper_latin_word_boundary_before():
    assert _title_mentions("CLOUDNAVER 출시", ["NAVER"]) is False


def test_helper_hangul_before_boundary_rejected():
    # alias sitting mid-word (Hangul before) must be rejected
    assert _title_mentions("한국삼성전자 발표", ["삼성전자"]) is False


def test_helper_alias_with_for_particle_euro():
    # 으로 (longer particle) clean boundary
    assert _title_mentions("삼성전자으로 추정", ["삼성전자"]) is True


def test_helper_eseo_particle_not_seo_compound():
    # 에서 is a particle; ensure 삼성전자에서 accepts via 에서
    assert _title_mentions("삼성전자에서 발표", ["삼성전자"]) is True
