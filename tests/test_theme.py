"""테마 단일 출처 회귀 가드.

us_page.py가 .hero 마크업을 쓰는데 그 CSS가 live_page.py 페이지 로컬에만 있어
미국 상세 히어로가 스타일 없이 렌더되던 결함(2026-08-12 실측)을 막는다.
"""
import re

from backend.report.dashboard import _BASE_CSS
from backend.report.theme import BASE_CSS, PWA_HEAD


def test_hero_classes_live_in_shared_css():
    # us_page.py는 _BASE_CSS만 싣는다 — 히어로 클래스가 여기 없으면 그 화면이 민짜가 된다.
    for cls in (".hero{", ".hero .htop{", ".hero .hname{", ".hero .price{", ".hero .chg{"):
        assert cls in BASE_CSS, cls
    assert ".hero{" in _BASE_CSS      # dashboard 재수출 경로도 같은 내용이어야 한다


def test_pill_is_shared_and_has_direction_variants():
    assert ".pill{" in BASE_CSS
    assert ".pill.up{" in BASE_CSS and ".pill.down{" in BASE_CSS
    # 새 색을 만들지 않았는지 — 기존 틴트 토큰만 쓴다
    assert "--up-bg" in BASE_CSS and "--down-bg" in BASE_CSS


def _selectors(css: str) -> set:
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)  # 주석이 셀렉터에 붙는 것 방지
    return {re.sub(r"\s+", "", m.group(1))
            for m in re.finditer(r"([^{}\n][^{}]*)\{[^{}]*\}", css)}


def test_tokens_match_6th_redesign():
    """되돌림 가드. 진짜 검수는 make verify 스크린샷이지, 이 문자열 검사가 아니다."""
    for tok in ("--r-lg:24px", "--r:16px", "--r-sm:12px",
                "--bg:#f0f4f8", "--bg:#080b10"):
        assert tok in BASE_CSS, tok
    # 경계선은 rgba여야 서피스 3단계 어디에 놓여도 대비가 일정하다
    assert "--border:rgba(0,0,0,.07)" in BASE_CSS
    assert "--border:rgba(255,255,255,.09)" in BASE_CSS
    # 시맨틱 색은 건드리지 않는다
    assert "--up:#e5342f" in BASE_CSS and "--down:#1f66e0" in BASE_CSS
    # PWA_HEAD의 theme-color는 --bg의 리터럴 사본이다(CSS 변수를 못 씀) — 따로 갱신 안 하면
    # 홈화면 PWA 상태바 색이 새 --bg와 어긋나 상단에 이음매가 생긴다(2026-08-12 리뷰 발견).
    assert "#f0f4f8" in PWA_HEAD and "#080b10" in PWA_HEAD


def test_live_page_does_not_redefine_shared_rules():
    """live_page.py는 __BASE_CSS__를 이미 싣는다 — 같은 셀렉터를 또 정의하면
    두 복사본이 갈라져도 아무도 모른다(2026-08-12: 10규칙이 바이트 동일 복제였다)."""
    from pathlib import Path
    src = Path("backend/report/live_page.py").read_text(encoding="utf-8")
    local = src.split("__BASE_CSS__", 1)[1].split("</style>", 1)[0]
    shared = _selectors(BASE_CSS)
    dupes = sorted(s for s in _selectors(local) if s in shared)
    assert dupes == [], "theme.py와 중복된 셀렉터: %s" % dupes


def test_rail_component_exists():
    for sel in (".rail{", ".rail>div{", ".rail .k{", ".rail .v{"):
        assert sel in BASE_CSS, sel


def test_direction_bar_variants_exist():
    assert ".card--up{" in BASE_CSS and ".card--down{" in BASE_CSS
