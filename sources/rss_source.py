import re
from datetime import datetime, timezone
from html import unescape

import feedparser

from sources.foerderdatenbank_detail import enrich_foerderdatenbank_program

GOOD_TERMS = [
    "grant", "grants", "funding", "fund", "funds", "programme", "program",
    "call", "call for proposals", "call for applications", "opportunity", "opportunities",
    "competition", "challenge", "award", "scheme", "application", "apply",
    "eligibility", "deadline", "research", "innovation", "sme", "startup",
    "small business", "technology", "digital", "horizon europe", "ukri", "sbir", "sttr",
    "förderung", "zuschuss", "förderprogramm", "darlehen",
]

BAD_TERMS = [
    "news", "event", "events", "conference", "webinar", "workshop", "blog",
    "article", "press release", "speech", "president", "board approves", "board meeting",
    "annual meeting", "report", "newsletter", "story", "case study", "video",
    "podcast", "interview", "celebrates", "visit", "visits", "statement",
]

HARD_BAD_TITLES = [
    "read more", "learn more", "find out more", "click here", "home", "contact",
    "newsletter", "subscribe", "events", "news",
]


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(value):
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split()).strip()


def _score_rss_item(title: str, summary: str, themes: list[str]) -> int:
    text = f" {title} {summary} {' '.join(themes or [])} ".lower()
    score = 0
    for term in GOOD_TERMS:
        if term in text:
            score += 4
    for term in BAD_TERMS:
        if term in text:
            score -= 3
    if any(term in text for term in ["deadline", "apply", "application", "eligibility"]):
        score += 6
    if any(term in text for term in ["call for proposals", "call for applications", "funding opportunity"]):
        score += 10
    return score


def _keep_rss_item(title: str, summary: str, themes: list[str]) -> bool:
    normalized_title = title.lower().strip()
    if not normalized_title or len(normalized_title) < 8:
        return False
    if normalized_title in HARD_BAD_TITLES:
        return False

    text = f" {title} {summary} ".lower()
    has_core_signal = any(term in text for term in [
        "grant", "funding", "fund", "call", "proposal", "application", "competition", "opportunity",
        "programme", "program", "award", "scheme", "research", "innovation", "förderung", "zuschuss",
    ])

    # Match the main scraped-result behavior: only reject obvious noise.
    # If it has a funding/opportunity signal, keep it even when it also looks like a news/update item.
    if has_core_signal:
        return True

    # For broad feeds, keep weak but plausible source-themed items and let the shared quality gate score them later.
    return _score_rss_item(title, summary, themes) >= 2


def fetch_rss(feed_url: str, source_name: str, default_funder: str, location_scope: str, themes: list[str]):
    """
    Returns list of normalized-ish dicts (still light normalization).
    RSS often doesn't include deadlines, so deadline_date may be None for MVP.
    """
    parsed = feedparser.parse(feed_url)
    out = []
    skipped = 0
    for e in parsed.entries:
        title = _clean(getattr(e, "title", "") or "")
        link = (getattr(e, "link", "") or "").strip()
        summary = _clean(getattr(e, "summary", "") or getattr(e, "description", "") or "")

        if not _keep_rss_item(title, summary, themes):
            skipped += 1
            continue

        deadline_date = None
        eligibility_notes = None
        funding_amount_min = None
        funding_amount_max = None
        confidence = 0.6 + min(0.25, max(0, _score_rss_item(title, summary, themes)) / 100)
        raw_snippet = summary[:4000] if summary else None

        if link and "foerderdatenbank.de" in link:
            try:
                extra = enrich_foerderdatenbank_program(link)
                deadline_date = extra.get("deadline_date")
                eligibility_notes = extra.get("eligibility_notes")
                funding_amount_min = extra.get("funding_amount_min")
                funding_amount_max = extra.get("funding_amount_max")
                raw_snippet = extra.get("raw_snippet") or raw_snippet
                confidence = min(1.0, confidence + float(extra.get("confidence_boost") or 0.0))
            except Exception:
                # keep RSS-only if page fetch/parsing fails
                pass

        out.append({
            "title": title,
            "funder": default_funder,
            "summary": summary[:2000] if summary else None,
            "eligibility_notes": eligibility_notes,
            "deadline_date": deadline_date,
            "funding_amount_min": funding_amount_min,
            "funding_amount_max": funding_amount_max,
            "location_scope": location_scope,
            "themes": themes,
            "url": link or None,
            "source": source_name,
            "date_found": _now_iso(),
            "confidence_score": confidence,
            "raw_snippet": raw_snippet,
        })

    if skipped:
        print(f"ℹ️ RSS filtered {skipped} obvious noisy items from {source_name}")
    return out
