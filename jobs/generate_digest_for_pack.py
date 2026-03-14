from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from digest import render_digest_html
from score import score_grant
from services.supabase_client import bump_sent, get_sent_counts, grant_fingerprint
from store import get_all_grants
from utils.application_effort import estimate_application_effort
from utils.deadline_radar import deadline_badge


PACK_TO_PROFILE = {
    "DE": "profiles/germany_startup.yaml",
    "EU": "profiles/eu_startup.yaml",
    "UK": "profiles/uk_startup.yaml",
    "AFRICA": "profiles/africa_startup.yaml",
}

PACK_LABELS = {
    "DE": "Germany",
    "EU": "European Union",
    "UK": "United Kingdom",
    "AFRICA": "Africa",
}


def load_profile(pack: str) -> Dict[str, Any]:
    pack = (pack or "").strip().upper()
    if pack not in PACK_TO_PROFILE:
        raise ValueError(f"Unknown pack: {pack}")

    path = PACK_TO_PROFILE[pack]
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _subject(pack: str) -> str:
    pack = (pack or "").strip().upper()
    label = PACK_LABELS.get(pack, pack or "Selected pack")
    return f"RubixScout | Weekly Grant Digest ({label})"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _ensure_fingerprint(g: Dict[str, Any]) -> str | None:
    """
    Ensure each grant has a stable fingerprint used for dedupe + send history.
    """
    fp = g.get("fingerprint")
    if fp:
        return str(fp)

    title = (g.get("title") or "").strip()
    url = (g.get("url") or "").strip()
    funder = (g.get("funder") or "").strip() or None
    deadline_date = (g.get("deadline_date") or "").strip() or None

    if not title or not url:
        return None

    fp = grant_fingerprint(title, funder, deadline_date, url)
    g["fingerprint"] = fp
    return fp


def _themes_to_text(themes: Any) -> str:
    if not themes:
        return ""
    if isinstance(themes, str):
        return themes
    if isinstance(themes, (list, tuple, set)):
        return " ".join(str(x) for x in themes if x)
    return str(themes)


def _text_blob(g: Dict[str, Any]) -> str:
    parts = [
        g.get("title"),
        g.get("summary"),
        g.get("eligibility_notes"),
        g.get("location_scope"),
        g.get("funder"),
        _themes_to_text(g.get("themes")),
        g.get("source"),
        g.get("url"),
    ]
    return " ".join(str(x or "") for x in parts).lower()


def is_pack_eligible(g: Dict[str, Any], pack: str) -> bool:
    """
    Hard pack filter.
    Conservative rules:
    - DE: Germany/Berlin only
    - UK: UK only
    - EU: EU + Germany, but not UK-only / Africa-only
    - AFRICA: Africa-specific only, unless the text explicitly targets Africa
    """
    pack = (pack or "").strip().upper()
    text = f" {_text_blob(g)} "
    source = (g.get("source") or "").strip().lower()
    scope = (g.get("location_scope") or "").strip().upper()

    def has_any(*terms: str) -> bool:
        return any(term.lower() in text for term in terms)

    is_germany = (
        source.startswith("berlin_ibb")
        or scope in {"DE", "BERLIN", "GERMANY"}
        or has_any(
            "germany",
            "german",
            "berlin",
            "deutschland",
            "deutsche",
            "investitionsbank berlin",
            "ibb",
        )
    )

    is_uk = (
        source.startswith("innovate_uk")
        or scope == "UK"
        or has_any(
            "united kingdom",
            "britain",
            "british",
            "england",
            "scotland",
            "wales",
            "northern ireland",
            "innovate uk",
            "ukri",
        )
    )

    is_africa = (
        source in {"aecf_opportunities", "gsma_innovation_fund", "tef_entrepreneurship"}
        or scope in {"AFRICA", "SUB-SAHARAN AFRICA"}
        or has_any(
            "africa",
            "african",
            "sub-saharan africa",
            "entrepreneurs across africa",
            "54 african countries",
            "african entrepreneurs",
            "kenya",
            "nigeria",
            "south africa",
            "ghana",
            "uganda",
            "tanzania",
            "rwanda",
            "zambia",
            "ethiopia",
        )
    )

    is_eu = (
        source in {"eu_funding_tenders_calls", "eic_accelerator"}
        or scope in {"EU", "EUROPE"}
        or has_any(
            "european union",
            "horizon europe",
            "european commission",
            "funding & tenders",
            "funding and tenders",
            "eic accelerator",
            "european innovation council",
            "eu-wide",
            "eu wide",
            "brussels",
        )
    )

    if pack == "DE":
        return is_germany and not is_uk and not is_africa

    if pack == "UK":
        return is_uk and not is_germany and not is_africa

    if pack == "EU":
        return (is_eu or is_germany) and not is_uk and not is_africa

    if pack == "AFRICA":
        return (
            is_africa
            and not is_germany
            and not (
                is_uk
                and not has_any(
                    "africa",
                    "african",
                    "sub-saharan africa",
                    "african entrepreneurs",
                    "54 african countries",
                    "oda eligible countries in sub-saharan africa",
                )
            )
            and not (
                is_eu
                and not has_any(
                    "africa",
                    "african",
                    "sub-saharan africa",
                    "african entrepreneurs",
                    "54 african countries",
                )
            )
        )

    return False


