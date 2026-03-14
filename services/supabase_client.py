# services/supabase_client.py

from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

from supabase import Client, create_client

from dedupe import make_fingerprint as grant_fingerprint


def _sb() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def _utc_now_iso() -> str:
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()


def normalize_url(u: str) -> str:
    u = (u or "").strip()
    u = u.replace("http://", "https://")
    u = u.split("?", 1)[0].rstrip("/")
    return u


# ----------------------------
# Subscribers
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
# Grants storage
# ----------------------------
def upsert_grants(grants: List[Dict[str, Any]], pack: Optional[str] = None) -> int:
    if not grants:
        return 0

    now = _utc_now_iso()
    rows_full: List[Dict[str, Any]] = []

    for g in grants:
        if not isinstance(g, dict):
            continue

        title = (g.get("title") or "").strip()
        url = (g.get("url") or "").strip()
        funder = (g.get("funder") or "").strip() or None
        deadline_date = (g.get("deadline_date") or "").strip() or None

        if not title or not url:
            continue

        fp = g.get("fingerprint") or grant_fingerprint(
            title=title,
            funder=funder,
            deadline_date=deadline_date,
            url=url,
        )

        resolved_pack = pack or g.get("pack") or g.get("section")
        resolved_pack = str(resolved_pack).strip().upper() if resolved_pack else None
        if not resolved_pack:
            continue

        rows_full.append(
            {
                "fingerprint": fp,
                "canonical_url": normalize_url(url) or None,
                "pack": resolved_pack,
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
    try:
        sb.table("grants").upsert(rows_full, on_conflict="fingerprint,pack").execute()
        return len(rows_full)
    except Exception as e:
        print("❌ GRANTS UPSERT FAILED:", str(e))
        raise


def fetch_latest_grants(limit: int = 500) -> List[Dict[str, Any]]:
    sb = _sb()
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
    Never falls back to latest grants, because that can send the wrong pack to users.
    Returns newest grants first.
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
        rows = res.data or []

        out: List[Dict[str, Any]] = []
        for row in rows:
            title = (row.get("title") or "").strip()
            url = (row.get("url") or "").strip()
            funder = (row.get("funder") or "").strip() or None
            deadline_date = (row.get("deadline_date") or "").strip() or None

            if not row.get("fingerprint") and title and url:
                row["fingerprint"] = grant_fingerprint(
                    title=title,
                    funder=funder,
                    deadline_date=deadline_date,
                    url=url,
                )

            out.append(row)

        return out

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


# ----------------------------
# Prevent duplicates in emails
# ----------------------------
def get_sent_counts(subscriber_id: str, fingerprints: List[str]) -> Dict[str, int]:
    """
    Returns {"<fingerprint>": sent_count, ...} for this subscriber.
    Expected table:
      grant_sends(subscriber_id, grant_fingerprint, sent_count, last_sent_at)
    """
    if not subscriber_id or not fingerprints:
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

    MVP approach:
      1) upsert missing rows with sent_count=0
      2) read current counts
      3) upsert bumped counts
    """
    if not subscriber_id or not fingerprints:
        return

    sb = _sb()

    seed_rows = [
        {"subscriber_id": subscriber_id, "grant_fingerprint": fp, "sent_count": 0}
        for fp in fingerprints
    ]
    sb.table("grant_sends").upsert(
        seed_rows,
        on_conflict="subscriber_id,grant_fingerprint",
    ).execute()

    current = get_sent_counts(subscriber_id, fingerprints)
    iso = _utc_now_iso()

    updates = []
    for fp in fingerprints:
        updates.append(
            {
                "subscriber_id": subscriber_id,
                "grant_fingerprint": fp,
                "sent_count": current.get(fp, 0) + 1,
                "last_sent_at": iso,
            }
        )

    sb.table("grant_sends").upsert(
        updates,
        on_conflict="subscriber_id,grant_fingerprint",
    ).execute()
