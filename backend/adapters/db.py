from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    code TEXT PRIMARY KEY, name TEXT, added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT, action TEXT, confidence INTEGER, reasons TEXT,
    advice INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT, trades INTEGER, win_rate REAL, payoff REAL,
    max_drawdown REAL, passed INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

def get_conn(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)

def init_db(db_path: str) -> None:
    conn = get_conn(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
