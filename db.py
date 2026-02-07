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
  deadline_date TEXT, -- ISO date string if available, else NULL
  funding_amount_min REAL,
  funding_amount_max REAL,
  location_scope TEXT,
  themes TEXT, -- JSON-ish string
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

def get_conn(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db(conn: sqlite3.Connection):
    conn.executescript(SCHEMA_SQL)
    conn.commit()
