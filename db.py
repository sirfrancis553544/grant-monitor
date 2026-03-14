# db.py
import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS grants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  fingerprint TEXT NOT NULL UNIQUE,

  title TEXT NOT NULL,
  funder TEXT,
  summary TEXT,
  eligibility_notes TEXT,
  deadline_date TEXT,
  funding_amount_min REAL,
  funding_amount_max REAL,
  location_scope TEXT,
  themes TEXT,
  url TEXT,
  source TEXT,

  date_found TEXT NOT NULL,
  confidence_score REAL DEFAULT 0.5,

  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  last_changed TEXT NOT NULL,

  raw_snippet TEXT
);

CREATE INDEX IF NOT EXISTS idx_grants_last_seen ON grants(last_seen);
CREATE INDEX IF NOT EXISTS idx_grants_deadline_date ON grants(deadline_date);
"""

REQUIRED_COLUMNS = {
    "fingerprint": "TEXT",
    "title": "TEXT",
    "funder": "TEXT",
    "summary": "TEXT",
    "eligibility_notes": "TEXT",
    "deadline_date": "TEXT",
    "funding_amount_min": "REAL",
    "funding_amount_max": "REAL",
    "location_scope": "TEXT",
    "themes": "TEXT",
    "url": "TEXT",
    "source": "TEXT",
    "date_found": "TEXT",
    "confidence_score": "REAL",
    "first_seen": "TEXT",
    "last_seen": "TEXT",
    "last_changed": "TEXT",
    "raw_snippet": "TEXT",
}


def get_conn(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _migrate_grants_table(conn: sqlite3.Connection):
    """
    If DB already existed before schema updates, add missing columns.
    """
    if not _table_exists(conn, "grants"):
        return

    existing = _get_columns(conn, "grants")
    missing = [c for c in REQUIRED_COLUMNS.keys() if c not in existing]
    if not missing:
        return

    for col in missing:
        col_type = REQUIRED_COLUMNS[col]
        conn.execute(f"ALTER TABLE grants ADD COLUMN {col} {col_type}")


def _backfill_nulls(conn: sqlite3.Connection):
    """
    Best-effort backfill for older rows after migrations.
    """
    if not _table_exists(conn, "grants"):
        return

    conn.execute("""
        UPDATE grants
        SET first_seen = COALESCE(first_seen, date_found)
        WHERE first_seen IS NULL
    """)
    conn.execute("""
        UPDATE grants
        SET last_seen = COALESCE(last_seen, date_found)
        WHERE last_seen IS NULL
    """)
    conn.execute("""
        UPDATE grants
        SET last_changed = COALESCE(last_changed, last_seen, date_found)
        WHERE last_changed IS NULL
    """)
    conn.execute("""
        UPDATE grants
        SET confidence_score = COALESCE(confidence_score, 0.5)
        WHERE confidence_score IS NULL
    """)
    conn.execute("""
        UPDATE grants
        SET themes = COALESCE(themes, '[]')
        WHERE themes IS NULL
    """)


def init_db(conn: sqlite3.Connection):
    conn.executescript(SCHEMA_SQL)
    _migrate_grants_table(conn)
    _backfill_nulls(conn)
    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_grants_last_seen ON grants(last_seen);
    CREATE INDEX IF NOT EXISTS idx_grants_deadline_date ON grants(deadline_date);
    """)
    conn.commit()
