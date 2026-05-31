from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0"}
GOOD_TERMS = ["grant", "fund", "funding", "finance", "support", "programme", "program", "opportunity", "competition", "apply", "application"]
BAD_TERMS = ["privacy", "cookie", "terms", "accessibility", "contact", "login", "sign in", "newsletter", "news", "blog", "event", "webinar", "case study"]
MONEY_RE = re.compile(r"(?:£|€|\$)\s*([\d,]+(?:\.\d+)?)\s*(million|m|k)?", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})")


def _clean(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def _money_to_number(text: str) -> int | None:
    m = MONEY_RE.search(text or "")
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except Exception:
        return None
    suffix = (m.group(2) or "").lower()
    if suffix in {"million", "m"}:
        value *= 1_000_000
    elif suffix == "k":
        value *= 1_000
    return int(value)


def _extract_deadline(text: str) -> str | None:
    lower = text.lower()
    if "rolling" in lower or "ongoing" in lower:
        return "rolling"
    match = DATE_RE.search(text)
    return match.group(1) if match else None


def _looks_relevant(title: str, url: str, text: str) -> bool:
    blob = f"{title} {url} {text}".lower()
    if any(term in blob for term in BAD_TERMS):
        return False
    return any(term in blob for term in GOOD_TERMS)


def fetch_generic_grant_page(url: str, max_items: int = 25) -> list[dict]:
    response = requests.get(url, headers=UA, timeout=25)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")

    items: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        title = _clean(a.get_text(" ", strip=True))
        if not href or not title or len(title) < 8:
            continue
        full_url = href if href.startswith("http") else urljoin(url, href)
        if full_url in seen:
            continue

        parent = a.find_parent(["article", "li", "section", "div"])
        block = _clean(parent.get_text(" ", strip=True) if parent else title)
        if not _looks_relevant(title, full_url, block):
            continue

        summary = block
        if len(summary) > 500:
            summary = summary[:500].rsplit(" ", 1)[0]

        items.append({
            "title": title,
            "url": full_url,
            "summary": summary,
            "deadline_date": _extract_deadline(block),
            "funding_amount_min": None,
            "funding_amount_max": _money_to_number(block),
            "eligibility_notes": "",
        })
        seen.add(full_url)
        if len(items) >= max_items:
            break

    return items
