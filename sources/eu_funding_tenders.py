# sources/eu_funding_tenders.py

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GrantMonitor/1.0)"
}


def _clean(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _extract_deadline(text: str) -> Optional[str]:
    if not text:
        return None

    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",
        r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",
        r"\b[A-Za-z]+\s+\d{1,2},\s+\d{4}\b",
        r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+[A-Za-z]+\s+\d{1,2},\s+\d{4}\b",
    ]

    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(0)

    return None


def _parse_date(raw: Optional[str]):
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


def _looks_like_call_page(title: str, href: str) -> bool:
    blob = f"{title} {href}".lower()

    good = [
        "call",
        "topic",
        "proposal",
        "funding",
        "grant",
        "eic",
        "horizon",
        "innovation",
        "digital",
        "open call",
        "call for proposals",
        "application",
        "deadline",
    ]

    bad = [
        "privacy",
        "cookie",
        "contact",
        "about",
        "faq",
        "help",
        "guide",
        "guidance",
        "manual",
        "support",
        "search",
        "login",
        "sign in",
        "terms",
        "accessibility",
        "news",
        "blog",
        "article",
        "press",
        "event",
        "events",
        "webinar",
        "workshop",
        "podcast",
        "video",
        "resource",
        "resources",
        "archive",
        "historical",
        "closed call",
        "closed-topic",
        "closed topic",
        "#",
        "mailto:",
    ]

    if any(x in blob for x in bad):
        return False

    return any(x in blob for x in good)


def _looks_like_live_opportunity(title: str, summary: str, href: str) -> bool:
    blob = f"{title} {summary} {href}".lower()

    good = [
        "apply",
        "application",
        "call for proposals",
        "open call",
        "deadline",
        "funding",
        "grant",
        "topic",
        "proposal",
        "submission",
    ]

    bad = [
        "news",
        "blog",
        "article",
        "event",
        "events",
        "webinar",
        "workshop",
        "podcast",
        "video",
        "resource",
        "resources",
        "press",
        "archive",
        "historical",
        "closed",
        "closed call",
        "results",
    ]

    if any(x in blob for x in bad):
        return False

    return any(x in blob for x in good)


def _is_obviously_stale(title: str, summary: str, deadline: Optional[str]) -> bool:
    if deadline:
        parsed = _parse_date(deadline)
        if parsed != "rolling" and parsed is not None:
            if parsed < datetime.now(timezone.utc):
                return True

    blob = f"{title} {summary}".lower()

    if any(y in blob for y in ["2022", "2023", "2024"]) and any(
        x in blob for x in ["closed", "archive", "historical", "results", "event", "webinar"]
    ):
        return True

    return False


def _best_summary_from_parent(parent, title: str) -> str:
    if not parent:
        return ""

    text = _clean(parent.get_text(" ", strip=True))
    if not text:
        return ""

    if text.startswith(title):
        text = text[len(title):].strip(" -:–|")

    if len(text) > 700:
        text = text[:700].rsplit(" ", 1)[0]

    return text


def fetch_eu_funding_tenders_calls(url: str) -> List[Dict[str, Any]]:
    """
    Hardened parser for EU Funding & Tenders calls/topics pages.
    Extracts likely live call links plus nearby summary and deadline if visible.
    """
    out: List[Dict[str, Any]] = []

    try:
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()
    except Exception as e:
        print("⚠️ EU Funding & Tenders fetch failed:", str(e))
        return out

    soup = BeautifulSoup(res.text, "html.parser")
    seen_urls = set()
    seen_titles = set()

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        title = _clean(a.get_text(" ", strip=True))

        if not href or not title or len(title) < 12:
            continue

        full_url = urljoin(url, href)
        if full_url in seen_urls or title.lower() in seen_titles:
            continue

        if not _looks_like_call_page(title, full_url):
            continue

        parent = a.find_parent(["article", "div", "li", "section", "tr"])
        summary = _best_summary_from_parent(parent, title) if parent else ""

        deadline = _extract_deadline(summary)

        if not _looks_like_live_opportunity(title, summary, full_url):
            continue

        if _is_obviously_stale(title, summary, deadline):
            continue

        out.append(
            {
                "title": title,
                "url": full_url,
                "summary": summary[:600],
                "eligibility_notes": "",
                "deadline_date": deadline,
                "funding_amount_min": None,
                "funding_amount_max": None,
            }
        )

        seen_urls.add(full_url)
        seen_titles.add(title.lower())

    print(f"✅ EU Funding & Tenders parsed {len(out)} calls")
    return out