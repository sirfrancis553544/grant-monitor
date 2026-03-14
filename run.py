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
    """
    Keep ranked order, but limit how many items from the same source
    can appear in the final digest list.
    """
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
    """
    Final quality gate before anything is scored/stored for digest output.

    Goal:
    - keep real funding/application opportunities
    - reject recap/news/resource/blog/event pages
    """
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
        "podcast",
        "press release",
        "portfolio company",
        "success story",
        "meet the cohort",
        "cohort spotlight",
        "conference",
        "summit",
    ]

    if any(term in blob for term in bad_terms):
        return False

    return any(term in blob for term in good_terms)


def _is_stale_or_expired(g: dict) -> bool:
    """
    Reject obviously expired or stale content.
    """
    deadline = g.get("deadline_date")
    parsed = _parse_date(deadline)

    if parsed == "rolling":
        return False

    if parsed is not None:
        return parsed < datetime.now(timezone.utc)

    blob = _text_blob(g)

    old_year_terms = ["2022", "2023", "2024"]
    stale_context_terms = [
        "bootcamp",
        "highlight",
        "highlights",
        "event",
        "events",
        "resource",
        "resources",
        "story",
        "case study",
        "workshop",
        "webinar",
        "video",
    ]

    if any(y in blob for y in old_year_terms) and any(t in blob for t in stale_context_terms):
        return True

    return False


def _has_minimum_signal(g: dict) -> bool:
    """
    Avoid sending garbage rows that have almost no usable metadata.
    """
    title = (g.get("title") or "").strip()
    url = (g.get("url") or "").strip()
    summary = (g.get("summary") or "").strip()
    scope = (g.get("location_scope") or "").strip()

    if not title or not url:
        return False

    if len(title) < 8:
        return False

    if url.startswith("#") or url.startswith("mailto:"):
        return False

    useful_fields = 0
    if summary:
        useful_fields += 1
    if scope:
        useful_fields += 1
    if g.get("deadline_date"):
        useful_fields += 1
    if g.get("funding_amount_max") is not None or g.get("funding_amount_min") is not None:
        useful_fields += 1
    if g.get("eligibility_notes"):
        useful_fields += 1

    return useful_fields >= 1


def validate_grant(g: dict) -> bool:
    """
    Final validation layer used across all packs before scoring.
    """
    if not _has_minimum_signal(g):
        return False

    if _is_stale_or_expired(g):
        return False

    if not _looks_like_actionable_opportunity(g):
        return False

    return True


def is_pack_eligible(g: dict, pack: str) -> bool:
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
        source in {"eu_funding_tenders_calls", "eic_accelerator", "tef_entrepreneurship"}
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
        return is_africa and not is_germany and not (
            is_uk and not has_any(
                "africa",
                "african",
                "sub-saharan africa",
                "african entrepreneurs",
                "54 african countries",
                "oda eligible countries in sub-saharan africa",
            )
        ) and not (
            is_eu and not has_any(
                "africa",
                "african",
                "sub-saharan africa",
                "african entrepreneurs",
                "54 african countries",
            )
        )

    return False


def _base_grant(source_cfg: dict, item: dict) -> dict:
    return {
        "title": item.get("title"),
        "url": item.get("url"),
        "source": source_cfg.get("id") or source_cfg.get("name") or "unknown_source",
        "funder": source_cfg.get("funder"),
        "location_scope": source_cfg.get("location_scope"),
        "themes": source_cfg.get("themes") or [],
        "summary": item.get("summary") or "",
        "eligibility_notes": item.get("eligibility_notes") or "",
        "deadline_date": item.get("deadline_date"),
        "funding_amount_min": item.get("funding_amount_min"),
        "funding_amount_max": item.get("funding_amount_max"),
    }


