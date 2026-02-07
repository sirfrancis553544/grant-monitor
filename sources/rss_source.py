import feedparser
from datetime import datetime, timezone
from sources.foerderdatenbank_detail import enrich_foerderdatenbank_program


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def fetch_rss(feed_url: str, source_name: str, default_funder: str, location_scope: str, themes: list[str]):
    """
    Returns list of normalized-ish dicts (still light normalization).
    RSS often doesn't include deadlines, so deadline_date may be None for MVP.
    """
    parsed = feedparser.parse(feed_url)
    out = []
    for e in parsed.entries:
        title = (getattr(e, "title", "") or "").strip()
        link = (getattr(e, "link", "") or "").strip()
        summary = (getattr(e, "summary", "") or "").strip()

        if not title:
            continue

        deadline_date = None
        eligibility_notes = None
        funding_amount_min = None
        funding_amount_max = None
        confidence = 0.6
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

    return out
