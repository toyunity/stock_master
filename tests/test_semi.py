"""반도체 동향 섹션 — 파서 (픽스처는 2026-07-13 실측 응답)."""
from backend.flow.semi import US_NAMES, parse_sox, parse_us_quote


def test_parse_us_quote_strips_leading_space_rate():
    # 실측: rate 선행 공백(' 0.00'). sign '0'은 프리오픈 롤오버 — 0.00% 보합으로
    # 그리면 직전 세션 변동을 가리므로 rate=None(–) 처리(리뷰 확정)
    js = {"rt_cd": "0", "output": {"rsym": "DNASMU", "last": "979.3000",
                                   "base": "979.3000", "diff": "0.0000",
                                   "rate": " 0.00", "sign": "0"}}
    q = parse_us_quote(js)
    assert q == {"last": 979.3, "base": 979.3, "rate": None, "sign": "flat"}
    # 장중 형태(상승)
    js = {"rt_cd": "0", "output": {"last": "215.10", "base": "210.96",
                                   "rate": " 1.96", "sign": "2"}}
    q = parse_us_quote(js)
    assert q["rate"] == 1.96 and q["sign"] == "up"
    # 미커버 심볼: rt_cd=0 + 빈값(무증상)
    assert parse_us_quote({"rt_cd": "0", "output": {"last": "", "rate": ""}}) is None
    assert parse_us_quote({"rt_cd": "1"}) is None


def test_parse_sox_real_fixture():
    js = {"rt_cd": "0", "output1": {
        "hts_kor_isnm": "필라델피아 반도체지수", "ovrs_nmix_prpr": "12967.16",
        "ovrs_nmix_prdy_vrss": "7.16", "prdy_vrss_sign": "2",
        "prdy_ctrt": "0.06", "ovrs_nmix_prdy_clpr": "12960.00"}}
    q = parse_sox(js)
    assert q == {"last": 12967.16, "base": 12960.0, "rate": 0.06, "sign": "up"}
    assert parse_sox({"rt_cd": "0", "output1": {}}) is None


def test_us_names_cover_default_set():
    from backend.config import settings
    for sym in settings.semi_us:
        assert sym in US_NAMES


def test_semi_us_uses_live_skhy_not_stale_skhyv():
    # 반도체 동향의 하이닉스 ADR도 /live처럼 실거래 SKHY를 써야 함.
    # SKHYV는 KIS가 상장일 값($168·거래량 0)에 얼려둔 스테일 → 갱신 안 됨(2026-07-15 실사고).
    from backend.config import settings
    assert "SKHY" in settings.semi_us and "SKHYV" not in settings.semi_us