def _ensure_fingerprint(g: dict) -> None:
    if g.get("fingerprint"):
        return

    title = (g.get("title") or "").strip()
    url = (g.get("url") or "").strip()
    if not title or not url:
        return

    g["fingerprint"] = grant_fingerprint(
        title,
        g.get("funder"),
        g.get("deadline_date"),
        url,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="Send digest email")
    ap.add_argument(
        "--remind", action="store_true", help="Send deadline reminders (7/14 days)"
    )
    args = ap.parse_args()

    profiles = load_profiles()
    sources_cfg = load_yaml("sources.yaml")

    BONUS_SOURCES = {
        "tef_entrepreneurship",
        "eic_accelerator",
        "innovate_uk_competitions",
    }

    conn = get_conn(DB_PATH)
    init_db(conn)

    inserted = changed = total = 0

    # -----------------------
    # 1) Ingest all sources
    # -----------------------
    for s in sources_cfg.get("sources", []):
        if s.get("enabled") is False:
            continue

        items: list[dict] = []

        if s.get("id") == "berlin_ibb_programs":
            raw_items = fetch_berlin_ibb_programs(s["url"]) or []
            for it in raw_items:
                g = {
                    "title": it.get("title"),
                    "url": it.get("url"),
                    "source": s.get("id") or s.get("name") or "berlin_ibb_programs",
                    "funder": s.get("funder") or "Investitionsbank Berlin (IBB)",
                    "location_scope": s.get("location_scope") or "Berlin",
                    "themes": s.get("themes") or [],
                    "summary": it.get("summary", "") or "",
                    "eligibility_notes": it.get("eligibility_notes", "") or "",
                    "deadline_date": it.get("deadline_date"),
                    "funding_amount_min": it.get("funding_amount_min"),
                    "funding_amount_max": it.get("funding_amount_max"),
                }

                if not (g["title"] and g["url"]):
                    continue

                if (
                    g.get("source") == "berlin_ibb_programs"
                    and g.get("url", "").startswith(
                        "https://www.ibb.de/de/foerderprogramme/"
                    )
                ):
                    extra = enrich_berlin_ibb_program(g["url"]) or {}

                    if extra.get("deadline_type") == "rolling":
                        g["deadline_date"] = "rolling"
                    elif extra.get("deadline_date"):
                        g["deadline_date"] = extra["deadline_date"]

                    if extra.get("eligibility_notes"):
                        g["eligibility_notes"] = extra["eligibility_notes"]

                    if extra.get("funding_amount_max") is not None:
                        g["funding_amount_max"] = extra["funding_amount_max"]

                    if extra.get("funding_amount_min") is not None:
                        g["funding_amount_min"] = extra["funding_amount_min"]

                    if extra.get("summary"):
                        g["summary"] = extra["summary"]

                _ensure_fingerprint(g)
                items.append(g)

        elif s.get("id") == "tef_entrepreneurship":
            raw_items = fetch_tef_programme(
                s["url"], programme_url=s.get("programme_url")
            ) or []
            for it in raw_items:
                g = _base_grant(s, it)
                if g["title"] and g["url"]:
                    _ensure_fingerprint(g)
                    items.append(g)

        elif s.get("id") == "aecf_opportunities":
            raw_items = fetch_aecf_opportunities(s["url"]) or []
            for it in raw_items:
                g = _base_grant(s, it)
                if g["title"] and g["url"]:
                    _ensure_fingerprint(g)
                    items.append(g)

        elif s.get("id") == "eu_funding_tenders_calls":
            raw_items = fetch_eu_funding_tenders_calls(s["url"]) or []
            for it in raw_items:
                g = _base_grant(s, it)
                if g["title"] and g["url"]:
                    _ensure_fingerprint(g)
                    items.append(g)

        elif s.get("id") == "eic_accelerator":
            raw_items = fetch_eic_accelerator(s["url"]) or []
            for it in raw_items:
                g = _base_grant(s, it)
                if g["title"] and g["url"]:
                    _ensure_fingerprint(g)
                    items.append(g)

        elif s.get("id") == "gsma_innovation_fund":
            raw_items = fetch_gsma_innovation_fund(s["url"]) or []
            for it in raw_items:
                g = _base_grant(s, it)
                if g["title"] and g["url"]:
                    _ensure_fingerprint(g)
                    items.append(g)

        elif s.get("id") == "innovate_uk_competitions":
            raw_items = fetch_innovate_uk_competitions(s["url"]) or []
            for it in raw_items:
                g = _base_grant(s, it)
                if g["title"] and g["url"]:
                    _ensure_fingerprint(g)
                    items.append(g)

        else:
            if s.get("type") != "rss":
                continue

            items = fetch_rss(
                feed_url=s["url"],
                source_name=s.get("name") or s.get("id") or "unknown_source",
                default_funder=s.get("funder")
                or s.get("name")
                or s.get("id")
                or "unknown_funder",
                location_scope=s.get("location_scope", "DE"),
                themes=s.get("themes", []),
            )

            for g in items:
                _ensure_fingerprint(g)

        for g in items:
            total += 1
            ins, chg = upsert_grant(conn, g)
            inserted += int(ins)
            changed += int(chg)

    conn.commit()

    # ------------------------------------
    # 2) Pull recent items and normalize
    # ------------------------------------
    order_col = "last_seen" if _has_column(conn, "grants", "last_seen") else "date_found"
    rows = conn.execute(
        "SELECT title, funder, summary, eligibility_notes, deadline_date, "
        "funding_amount_min, funding_amount_max, location_scope, themes, url, source, date_found, confidence_score "
        f"FROM grants ORDER BY {order_col} DESC LIMIT 500"
    ).fetchall()

    normalized: list[dict] = []
    rejected_quality = 0

    for r in rows:
        title = r[0]
        url = r[9]
        themes_value = _normalize_themes(r[8])

        gg = {
            "title": title,
            "funder": r[1],
            "summary": r[2],
            "eligibility_notes": r[3],
            "deadline_date": r[4],
            "funding_amount_min": r[5],
            "funding_amount_max": r[6],
            "location_scope": r[7],
            "themes": themes_value,
            "url": url,
            "source": r[10],
            "date_found": r[11],
            "confidence_score": r[12],
        }

        if title and url:
            gg["fingerprint"] = grant_fingerprint(
                title,
                gg.get("funder"),
                gg.get("deadline_date"),
                url,
            )

        if not validate_grant(gg):
            rejected_quality += 1
            continue

        normalized.append(gg)

    # ------------------------------------
    # 3) Hard filter by pack, then score
    # ------------------------------------
    STORE_LIMIT_PER_PACK = 200

    sections: dict[str, list[dict]] = {}
    store_sections: dict[str, list[dict]] = {}

    for key, prof in profiles.items():
        eligible = [g for g in normalized if is_pack_eligible(g, key)]

        scored: list[dict] = []
        for g in eligible:
            sc, why = score_grant(g, prof)
            gg = dict(g)
            gg["_score"] = sc
            gg["_why"] = why
            scored.append(gg)

        scored = [g for g in scored if g.get("_score", 0) > 0]
        scored.sort(key=lambda x: x.get("_score", 0), reverse=True)

        deduped: dict[str, dict] = {}
        for g in scored:
            k = canonical_url(g.get("url")) or (g.get("title") or "").strip().lower()
            if k not in deduped or g.get("_score", 0) > deduped[k].get("_score", 0):
                deduped[k] = g

        scored = list(deduped.values())
        scored.sort(key=lambda x: x.get("_score", 0), reverse=True)

        capped_for_email = apply_source_cap(scored, max_per_source=3)

        top_n = int(prof.get("top_n", 10))
        sections[key] = capped_for_email[:top_n]

        capped_for_store = apply_source_cap(scored, max_per_source=10)
        store_sections[key] = capped_for_store[:STORE_LIMIT_PER_PACK]

    # ------------------------------------
    # 4) Apply main vs bonus rule
    # ------------------------------------
    sections["DE"] = [
        g for g in sections.get("DE", []) if g.get("source") not in BONUS_SOURCES
    ]
    store_sections["DE"] = [
        g for g in store_sections.get("DE", []) if g.get("source") not in BONUS_SOURCES
    ]

    sections.setdefault("EU", [])
    sections.setdefault("UK", [])
    sections.setdefault("AFRICA", [])

    store_sections.setdefault("EU", [])
    store_sections.setdefault("UK", [])
    store_sections.setdefault("AFRICA", [])

    # ------------------------------------
    # 4.5) Upsert larger pool into Supabase
    # ------------------------------------
    try:
        supa_total = 0
        for pack, items in store_sections.items():
            for g in items:
                _ensure_fingerprint(g)

            supa_total += upsert_grants(items, pack=pack)

        print(f"✅ Supabase upsert done: {supa_total} rows attempted (store pool).")

    except Exception as e:
        print("⚠️ Supabase upsert skipped/failed:", str(e))

    # ------------------------------------
    # 5) Write outputs
    # ------------------------------------
    json_path, csv_path, html_path = write_outputs(sections, out_dir="data")
    digest_html = Path(html_path).read_text(encoding="utf-8")

    # ------------------------------------
    # 6) Email sending + reminders
    # ------------------------------------
    if args.send:
        to_email = os.environ.get("GM_TO", "me")
        send_html_email(subject="Grant Digest", html=digest_html, to_email=to_email)
        print("✅ Sent digest email to", to_email)

    if args.remind:
        for days in (14, 7):
            due_items = get_due_soon(DB_PATH, days)
            html = render_reminder_html(due_items, days)
            if html:
                to_email = os.environ.get("GM_TO", "me")
                send_html_email(
                    subject=f"Grant deadlines in the next {days} days",
                    html=html,
                    to_email=to_email,
                )
                print(f"✅ Sent {days}-day reminder to", to_email)

    # ------------------------------------
    # 7) Console summary
    # ------------------------------------
    print("Done.")
    print(f"Ingested items: {total} | inserted: {inserted} | changed: {changed}")
    print(f"Rejected by quality gate: {rejected_quality}")
    print(
        "Digest sections:",
        f"DE={len(sections.get('DE', []))}",
        f"EU={len(sections.get('EU', []))}",
        f"UK={len(sections.get('UK', []))}",
        f"AFRICA={len(sections.get('AFRICA', []))}",
    )
    print(f"Outputs: {json_path}, {csv_path}, {html_path}")


if __name__ == "__main__":
    main()

# Windows:
#   .venv\Scripts\activate
#   python run.py
#   python run.py --send
