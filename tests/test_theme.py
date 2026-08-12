"""테마 단일 출처 회귀 가드.

us_page.py가 .hero 마크업을 쓰는데 그 CSS가 live_page.py 페이지 로컬에만 있어
미국 상세 히어로가 스타일 없이 렌더되던 결함(2026-08-12 실측)을 막는다.
"""
import re

from backend.report.dashboard import _BASE_CSS
from backend.report.theme import BASE_CSS, PWA_HEAD


def test_hero_classes_live_in_shared_css():
    # us_page.py는 _BASE_CSS만 싣는다 — 히어로 클래스가 여기 없으면 그 화면이 민짜가 된다.
    # .hero .chg는 없다 — us_page의 등락 표시는 2026-08-13부터 .pill(공유 컴포넌트,
    # 아래 test_pill_is_shared_and_has_direction_variants가 덮는다)을 쓴다.
    for cls in (".hero{", ".hero .htop{", ".hero .hname{", ".hero .price{"):
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


def test_pages_do_not_hardcode_colors():
    """CSS 단일 출처 — 페이지 파일에 색을 직접 쓰지 않는다(CLAUDE.md).

    허용 목록은 파일별 "정확한 헥스 값" 단위로 좁힌다 — 같은 파일에 새 하드코딩
    색이 섞여도 그 값이 목록에 없으면 여전히 걸린다(2026-08-13 감사).

    예외 사유:
    - options_panel.py·vol_panel.py: `CV('--x')||'#hex'` 폴백. theme.py의
      CHART_THEME_JS._cv()와 동일한 패턴 — node 하니스는 getComputedStyle이
      없어 이 폴백이 실제로 실행되는 살아있는 코드다(theme.py 주석 참조).
    - dashboard.py·live_page.py·us_page.py 캔들/기준선/가격선/이평선 색:
      LightweightCharts는 JS 객체 리터럴이라 CSS var()를 못 받는다. 캔들·기준선은
      같은 틱에 registerSemSeries()가 semUp()/semDown()으로 즉시 재적용해 이 값이
      화면에 노출되진 않는다. 이평선 5색(#9aa0a6 등)은 토큰과 의미가 다른 카테고리
      팔레트라 토큰화하면 5개 신규 토큰이 필요해 과설계다.
      (알려진 갭, 이번 범위 아님: us_page.py 캔들은 registerSemSeries를 안 불러
      다크에서 라이트 색 그대로다. live_page.py:717 현재가 색·891 매물벽 마커도
      다크 재적용 없이 라이트 값 고정.)
    - dashboard.py `#b3a4ff`: 앱 아이콘 마크 그라디언트의 보조색. 라이트·다크
      공통 고정값이 의도다 — `--primary-ink`로 바꾸면 라이트(#5238d8, 더 어두움)와
      다크(#9a86ff·b3a4ff, 더 밝음)가 반대 방향이라 그라디언트가 뒤집힌다.
    - widget_setup.py: iOS Scriptable 위젯 스크립트 — 다른 런타임·다른 색 시스템
      (Color.dynamic)이라 CSS 토큰과 무관하다.
    """
    import re
    from pathlib import Path

    report_dir = Path(__file__).resolve().parents[1] / "backend" / "report"
    files = sorted(report_dir.glob("*.py"))
    assert files, "backend/report 스캔 경로가 비었다 — glob이 깨졌다"

    allowed_hex = {
        "options_panel.py": {"#e5342f", "#1f66e0", "#dcdfe6", "#8b93a4"},
        "vol_panel.py": {"#dcdfe6", "#8b93a4", "#1a1d24", "#e5342f", "#1f66e0"},
        "dashboard.py": {"#e5342f", "#1f66e0", "#b3a4ff"},
        "live_page.py": {
            "#e5342f", "#1f66e0", "#8a94a6", "#a855f7",
            "#9aa0a6", "#ec4899", "#f59e0b", "#22c55e", "#3b82f6",
        },
        "us_page.py": {"#e5342f", "#1f66e0", "#f0a020", "#6a4ff0", "#8a8f9a"},
        "widget_setup.py": {
            "#d32f2f", "#ff6b6b", "#1565c0", "#6ba3ff", "#000000", "#ffffff",
        },
    }

    bad = []
    for p in files:
        if p.name == "theme.py":
            continue
        allowed = allowed_hex.get(p.name, set())
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            # var(--토큰) 자체를 지운 뒤 남은 hex만 본다. 줄 단위로 통째로
            # 건너뛰면 `linear-gradient(135deg,var(--primary),#b3a4ff)`처럼
            # 토큰과 하드코딩이 한 줄에 섞인 경우 hex가 검사에서 통째로
            # 빠진다(2026-08-13 리뷰에서 발견 — 허용 목록에서 지워도 통과했다).
            stripped = re.sub(r"var\(--[a-z0-9-]+\)", "", line)
            for m in re.finditer(r"#[0-9a-fA-F]{6}\b", stripped):
                if m.group(0).lower() not in allowed:
                    bad.append("%s:%d:%s" % (p.name, i, m.group(0)))
    assert bad == [], "허용 목록 밖 하드코딩 색: %s" % bad


def test_hero_headline_is_sans_tabular_48():
    """kospinow 문법: 히어로는 모노가 아니라 sans 볼드 tabular다.
    Pretendard는 굽기당 766~791KB라 못 싣는다(2026-08-12 실측) — SF Pro로 같은 효과를 낸다."""
    hero = BASE_CSS.split(".hero .price{", 1)[1].split("}", 1)[0]
    assert "font-size:48px" in hero
    assert "font-weight:800" in hero
    assert "tabular-nums" in hero
    assert "var(--font-num)" not in hero      # 모노를 쓰지 않는다