def _freshness_bonus(g: Dict[str, Any]) -> float:
    """
    Small bonus for fresher grants so strong new items can rotate in.
    """
    last_seen = _parse_dt(g.get("last_seen"))
    if not last_seen:
        return 0.0

    now = datetime.now(timezone.utc)
    age_days = max(0, (now - last_seen).days)

    if age_days <= 3:
        return 1.2
    if age_days <= 7:
        return 0.9
    if age_days <= 14:
        return 0.5
    if age_days <= 30:
        return 0.2
    return 0.0


def _rotation_rank(g: Dict[str, Any], sent_count: int) -> float:
    """
    Final ranking score used for selection.
    Balances base score with freshness and light anti-repeat pressure.
    """
    base = float(g.get("_score", 0))
    freshness = _freshness_bonus(g)

    # Penalize repeat exposure so near-equal grants can rotate.
    repeat_penalty = 1.25 * max(0, sent_count)

    # Slight nudge for nearer deadlines if deadline_radar already computed.
    radar = g.get("deadline_radar") or {}
    deadline_boost = 0.0
    if isinstance(radar, dict):
        days = radar.get("days")
        try:
            days_int = int(days)
            if 0 <= days_int <= 14:
                deadline_boost = 0.6
            elif 15 <= days_int <= 30:
                deadline_boost = 0.3
        except Exception:
            pass

    return base + freshness + deadline_boost - repeat_penalty


def pick_top(
    grants: List[Dict[str, Any]],
    profile: Dict[str, Any],
    subscriber_id: str | None = None,
    limit: int = 20,
    max_repeat: int = 2,
) -> List[Dict[str, Any]]:
    """
    Score and pick top grants for a profile.
    Keeps only score > 0, enriches grants for rendering, and rotates results
    so users do not see the exact same top items every week.
    """
    scored: List[Dict[str, Any]] = []

    for g in grants:
        sc, why = score_grant(g, profile)
        if sc <= 0:
            continue

        gg = dict(g)
        gg["_score"] = sc
        gg["_why"] = why
        gg["fit_score"] = max(1, min(99, int(sc * 10)))
        gg["application_effort"] = estimate_application_effort(gg)
        gg["deadline_radar"] = deadline_badge(gg.get("deadline_date"))
        _ensure_fingerprint(gg)

        scored.append(gg)

    if not scored:
        return []

    counts: Dict[str, int] = {}
    if subscriber_id:
        fps = [g["fingerprint"] for g in scored if g.get("fingerprint")]
        counts = get_sent_counts(subscriber_id=subscriber_id, fingerprints=fps)

    eligible_ranked: List[Dict[str, Any]] = []
    for g in scored:
        fp = g.get("fingerprint")
        sent_count = int(counts.get(fp, 0)) if fp else 0

        if sent_count >= max_repeat:
            continue

        gg = dict(g)
        gg["_sent_count"] = sent_count
        gg["_rotation_rank"] = _rotation_rank(gg, sent_count)
        eligible_ranked.append(gg)

    eligible_ranked.sort(
        key=lambda x: (
            x.get("_rotation_rank", 0),
            x.get("_score", 0),
        ),
        reverse=True,
    )

    return eligible_ranked[:limit]


def filter_repeat_sends(
    subscriber_id: str,
    grants: List[Dict[str, Any]],
    max_repeat: int = 2,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Final defensive filter.
    Returns:
      (filtered_grants, fingerprints_of_filtered_grants)
    """
    if not subscriber_id:
        fps = [fp for g in grants if (fp := _ensure_fingerprint(g))]
        return grants, fps

    fps: List[str] = []
    for g in grants:
        fp = _ensure_fingerprint(g)
        if fp:
            fps.append(fp)

    counts = get_sent_counts(subscriber_id=subscriber_id, fingerprints=fps)

    allowed: List[Dict[str, Any]] = []
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

    Applies:
      - hard pack eligibility filtering
      - score-based ranking
      - fit score enrichment
      - application effort enrichment
      - deadline radar enrichment
      - smart grant rotation
      - duplicate suppression
    """
    pack = (pack or "").strip().upper()
    if pack not in PACK_TO_PROFILE:
        raise ValueError(f"Unknown pack: {pack}")

    profile = load_profile(pack)

    grants = get_all_grants()
    eligible = [g for g in grants if is_pack_eligible(g, pack)]

    top_n = min(int(profile.get("top_n", 6) or 6), 12)

    picked = pick_top(
        eligible,
        profile,
        subscriber_id=subscriber_id,
        limit=top_n,
        max_repeat=max_repeat,
    )

    sid = (subscriber_id or "").strip()
    filtered, fps_sent = filter_repeat_sends(sid, picked, max_repeat=max_repeat)

    html = render_digest_html(filtered, pack=pack)
    subject = _subject(pack)

    return subject, html, len(filtered), fps_sent


def mark_digest_sent(subscriber_id: str, fingerprints_sent: List[str]) -> None:
    """
    Call after successful email send.
    """
    sid = (subscriber_id or "").strip()
    if not sid or not fingerprints_sent:
        return

    bump_sent(subscriber_id=sid, fingerprints=fingerprints_sent)
