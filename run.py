from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from db import get_conn, init_db
from digest import write_outputs
from reminders import get_due_soon, render_reminder_html
from score import score_grant
from services.email_resend import send_email as send_html_email
from services.supabase_client import grant_fingerprint, upsert_grants
from sources.aecf import fetch_aecf_opportunities
from sources.berlin_ibb import fetch_berlin_ibb_programs
from sources.berlin_ibb_detail import enrich_berlin_ibb_program
from sources.eic import fetch_eic_accelerator
from sources.eu_funding_tenders import fetch_eu_funding_tenders_calls
from sources.gsma import fetch_gsma_innovation_fund
from sources.innovate_uk import fetch_innovate_uk_competitions
from sources.rss_source import fetch_rss
from sources.tef import fetch_tef_programme
from store import upsert_grant

DB_PATH = "data/grants.db"

CREATOR_TERMS = {
    "creator economy",
    "content creator",
    "creator",
    "podcast",
    "podcaster",
    "social media",
    "influencer",
    "digital media",
    "media startup",
    "creator tools",
    "creator platform",
    "digital content",
    "online media",
    "youtube",
    "tiktok",
    "streaming",
    "audience growth",
    "media innovation",
    "creative technology",
    "creative industries",
}


def canonical_url(u: str | None) -> str | None:
    if not u:
        return None
    return u.split("?")[0].rstrip("/")


def load_yaml(path: str) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_profiles() -> dict[str, dict[str, Any]]:
    return {
        "DE": load_yaml("profiles/germany_startup.yaml"),
        "EU": load_yaml("profiles/eu_startup.yaml"),
        "UK": load_yaml("profiles/uk_startup.yaml"),
        "AFRICA": load_yaml("profiles/africa_startup.yaml"),
    }


def apply_source_cap(items: list[dict], max_per_source: int = 3) -> list[dict]:
    out: list[dict] = []
    counts: dict[str, int] = {}

    for g in items:
        source = (g.get("source") or "unknown").strip()
        current = counts.get(source, 0)

        if current >= max_per_source:
            continue

        out.append(g)
        counts[source] = current + 1

    return out


def _has_column(conn, table: str, col: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        cols = {r[1] for r in rows}
        return col in cols
    except Exception:
        return False


def _normalize_themes(value: Any) -> list[str]:
    if not value:
        return []

    if isinstance(value, list):
        return [str(x) for x in value if x]

    if isinstance(value, (tuple, set)):
        return [str(x) for x in value if x]

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
        except Exception:
            pass
        return [raw]

    return [str(value)]


def _themes_to_text(themes: Any) -> str:
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


def _contains_creator_terms(blob: str) -> bool:
    return any(term in blob for term in CREATOR_TERMS)


def _parse_date(raw: Any):
    if not raw:
        return None

    s = str(raw).strip()
    s_l = s.lower()

    if s_l in {"rolling", "open"}:
        return "rolling"

    s = re.sub(
        r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+",
        "",
        s,
        flags=re.IGNORECASE,
    ).strip()

    fmts = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d %B %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %b %Y",
    ]

    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _looks_like_actionable_opportunity(g: dict) -> bool:
    blob = _text_blob(g)

    good_terms = [
        "grant",
        "fund",
        "funding",
        "apply",
        "application",
        "open call",
        "call for applications",
        "call for proposals",
        "competition",
        "challenge fund",
        "innovation fund",
        "request for proposals",
        "rfp",
        "deadline",
        "eligibility",
        "submit",
        "co-financing",
    ]

    bad_terms = [
        "bootcamp",
        "highlights",
        "highlight",
        "event",
        "events",
        "news",
        "blog",
        "article",
        "story",
        "case study",
        "report",
        "resource",
        "resources",
        "video",
        "webinar",
        "workshop",
        "press release",
        "portfolio company",
        "success story",
        "meet the cohort",
        "cohort spotlight",
        "conference",
        "summit",
    ]

    if any(term in blob for term in bad_terms):
        if not (
            _contains_creator_terms(blob)
            and any(term in blob for term in good_terms)
        ):
            return False

    return any(term in blob for term in good_terms)
