from __future__ import annotations

from pathlib import Path
from typing import List, Tuple
import yaml

from score import score_grant
from digest import render_digest_html
from store import get_all_grants
from services.supabase_client import get_sent_counts, bump_sent, grant_fingerprint
from utils.deadline_radar import deadline_badge
from utils.application_effort import estimate_application_effort

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


def _themes_to_text(themes) -> str:
    if not themes:
        return ""
    if isinstance(themes, str):
        return themes
    if isinstance(themes, (list, tuple, set)):
        return " ".join(str(x) for x in themes if x)
    return str(themes)


def _text_blob(g: dict) -> str:
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


def is_pack_eligible(g: dict, pack: str) -> bool:
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
        return any(t.lower() in text for t in terms)

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


def pick_top(grants: List[dict], profile: dict, limit: int = 20) -> List[dict]:
    """
    Score and pick top grants for a profile.
    Keeps only score > 0 and enriches grants for rendering.
    """
    scored: List[dict] = []

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
        fps = [fp for g in grants if (fp := _ensure_fingerprint(g))]
        return grants, fps

    fps: List[str] = []
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

    Applies:
      - hard pack eligibility filtering
      - score-based ranking
      - fit score enrichment
      - application effort enrichment
      - deadline radar enrichment
      - duplicate suppression
    """
    pack = pack.upper().strip()
    if pack not in PACK_TO_PROFILE:
        raise ValueError(f"Unknown pack: {pack}")

    profile = load_profile(pack)

    grants = get_all_grants()
    eligible = [g for g in grants if is_pack_eligible(g, pack)]

    top_n = min(int(profile.get("top_n", 6)), 6)
    picked = pick_top(eligible, profile, limit=top_n)

    sid = (subscriber_id or "").strip()
    filtered, fps_sent = filter_repeat_sends(sid, picked, max_repeat=max_repeat)

    html = render_digest_html(filtered, pack=pack)

    subject = f"RubixScout — {pack} Funding Digest"
    return subject, html, len(filtered), fps_sent


def mark_digest_sent(subscriber_id: str, fingerprints_sent: List[str]) -> None:
    """
    Call after successful email send.
    """
    if not subscriber_id or not fingerprints_sent:
        return
    bump_sent(subscriber_id=subscriber_id, fingerprints=fingerprints_sent)