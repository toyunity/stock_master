"""테마 단일 출처 회귀 가드.

us_page.py가 .hero 마크업을 쓰는데 그 CSS가 live_page.py 페이지 로컬에만 있어
미국 상세 히어로가 스타일 없이 렌더되던 결함(2026-08-12 실측)을 막는다.
"""
from backend.report.dashboard import _BASE_CSS
from backend.report.theme import BASE_CSS


def test_hero_classes_live_in_shared_css():
    # us_page.py는 _BASE_CSS만 싣는다 — 히어로 클래스가 여기 없으면 그 화면이 민짜가 된다.
    for cls in (".hero{", ".hero .htop{", ".hero .hname{", ".hero .price{", ".hero .chg{"):
        assert cls in BASE_CSS, cls
    assert ".hero{" in _BASE_CSS      # dashboard 재수출 경로도 같은 내용이어야 한다
