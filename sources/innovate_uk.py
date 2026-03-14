# sources/innovate_uk.py

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0"}

GBP_RE = re.compile(r"£\s*([\d,]+(?:\.\d+)?)\s*(million|m)?", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})")

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split()).strip()


def _date_to_iso(s: str) -> str | None:
    # "11 February 2026" -> "2026-02-11"
    s = _clean(s)
    parts = s.split()
    if len(parts) != 3:
        return None

    dd, mon, yyyy = parts
    m = MONTHS.get(mon.lower())
    if not m:
        return None

    try:
        return f"{int(yyyy):04d}-{m:02d}-{int(dd):02d}"
    except Exception:
        return None


def _parse_date(raw: str | None):
    if not raw:
        return None

    s = _clean(raw)
    s_l = s.lower()

    if s_l in {"rolling", "open"}:
        return "rolling"

    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except Exception:
        pass

    iso = _date_to_iso(s)
    if iso:
        try:
            return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
        except Exception:
            pass

    return None


def _parse_gbp_amount(text: str):
    m = GBP_RE.search(text or "")
    if not m:
        return None

    try:
        num = float(m.group(1).replace(",", ""))
    except Exception:
        return None

    is_m = bool(m.group(2))
    if is_m:
        return int(num * 1_000_000)
    return int(num)


def _looks_like_competition(title: str, href: str, blob: str) -> bool:
    full = f"{title} {href} {blob}".lower()

    good = [
        "competition",
        "innovate uk",
        "apply",
        "application",
        "funding",
        "grant",
        "open",
        "closes:",
    ]

    bad = [
        "privacy",
        "cookie",
        "contact",
        "about",
        "terms",
        "accessibility",
        "news",
        "blog",
        "article",
        "press",
        "report",
        "event",
        "webinar",
        "podcast",
        "resource",
        "guidance only",
        "case study",
        "success story",
        "mailto:",
        "#",
    ]

    if any(x in full for x in bad):
        return False

    return any(x in full for x in good)


def _is_expired(deadline_iso: str | None) -> bool:
    if not deadline_iso:
        return False

    parsed = _parse_date(deadline_iso)
    if parsed in (None, "rolling"):
        return False

    return parsed < datetime.now(timezone.utc)


def _extract_eligibility(blob: str) -> str:
    m = re.search(r"### Eligibility\s*(.+?)(###|$)", blob, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return _clean(m.group(1))[:700]


def _extract_deadline_iso(blob: str) -> str | None:
    m = re.search(r"Closes:\s*([0-9]{1,2}\s+[A-Za-z]+\s+\d{4})", blob, flags=re.IGNORECASE)
    if not m:
        return None
    return _date_to_iso(m.group(1))


def _extract_summary(blob: str) -> str:
    if not blob:
        return ""

    summary = blob
    if "### Eligibility" in summary:
        summary = summary.split("### Eligibility", 1)[0]

    summary = _clean(summary)
    if len(summary) > 500:
        summary = summary[:500].rsplit(" ", 1)[0]

    return summary


def fetch_innovate_uk_competitions(search_url: str) -> list[dict]:
    r = requests.get(search_url, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    items: list[dict] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    # Competitions are rendered as repeating blocks with H2 headings.
    for h2 in soup.find_all("h2"):
        a = h2.find("a")
        if not a or not a.get("href"):
            continue

        title = _clean(a.get_text(" ", strip=True))
        href = a["href"].strip()
        if not title or len(title) < 8:
            continue

        full_url = href if href.startswith("http") else urljoin(
            "https://apply-for-innovation-funding.service.gov.uk", href
        )

        if full_url in seen_urls or title.lower() in seen_titles:
            continue

        # Pull nearby sibling text until next block
        block_text: list[str] = []
        node = h2
        for _ in range(20):
            node = node.find_next_sibling()
            if not node:
                break
            if getattr(node, "name", None) == "h2":
                break
            if getattr(node, "name", None) == "hr":
                break

            t = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
            t = _clean(t)
            if t:
                block_text.append(t)

        blob = " ".join(block_text)
        if not blob:
            continue

        if not _looks_like_competition(title, full_url, blob):
            continue

        deadline_iso = _extract_deadline_iso(blob)
        if _is_expired(deadline_iso):
            continue

        summary = _extract_summary(blob)
        eligibility = _extract_eligibility(blob)
        funding_max = _parse_gbp_amount(blob)

        # Minimum quality gate
        if not summary and not eligibility and funding_max is None and not deadline_iso:
            continue

        items.append(
            {
                "title": title,
                "url": full_url,
                "summary": summary,
                "deadline_date": deadline_iso,
                "funding_amount_min": None,
                "funding_amount_max": funding_max,
                "eligibility_notes": eligibility,
            }
        )

        seen_urls.add(full_url)
        seen_titles.add(title.lower())

    # Keep it sane
    return items[:30]