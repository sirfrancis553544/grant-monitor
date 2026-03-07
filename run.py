# run.py

from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml

from services.email_resend import send_email as send_html_email
from reminders import get_due_soon, render_reminder_html
from sources.aecf import fetch_aecf_opportunities
from sources.eu_funding_tenders import fetch_eu_funding_tenders_calls

from sources.berlin_ibb import fetch_berlin_ibb_programs
from sources.berlin_ibb_detail import enrich_berlin_ibb_program
from sources.tef import fetch_tef_programme
from sources.eic import fetch_eic_accelerator
from sources.innovate_uk import fetch_innovate_uk_competitions

from db import get_conn, init_db
from sources.rss_source import fetch_rss
from store import upsert_grant
from score import score_grant
from digest import write_outputs

# ✅ Supabase helpers
from services.supabase_client import upsert_grants, grant_fingerprint

DB_PATH = "data/grants.db"


# --- Dedupe helper (canonical URL) ---
def canonical_url(u: str | None) -> str | None:
    if not u:
        return None
    return u.split("?")[0].rstrip("/")


def load_yaml(path: str):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_profiles():
    return {
        "DE": load_yaml("profiles/germany_startup.yaml"),
        "EU": load_yaml("profiles/eu_startup.yaml"),
        "UK": load_yaml("profiles/uk_startup.yaml"),
        "AFRICA": load_yaml("profiles/africa_startup.yaml"),
    }


