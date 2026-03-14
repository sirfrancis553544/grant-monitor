from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dedupe import make_fingerprint

try:
    from supabase import Client, create_client
except Exception:
    Client = None  # type: ignore
    create_client = None  # type: ignore


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# -------------------------------------------------------------------
# Existing SQLite upsert logic
# -------------------------------------------------------------------
def upsert_grant(conn, g: dict) -> tuple[bool, bool]:
    """
    Returns (inserted, changed)
    - inserted=True when new
    - changed=True when existing record updated (fields changed)
    """
    fingerprint = make_fingerprint(
        g["title"],
        g.get("funder"),
        g.get("deadline_date"),
        g.get("url"),
    )
    now = _now_iso()

    themes_str = json.dumps(g.get("themes") or [], ensure_ascii=False)

    row = conn.execute(
        """
        SELECT id, title, funder, summary, eligibility_notes, deadline_date,
               funding_amount_min, funding_amount_max, location_scope, themes,
               url, source, confidence_score, raw_snippet
        FROM grants
        WHERE fingerprint=?
        """,
        (fingerprint,),
    ).fetchone()

    if row is None:
        conn.execute(
            """
            INSERT INTO grants (
                fingerprint, title, funder, summary, eligibility_notes, deadline_date,
                funding_amount_min, funding_amount_max, location_scope, themes, url, source,
                date_found, confidence_score, first_seen, last_seen, last_changed, raw_snippet
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
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
                now,
                now,
                now,
                g.get("raw_snippet"),
            ),
        )
        return True, False

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
            """
            UPDATE grants
            SET title=?, funder=?, summary=?, eligibility_notes=?, deadline_date=?,
                funding_amount_min=?, funding_amount_max=?, location_scope=?, themes=?, url=?, source=?,
                confidence_score=?, raw_snippet=?, last_seen=?, last_changed=?
            WHERE fingerprint=?
            """,
            (
                newvals["title"],
                newvals["funder"],
                newvals["summary"],
                newvals["eligibility_notes"],
                newvals["deadline_date"],
                newvals["funding_amount_min"],
                newvals["funding_amount_max"],
                newvals["location_scope"],
                newvals["themes"],
                newvals["url"],
                newvals["source"],
                newvals["confidence_score"],
                newvals["raw_snippet"],
                now,
                now,
                fingerprint,
            ),
        )
    else:
        conn.execute("UPDATE grants SET last_seen=? WHERE fingerprint=?", (now, fingerprint))

    return False, changed


# -------------------------------------------------------------------
# Read helpers
# -------------------------------------------------------------------
DEFAULT_DB_PATH = Path("data") / "grants.db"


def _get_db_path() -> str:
    return os.environ.get("DB_PATH") or str(DEFAULT_DB_PATH)


def _normalize_themes(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if x]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
        except Exception:
            return [value] if value.strip() else []
    return [str(value)]


def _normalize_grant_row(d: Dict[str, Any]) -> Dict[str, Any]:
    title = (d.get("title") or "").strip()
    funder = (d.get("funder") or None)
    deadline = d.get("deadline_date")
    url = (d.get("url") or "").strip()

    d["themes"] = _normalize_themes(d.get("themes"))

    if not d.get("fingerprint") and title and url:
        d["fingerprint"] = make_fingerprint(title, funder, deadline, url)

    return d


# -------------------------------------------------------------------
# Supabase read path
# -------------------------------------------------------------------
def _can_use_supabase() -> bool:
    return bool(
        create_client
        and os.environ.get("SUPABASE_URL")
        and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )


def _sb() -> Client:
    if not _can_use_supabase():
        raise RuntimeError("Supabase client not configured")
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def _get_all_grants_from_supabase(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    sb = _sb()

    query = (
        sb.table("grants")
        .select(
            "fingerprint,title,funder,summary,eligibility_notes,deadline_date,"
            "funding_amount_min,funding_amount_max,location_scope,themes,url,source,"
            "confidence_score,raw,last_seen,pack"
        )
        .order("last_seen", desc=True)
    )

    if limit:
        query = query.limit(int(limit))

    res = query.execute()
    rows = res.data or []

    out: List[Dict[str, Any]] = []
    for row in rows:
        raw = row.get("raw") or {}
        merged = {
            "fingerprint": row.get("fingerprint"),
            "title": row.get("title"),
            "funder": row.get("funder"),
            "summary": row.get("summary") or raw.get("summary"),
            "eligibility_notes": row.get("eligibility_notes") or raw.get("eligibility_notes"),
            "deadline_date": row.get("deadline_date"),
            "funding_amount_min": row.get("funding_amount_min"),
            "funding_amount_max": row.get("funding_amount_max"),
            "location_scope": row.get("location_scope"),
            "themes": row.get("themes"),
            "url": row.get("url"),
            "source": row.get("source"),
            "confidence_score": row.get("confidence_score"),
            "raw_snippet": raw.get("raw_snippet"),
            "pack": row.get("pack"),
        }
        out.append(_normalize_grant_row(merged))

    return out


# -------------------------------------------------------------------
# SQLite fallback
# -------------------------------------------------------------------
def _get_all_grants_from_sqlite(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    db_path = _get_db_path()
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"DB not found at {db_path}. Set DB_PATH env var or put DB at {DEFAULT_DB_PATH}."
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    q = """
    SELECT
      fingerprint,
      title,
      funder,
      summary,
      eligibility_notes,
      deadline_date,
      funding_amount_min,
      funding_amount_max,
      location_scope,
      themes,
      url,
      source,
      confidence_score,
      raw_snippet,
      last_seen
    FROM grants
    ORDER BY last_seen DESC
    """
    if limit:
        q += f" LIMIT {int(limit)}"

    rows = conn.execute(q).fetchall()
    conn.close()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(_normalize_grant_row(dict(r)))

    return out


# -------------------------------------------------------------------
# Public read API
# -------------------------------------------------------------------
def get_all_grants(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Preferred order:
    1) Supabase grants table
    2) local SQLite fallback

    This keeps local development easy while making CI / GitHub Actions use the
    canonical remote grants store.
    """
    if _can_use_supabase():
        try:
            return _get_all_grants_from_supabase(limit=limit)
        except Exception as e:
            print(f"⚠️ Supabase get_all_grants failed, falling back to SQLite: {e}")

    return _get_all_grants_from_sqlite(limit=limit)