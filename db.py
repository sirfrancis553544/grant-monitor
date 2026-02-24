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

# Columns we require for older DB migrations
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
    # PRAGMA table_info => (cid, name, type, notnull, dflt_value, pk)
    return {r[1] for r in rows}

def _migrate_grants_table(conn: sqlite3.Connection):
    """
    If DB already existed before schema updates, add missing columns.
    This prevents 'column ... does not exist' errors.
    """
    if not _table_exists(conn, "grants"):
        return

    existing = _get_columns(conn, "grants")
    missing = [c for c in REQUIRED_COLUMNS.keys() if c not in existing]
    if not missing:
        return

    for col in missing:
        col_type = REQUIRED_COLUMNS[col]
        # keep defaults simple; store.py always writes values for these
        conn.execute(f"ALTER TABLE grants ADD COLUMN {col} {col_type}")

def init_db(conn: sqlite3.Connection):
    # Create table if missing
    conn.executescript(SCHEMA_SQL)
    # Migrate older tables if needed
    _migrate_grants_table(conn)
    # Ensure indexes exist (safe even if already there)
    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_grants_last_seen ON grants(last_seen);
    CREATE INDEX IF NOT EXISTS idx_grants_deadline_date ON grants(deadline_date);
    """)
    conn.commit()