def _has_column(conn, table: str, col: str) -> bool:
    """
    SQLite schema check. Prevents crashes like:
    'column "last_seen" does not exist'
    """
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        cols = {r[1] for r in rows}  # name is index 1
        return col in cols
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="Send digest email")
    ap.add_argument(
        "--remind", action="store_true", help="Send deadline reminders (7/14 days)"
    )
    args = ap.parse_args()

    profiles = load_profiles()
    sources_cfg = load_yaml("sources.yaml")

    BONUS_SOURCES = {"tef_entrepreneurship", "eic_accelerator", "innovate_uk_competitions"}

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

        # --- Berlin IBB programs (custom source) ---
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

                # --- Enrichment from detail page ---
                if (
                    g.get("source") == "berlin_ibb_programs"
                    and g.get("url", "").startswith("https://www.ibb.de/de/foerderprogramme/")
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

                items.append(g)

        # --- TEF Entrepreneurship ---
        elif s.get("id") == "tef_entrepreneurship":
            raw_items = fetch_tef_programme(
                s["url"], programme_url=s.get("programme_url")
            ) or []
            for it in raw_items:
                g = {
                    "title": it.get("title"),
                    "url": it.get("url"),
                    "source": s.get("id"),
                    "funder": s.get("funder"),
                    "location_scope": s.get("location_scope"),
                    "themes": s.get("themes") or [],
                    "summary": it.get("summary") or "",
                    "eligibility_notes": it.get("eligibility_notes") or "",
                    "deadline_date": it.get("deadline_date"),
                    "funding_amount_min": it.get("funding_amount_min"),
                    "funding_amount_max": it.get("funding_amount_max"),
                }
                if g["title"] and g["url"]:
                    items.append(g)
                    
        # --- AECF Opportunities ---
        elif s.get("id") == "aecf_opportunities":
            raw_items = fetch_aecf_opportunities(s["url"]) or []
            for it in raw_items:
                g = {
                    "title": it.get("title"),
                    "url": it.get("url"),
                    "source": s.get("id"),
                    "funder": s.get("funder"),
                    "location_scope": s.get("location_scope"),
                    "themes": s.get("themes") or [],
                    "summary": it.get("summary") or "",
                    "eligibility_notes": it.get("eligibility_notes") or "",
                    "deadline_date": it.get("deadline_date"),
                    "funding_amount_min": it.get("funding_amount_min"),
                    "funding_amount_max": it.get("funding_amount_max"),
                }
                if g["title"] and g["url"]:
                    items.append(g)

        # --- EU Funding & Tenders ---
        elif s.get("id") == "eu_funding_tenders_calls":
            raw_items = fetch_eu_funding_tenders_calls(s["url"]) or []
            for it in raw_items:
                g = {
                    "title": it.get("title"),
                    "url": it.get("url"),
                    "source": s.get("id"),
                    "funder": s.get("funder"),
                    "location_scope": s.get("location_scope"),
                    "themes": s.get("themes") or [],
                    "summary": it.get("summary") or "",
                    "eligibility_notes": it.get("eligibility_notes") or "",
                    "deadline_date": it.get("deadline_date"),
                    "funding_amount_min": it.get("funding_amount_min"),
                    "funding_amount_max": it.get("funding_amount_max"),
                }
                if g["title"] and g["url"]:
                    items.append(g)

        # --- EIC Accelerator ---
        elif s.get("id") == "eic_accelerator":
            raw_items = fetch_eic_accelerator(s["url"]) or []
            for it in raw_items:
                g = {
                    "title": it.get("title"),
                    "url": it.get("url"),
                    "source": s.get("id"),
                    "funder": s.get("funder"),
                    "location_scope": s.get("location_scope"),
                    "themes": s.get("themes") or [],
                    "summary": it.get("summary") or "",
                    "eligibility_notes": it.get("eligibility_notes") or "",
                    "deadline_date": it.get("deadline_date"),
                    "funding_amount_min": it.get("funding_amount_min"),
                    "funding_amount_max": it.get("funding_amount_max"),
                }
                if g["title"] and g["url"]:
                    items.append(g)

        # --- Innovate UK competitions ---
        elif s.get("id") == "innovate_uk_competitions":
            raw_items = fetch_innovate_uk_competitions(s["url"]) or []
            for it in raw_items:
                g = {
                    "title": it.get("title"),
                    "url": it.get("url"),
                    "source": s.get("id"),
                    "funder": s.get("funder"),
                    "location_scope": s.get("location_scope"),
                    "themes": s.get("themes") or [],
                    "summary": it.get("summary") or "",
                    "eligibility_notes": it.get("eligibility_notes") or "",
                    "deadline_date": it.get("deadline_date"),
                    "funding_amount_min": it.get("funding_amount_min"),
                    "funding_amount_max": it.get("funding_amount_max"),
                }
                if g["title"] and g["url"]:
                    items.append(g)

        # --- RSS (default) ---
        else:
            if s.get("type") != "rss":
                continue

            items = fetch_rss(
                feed_url=s["url"],
                source_name=s.get("name") or s.get("id") or "unknown_source",
                default_funder=s.get("funder") or s.get("name") or s.get("id") or "unknown_funder",
                location_scope=s.get("location_scope", "DE"),
                themes=s.get("themes", []),
            )

        for g in items:
            total += 1
            ins, chg = upsert_grant(conn, g)
            inserted += int(ins)
            changed += int(chg)

    conn.commit()

    # ------------------------------------
    # 2) Pull recent items and normalize
    #    ✅ FIX: don't ORDER BY last_seen if column doesn't exist
    # ------------------------------------
    order_col = "last_seen" if _has_column(conn, "grants", "last_seen") else "date_found"
    rows = conn.execute(
        "SELECT title, funder, summary, eligibility_notes, deadline_date, "
        "funding_amount_min, funding_amount_max, location_scope, themes, url, source, date_found, confidence_score "
        f"FROM grants ORDER BY {order_col} DESC LIMIT 500"
    ).fetchall()

    normalized: list[dict] = []
    for r in rows:
        title = r[0]
        url = r[9]

        gg = {
            "title": title,
            "funder": r[1],
            "summary": r[2],
            "eligibility_notes": r[3],
            "deadline_date": r[4],
            "funding_amount_min": r[5],
            "funding_amount_max": r[6],
            "location_scope": r[7],
            "themes": r[8],
            "url": url,
            "source": r[10],
            "date_found": r[11],
            "confidence_score": r[12],
        }

        # ✅ Stable dedupe fingerprint (title + url)
        if title and url:
            gg["fingerprint"] = grant_fingerprint(title, url)

        normalized.append(gg)

    # ------------------------------------
    # 3) Score per profile and build sections
    # ------------------------------------

    STORE_LIMIT_PER_PACK = 200

    sections: dict[str, list[dict]] = {}
    store_sections: dict[str, list[dict]] = {}

    for key, prof in profiles.items():
        scored = []
        for g in normalized:
            sc, why = score_grant(g, prof)
            gg = dict(g)
            gg["_score"] = sc
            gg["_why"] = why
            scored.append(gg)

        # sort by score
        scored.sort(key=lambda x: x.get("_score", 0), reverse=True)

        # Deduplicate by canonical URL
        deduped = {}
        for g in scored:
            k = canonical_url(g.get("url")) or (g.get("title") or "").strip().lower()
            if k not in deduped or g.get("_score", 0) > deduped[k].get("_score", 0):
                deduped[k] = g

        scored = list(deduped.values())
        scored.sort(key=lambda x: x.get("_score", 0), reverse=True)

        # small list → email output
        top_n = int(prof.get("top_n", 10))
        sections[key] = scored[:top_n]

        # big list → storage pool
        store_sections[key] = scored[:STORE_LIMIT_PER_PACK]


    # ------------------------------------
    # 4) Apply your “main vs bonus” rule
    # ------------------------------------

    sections["DE"] = [g for g in sections.get("DE", []) if g.get("source") not in BONUS_SOURCES]
    store_sections["DE"] = [g for g in store_sections.get("DE", []) if g.get("source") not in BONUS_SOURCES]

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
                if not g.get("fingerprint") and g.get("title") and g.get("url"):
                    g["fingerprint"] = grant_fingerprint(g["title"], g["url"])

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

# .venv\Scripts\activate
# python run.py --send