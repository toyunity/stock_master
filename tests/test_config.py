import shutil
from pathlib import Path

from backend.config import Settings

def test_defaults_have_watchlist_and_paths():
    s = Settings()
    assert isinstance(s.watchlist, list)
    assert len(s.watchlist) >= 5
    assert all(code.isdigit() and len(code) == 6 for code in s.watchlist)
    assert s.cache_dir.endswith("cache")

def test_env_override(monkeypatch):
    monkeypatch.setenv("SM_HISTORY_DAYS", "42")
    s = Settings()
    assert s.history_days == 42

def test_env_example_boots(tmp_path, monkeypatch):
    """README 첫 줄이 `cp .env.example .env`다 — 그러고 기동이 죽으면 README가 거짓말이 된다.

    실제로 두 번 죽었다: 빈 값(`SM_AUTH_ENABLED=`)은 '미설정'이 아니라 `''`로 들어와
    bool 파싱이 터지고, 값 뒤에 붙인 `# 주석`은 값의 일부로 읽힌다. 그래서 예시 파일의
    bool·주석 키는 통째로 주석 처리한다(키가 없어야 필드 기본값이 쓰인다)."""
    shutil.copy(Path(__file__).resolve().parent.parent / ".env.example", tmp_path / ".env")
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert s.auth_enabled is False and s.options_enabled is False   # 데모로 안전하게 뜬다
    assert not (s.allowed_emails or "").lstrip().startswith("#")    # 주석이 값으로 새지 않는다


def test_public_url_has_no_default(monkeypatch):
    """공개 호스트명은 소스가 아니라 .env에만 있다(리포 공개 시 고정 표적 방지)."""
    monkeypatch.delenv("SM_PUBLIC_URL", raising=False)
    assert Settings(_env_file=None).public_url is None
