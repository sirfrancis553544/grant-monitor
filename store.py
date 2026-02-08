import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from dedupe import make_fingerprint


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def upsert_grant(conn, g: dict) -> tuple[bool, bool]:
    """
    Returns (inserted, changed)
    - inserted=True when new
    - changed=True when existing record updated (fields changed)
    """
    fingerprint = make_fingerprint(g["title"], g.get("funder"), g.get("deadline_date"), g.get("url"))
    now = _now_iso()

    themes_str = json.dumps(g.get("themes") or [], ensure_ascii=False)

    row = conn.execute(
        "SELECT id, title, funder, summary, eligibility_notes, deadline_date, funding_amount_min, funding_amount_max, "
        "location_scope, themes, url, source, confidence_score, raw_snippet "
        "FROM grants WHERE fingerprint=?",
        (fingerprint,)
    ).fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO grants (fingerprint, title, funder, summary, eligibility_notes, deadline_date, "
            "funding_amount_min, funding_amount_max, location_scope, themes, url, source, date_found, "
            "confidence_score, first_seen, last_seen, last_changed, raw_snippet) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fingerprint,
                g["title"],
                g.get("funder"),
                g.get("summary"),
                g.get("eligibility_notes"),
                g.get("deadline_date"),
                g.get("funding_amount_min"),
                g.get("funding_amount_max"),
                g.get("location_scope"),
                themes_str,
                g.get("url"),
                g.get("source"),
                g.get("date_found") or now,
                float(g.get("confidence_score") or 0.5),
                now, now, now,
                g.get("raw_snippet"),
            )
        )
        return True, False

    # Compare “core fields” to detect changes
    existing = {
        "title": row[1],
        "funder": row[2],
        "summary": row[3],
        "eligibility_notes": row[4],
        "deadline_date": row[5],
        "funding_amount_min": row[6],
        "funding_amount_max": row[7],
        "location_scope": row[8],
        "themes": row[9],
        "url": row[10],
        "source": row[11],
        "confidence_score": row[12],
        "raw_snippet": row[13],
    }

    newvals = {
        "title": g["title"],
        "funder": g.get("funder"),
        "summary": g.get("summary"),
        "eligibility_notes": g.get("eligibility_notes"),
        "deadline_date": g.get("deadline_date"),
        "funding_amount_min": g.get("funding_amount_min"),
        "funding_amount_max": g.get("funding_amount_max"),
        "location_scope": g.get("location_scope"),
        "themes": themes_str,
        "url": g.get("url"),
        "source": g.get("source"),
        "confidence_score": float(g.get("confidence_score") or 0.5),
        "raw_snippet": g.get("raw_snippet"),
    }

    changed = any(str(existing[k] or "") != str(newvals[k] or "") for k in newvals.keys())

    if changed:
        conn.execute(
            "UPDATE grants SET title=?, funder=?, summary=?, eligibility_notes=?, deadline_date=?, "
            "funding_amount_min=?, funding_amount_max=?, location_scope=?, themes=?, url=?, source=?, "
            "confidence_score=?, raw_snippet=?, last_seen=?, last_changed=? WHERE fingerprint=?",
            (
                newvals["title"], newvals["funder"], newvals["summary"], newvals["eligibility_notes"],
                newvals["deadline_date"], newvals["funding_amount_min"], newvals["funding_amount_max"],
                newvals["location_scope"], newvals["themes"], newvals["url"], newvals["source"],
                newvals["confidence_score"], newvals["raw_snippet"],
                now, now, fingerprint
            )
        )
    else:
        conn.execute("UPDATE grants SET last_seen=? WHERE fingerprint=?", (now, fingerprint))

    return False, changed

DEFAULT_DB_PATH = Path("data") / "grants.db"  # change if your DB filename differs


def _get_db_path() -> str:
    return os.environ.get("DB_PATH") or str(DEFAULT_DB_PATH)


def get_all_grants(limit: int | None = None) -> list[dict]:
    """
    Reads from your SQLite 'grants' table (the schema you already use in upsert_grant).
    Returns list[dict] that score.py expects.
    """
    db_path = _get_db_path()
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"DB not found at {db_path}. Set DB_PATH env var or put DB at {DEFAULT_DB_PATH}."
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    q = """
    SELECT
      title, funder, summary, eligibility_notes, deadline_date,
      funding_amount_min, funding_amount_max,
      location_scope, themes, url, source, confidence_score, raw_snippet
    FROM grants
    ORDER BY last_seen DESC
    """
    if limit:
        q += f" LIMIT {int(limit)}"

    rows = conn.execute(q).fetchall()
    conn.close()

    out: list[dict] = []
    for r in rows:
        d = dict(r)
        # themes stored as JSON string in DB
        try:
            d["themes"] = json.loads(d["themes"]) if d.get("themes") else []
        except Exception:
            d["themes"] = []

        out.append(d)

    return out
