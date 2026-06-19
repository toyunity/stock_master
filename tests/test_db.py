from backend.adapters.db import init_db, get_conn

def test_init_creates_tables(tmp_path):
    db = tmp_path / "t.db"
    init_db(str(db))
    conn = get_conn(str(db))
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"signals", "watchlist", "backtest_results"} <= names
    conn.close()
