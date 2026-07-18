from backend.education import glossary as g

def test_glossary_has_core_terms():
    keys = {t.key for t in g.all_terms()}
    for k in ["골든크로스", "RSI", "손절", "백테스트", "거래량", "분산투자"]:
        assert k in keys

def test_get_returns_term_with_short_and_long():
    t = g.get("골든크로스")
    assert t is not None
    assert len(t.short) > 0
    assert len(t.long) > 20  # 공부용 자세한 설명

def test_get_unknown_returns_none():
    assert g.get("없는용어") is None

def test_terms_in_finds_terms_in_golden_cross_reason():
    found = g.terms_in("20일선이 60일선을 상향 돌파(골든크로스)")
    keys = {t.key for t in found}
    assert "골든크로스" in keys
    assert "이동평균" in keys   # via alias 20일선/60일선

def test_terms_in_matches_rsi_reason():
    found = g.terms_in("RSI 74 (과매수 — 과열 주의)")
    keys = {t.key for t in found}
    assert "RSI" in keys
    assert "과매수" in keys

def test_terms_in_excludes_substring_false_positive():
    keys = {t.key for t in g.terms_in("RSI 74 (과매수 — 과열 주의)")}
    assert "과매수" in keys
    assert "RSI" in keys
    assert "매수" not in keys   # 과매수의 부분문자열이라 제외돼야 함


# ── 값 인식형 쉬운말 리더 (내일예상 고도화, 2026-07-18) ──
from backend.education.glossary import (
    read_per, read_pbr, read_w52_pos, read_roe, read_debt, read_bid_ratio, read_flow)


def test_read_per_bands():
    assert read_per(None) is None
    assert "적자" in read_per(0)                 # <=0
    assert "싼 편" in read_per(8)
    assert "보통" in read_per(15)
    assert "비싼 편" in read_per(31)
    assert "매우 비쌈" in read_per(80)


def test_read_w52_debt_flow():
    assert "고점 부근" in read_w52_pos(85)
    assert "저점 부근" in read_w52_pos(12)
    assert "적은 편" in read_debt(36)            # 안정
    assert "많은 편" in read_debt(180)
    assert read_flow(None, None) is None
    assert "쌍끌이" in read_flow(1000, 2000)
    assert "동반 순매도" in read_flow(-500, -300)
    assert "혼조" in read_flow(1000, -300)


def test_read_roe_pbr_bidratio():
    assert "잘 버는" in read_roe(61)
    assert "약한" in read_roe(2)
    assert read_pbr(0) is None
    assert "순자산보다 싸게" in read_pbr(0.8)
    assert "사자" in read_bid_ratio(60) and "팔자" in read_bid_ratio(40)
