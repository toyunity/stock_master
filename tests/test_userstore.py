"""계정별 저장소 — 격리·검증·마이그레이션·토큰. 설계 2026-07-17.
⚠ Settings는 .env 자동로드 — 테스트는 tmp cache_dir·명시 값으로 격리."""
def test_norm_email():
    from backend.flow.userstore import norm_email
    assert norm_email("  Master@Gmail.com ") == "master@gmail.com"
