# services/supabase_client.py

import os
import hashlib
import re
import datetime
from typing import Any, Dict, List, Optional

from supabase import create_client, Client


def _sb() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def _utc_now_iso() -> str:
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()


# ----------------------------
# Fingerprint (dedupe key)
# ----------------------------
_ws = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = _ws.sub(" ", s)
    return s


def normalize_url(u: str) -> str:
    u = (u or "").strip()
    u = u.replace("http://", "https://")
    # canonicalize query + trailing slash
    u = u.split("?", 1)[0].rstrip("/")
    return u


def grant_fingerprint(title: str, url: str) -> str:
    """
    Stable key to identify the same grant across scans.
    Uses normalized title + canonical url.
    """
    base = f"{normalize_text(title)}|{normalize_url(url)}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


# ----------------------------
# Subscribers (existing usage)
# ----------------------------
def get_active_subscribers() -> List[Dict[str, Any]]:
    sb = _sb()
    res = (
        sb.table("subscribers")
        .select("id,email,pack,unsubscribe_token,status")
        .eq("status", "active")
        .execute()
    )

    rows = res.data or []

    # Normalize pack so send job does not get weird values like "de ", " germany ", None, etc.
    out: List[Dict[str, Any]] = []
    for row in rows:
        raw_pack = (row.get("pack") or "").strip().upper()
        row["pack"] = raw_pack if raw_pack else None
        out.append(row)

    return out


def log_send(
    subscriber_id: str,
    pack: str,
    item_count: int,
    status: str,
    error: Optional[str],
) -> None:
    sb = _sb()
    sb.table("send_logs").insert(
        {
            "subscriber_id": subscriber_id,
            "pack": pack,
            "item_count": item_count,
            "status": status,
            "error": error,
        }
    ).execute()


# ----------------------------
# Grants storage (scan -> Supabase)
# ----------------------------
def upsert_grants(grants: List[Dict[str, Any]], pack: Optional[str] = None) -> int:
    """
    Upserts grants into public.grants using fingerprint.

    IMPORTANT:
    - We try a "full" payload first (includes newer columns like last_seen/raw/etc).
    - If your grants table is older / missing some columns (e.g., pack), we retry
      with a smaller, safer payload to avoid breaking your scan.

    Returns: number of rows attempted (not exact inserts).
    """
    if not grants:
        return 0

    now = _utc_now_iso()

    # Full rows (best schema)
    rows_full: List[Dict[str, Any]] = []
    for g in grants:
        if not isinstance(g, dict):
            continue

        title = (g.get("title") or "").strip()
        url = (g.get("url") or "").strip()
        if not title or not url:
            continue

        fp = g.get("fingerprint") or grant_fingerprint(title, url)

        rows_full.append(
            {
                "fingerprint": fp,
                "canonical_url": normalize_url(url) or None,
                "pack": (pack or g.get("pack") or g.get("section") or None),
                "title": g.get("title"),
                "summary": g.get("summary"),
                "eligibility_notes": g.get("eligibility_notes"),
                "funder": g.get("funder"),
                "url": g.get("url"),
                "deadline_date": g.get("deadline_date"),
                "funding_amount_min": g.get("funding_amount_min"),
                "funding_amount_max": g.get("funding_amount_max"),
                "location_scope": g.get("location_scope"),
                "themes": g.get("themes"),
                "source": g.get("source"),
                "last_seen": now,
                "confidence_score": g.get("confidence_score") or g.get("_score"),
                "raw": g,
            }
        )

    if not rows_full:
        return 0

    sb = _sb()

    # 1) Try full upsert (may fail if older table missing columns like "pack", "raw", etc.)
    try:
        sb.table("grants").upsert(rows_full, on_conflict="fingerprint,pack").execute()
        return len(rows_full)
    except Exception as e:
        print("❌ GRANTS UPSERT FAILED:", str(e))
        raise


def fetch_latest_grants(limit: int = 500) -> List[Dict[str, Any]]:
    sb = _sb()
    # Prefer last_seen (you just added it). If your table has updated_at instead, this is still fine.
    res = (
        sb.table("grants")
        .select("*")
        .order("last_seen", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def fetch_grants_for_pack(pack: str, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Strict pack filter.
    Never fall back to latest grants, because that can send the wrong pack to users.
    """
    sb = _sb()
    pack = (pack or "").strip().upper()

    if not pack:
        return []

    try:
        res = (
            sb.table("grants")
            .select("*")
            .eq("pack", pack)
            .order("last_seen", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        print(f"⚠️ fetch_grants_for_pack failed for pack={pack}: {e}")
        return []
    
def has_grants_for_pack(pack: str) -> bool:
    sb = _sb()
    pack = (pack or "").strip().upper()

    if not pack:
        return False

    try:
        res = (
            sb.table("grants")
            .select("fingerprint")
            .eq("pack", pack)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        print(f"⚠️ has_grants_for_pack failed for pack={pack}: {e}")
        return False

def has_grants_for_pack(pack: str) -> bool:
    sb = _sb()
    pack = (pack or "").strip().upper()
    if not pack:
        return False

    try:
        res = (
            sb.table("grants")
            .select("fingerprint")
            .eq("pack", pack)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        print(f"⚠️ has_grants_for_pack failed for pack={pack}: {e}")
        return False


# ----------------------------
# Prevent duplicates in emails
# ----------------------------
def get_sent_counts(subscriber_id: str, fingerprints: List[str]) -> Dict[str, int]:
    """
    Returns {"<fingerprint>": sent_count, ...} for this subscriber.
    Table expected: grant_sends(subscriber_id, grant_fingerprint, sent_count, last_sent_at)
    """
    if not fingerprints:
        return {}

    sb = _sb()
    res = (
        sb.table("grant_sends")
        .select("grant_fingerprint,sent_count")
        .eq("subscriber_id", subscriber_id)
        .in_("grant_fingerprint", fingerprints)
        .execute()
    )

    out: Dict[str, int] = {}
    for row in (res.data or []):
        fp = row.get("grant_fingerprint")
        if not fp:
            continue
        out[fp] = int(row.get("sent_count") or 0)
    return out


def bump_sent(subscriber_id: str, fingerprints: List[str]) -> None:
    """
    Increment sent_count for each fingerprint. Creates rows if missing.

    Note:
    - Supabase python client doesn't provide a clean atomic increment across many rows.
      For MVP we:
        1) upsert missing rows with sent_count=0
        2) read current counts
        3) upsert updated counts
    """
    if not fingerprints:
        return

    sb = _sb()

    # 1) Ensure existence
    seed_rows = [
        {"subscriber_id": subscriber_id, "grant_fingerprint": fp, "sent_count": 0}
        for fp in fingerprints
    ]
    sb.table("grant_sends").upsert(
        seed_rows, on_conflict="subscriber_id,grant_fingerprint"
    ).execute()

    # 2) Read current counts
    current = get_sent_counts(subscriber_id, fingerprints)

    # 3) Write back bumped counts
    iso = _utc_now_iso()
    updates = []
    for fp in fingerprints:
        c = current.get(fp, 0) + 1
        updates.append(
            {
                "subscriber_id": subscriber_id,
                "grant_fingerprint": fp,
                "sent_count": c,
                "last_sent_at": iso,
            }
        )

    sb.table("grant_sends").upsert(
        updates, on_conflict="subscriber_id,grant_fingerprint"
    ).execute()