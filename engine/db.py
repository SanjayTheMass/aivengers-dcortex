"""SQLite connection helper. Swap DB_URL to PostgreSQL later without touching callers."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "crewops.db"


def get_con():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def rows(con, sql, params=()):
    return [dict(r) for r in con.execute(sql, params).fetchall()]
