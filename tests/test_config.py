from backend.config import Settings

def test_defaults_have_watchlist_and_paths():
    s = Settings()
    assert isinstance(s.watchlist, list)
    assert len(s.watchlist) >= 5
    assert all(code.isdigit() and len(code) == 6 for code in s.watchlist)
    assert s.cache_dir.endswith("cache")
    assert s.db_path.endswith(".db")

def test_env_override(monkeypatch):
    monkeypatch.setenv("SM_DB_PATH", "/tmp/x.db")
    s = Settings()
    assert s.db_path == "/tmp/x.db"
