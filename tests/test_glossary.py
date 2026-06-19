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
