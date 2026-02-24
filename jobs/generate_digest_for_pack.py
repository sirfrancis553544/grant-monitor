# jobs/generate_digest_for_pack.py

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple
import yaml

from score import score_grant
from digest import render_digest_html

# ✅ You must have a function that returns a list[dict] of grants from SQLite.
# If your function name differs, update the import + call below.
from store import get_all_grants

# ✅ Supabase send-history helpers
from services.supabase_client import get_sent_counts, bump_sent, grant_fingerprint

PACK_TO_PROFILE = {
    "DE": "profiles/germany_startup.yaml",
    "EU": "profiles/eu_startup.yaml",
    "UK": "profiles/uk_startup.yaml",
    "AFRICA": "profiles/africa_startup.yaml",
}


def load_profile(pack: str) -> dict:
    path = PACK_TO_PROFILE[pack]
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _ensure_fingerprint(g: dict) -> str | None:
    """
    Ensure each grant has a stable fingerprint used for dedupe + send history.
    """
    fp = g.get("fingerprint")
    if fp:
        return fp
    title = (g.get("title") or "").strip()
    url = (g.get("url") or "").strip()
    if not title or not url:
        return None
    fp = grant_fingerprint(title, url)
    g["fingerprint"] = fp
    return fp


def pick_top(grants: List[dict], profile: dict, limit: int = 20) -> List[dict]:
    """
    Score and pick top grants for a profile.
    Keeps only score > 0.
    """
    scored: List[dict] = []
    for g in grants:
        sc, why = score_grant(g, profile)
        if sc <= 0:
            continue
        gg = dict(g)
        gg["_score"] = sc
        gg["_why"] = why
        scored.append(gg)

    scored.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return scored[:limit]


def filter_repeat_sends(
    subscriber_id: str,
    grants: List[dict],
    max_repeat: int = 2,
) -> Tuple[List[dict], List[str]]:
    """
    Remove any grants already sent to this subscriber >= max_repeat times.
    Returns (filtered_grants, fingerprints_of_filtered_grants).
    """
    if not subscriber_id:
        # If no subscriber_id provided, we can't track; allow all.
        fps = [fp for g in grants if (fp := _ensure_fingerprint(g))]
        return grants, fps

    fps = []
    for g in grants:
        fp = _ensure_fingerprint(g)
        if fp:
            fps.append(fp)

    counts = get_sent_counts(subscriber_id=subscriber_id, fingerprints=fps)

    allowed: List[dict] = []
    allowed_fps: List[str] = []

    for g in grants:
        fp = g.get("fingerprint")
        if not fp:
            continue
        if counts.get(fp, 0) < max_repeat:
            allowed.append(g)
            allowed_fps.append(fp)

    return allowed, allowed_fps


def generate_digest_for_pack(
    pack: str,
    subscriber_id: str | None = None,
    max_repeat: int = 2,
) -> Tuple[str, str, int, List[str]]:
    """
    Returns:
      (subject, html, item_count, fingerprints_sent)

    Applies duplicate suppression:
      - a subscriber can receive the same grant at most `max_repeat` times.
    """
    pack = pack.upper().strip()
    if pack not in PACK_TO_PROFILE:
        raise ValueError(f"Unknown pack: {pack}")

    profile = load_profile(pack)

    # Pull all grants from SQLite (already ingested by run.py / scan)
    grants = get_all_grants()  # <-- rename if your function differs

    # Pick top based on scoring
    top_n = int(profile.get("top_n", 20))
    picked = pick_top(grants, profile, limit=top_n)

    # Apply repeat-suppression per subscriber
    sid = (subscriber_id or "").strip()
    filtered, fps_sent = filter_repeat_sends(sid, picked, max_repeat=max_repeat)

    # Render HTML
    # NOTE: your digest renderer supports list mode (single pack)
    html = render_digest_html(filtered)

    subject = f"RubixScout — {pack} Funding Digest"
    return subject, html, len(filtered), fps_sent


def mark_digest_sent(subscriber_id: str, fingerprints_sent: List[str]) -> None:
    """
    Call after successful email send.
    """
    if not subscriber_id or not fingerprints_sent:
        return
    bump_sent(subscriber_id=subscriber_id, fingerprints=fingerprints_sent)