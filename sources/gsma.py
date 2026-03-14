# sources/gsma.py

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


def _extract_amount_max(text: str) -> Optional[float]:
    if not text:
        return None

    vals = []

    for m in re.finditer(
        r"(?:£|\$|€|USD|EUR|GBP)?\s*([\d]+(?:[.,]\d+)?)\s*(million|m)\b",
        text,
        flags=re.IGNORECASE,
    ):
        try:
            vals.append(float(m.group(1).replace(",", "")) * 1_000_000)
        except Exception:
            pass

    for m in re.finditer(
        r"(?:£|\$|€|USD|EUR|GBP)\s*([\d]{1,3}(?:[,\s]\d{3})*(?:[.,]\d+)?)",
        text,
        flags=re.IGNORECASE,
    ):
        try:
            vals.append(float(m.group(1).replace(",", "").replace(" ", "")))
        except Exception:
            pass

    return max(vals) if vals else None


def _looks_like_fund_page(title: str, href: str) -> bool:
    t = title.lower()
    h = href.lower()
    blob = f"{t} {h}"

    good = [
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
    ]

    bad = [
        "privacy",
        "cookie",
        "contact",
        "about",
        "team",
        "careers",
        "facebook",
        "linkedin",
        "instagram",
        "youtube",
        "podcast",
        "report",
        "newsroom",
        "press",
        "resource",
        "resources",
        "bootcamp",
        "highlights",
        "highlight",
        "event",
        "events",
        "workshop",
        "webinar",
        "video",
        "article",
        "news",
        "blog",
        "case study",
        "story",
        "success story",
        "portfolio",
        "meet the cohort",
        "cohort spotlight",
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
        "call for applications",
        "call for proposals",
        "open call",
        "deadline",
        "grant",
        "funding",
        "competition",
        "innovation fund",
        "request for proposals",
        "rfp",
    ]

    bad = [
        "bootcamp",
        "highlights",
        "highlight",
        "event",
        "events",
        "news",
        "blog",
        "resource",
        "resources",
        "video",
        "workshop",
        "webinar",
        "article",
        "report",
        "story",
        "case study",
    ]

    if any(x in blob for x in bad):
        return False

    return any(x in blob for x in good)


def _is_obviously_stale(title: str, summary: str, deadline: Optional[str]) -> bool:
    blob = f"{title} {summary}".lower()

    if deadline:
        parsed = _parse_date(deadline)
        if parsed != "rolling" and parsed is not None:
            now = datetime.now(timezone.utc)
            if parsed < now:
                return True

    old_year_terms = ["2022", "2023", "2024"]
    stale_content_terms = [
        "bootcamp",
        "highlight",
        "highlights",
        "event",
        "events",
        "workshop",
        "video",
        "resource",
        "resources",
        "blog",
        "article",
        "story",
    ]

    if any(y in blob for y in old_year_terms) and any(x in blob for x in stale_content_terms):
        return True

    return False


def _summary_from_parent(parent, title: str) -> str:
    if not parent:
        return ""
    text = _clean(parent.get_text(" ", strip=True))
    if text.startswith(title):
        text = text[len(title):].strip(" -:–|")
    return text[:700]


def _extract_best_link_from_node(node, base_url: str):
    anchors = node.select("a[href]")
    if not anchors:
        return None, None

    preferred = []
    fallback = []

    for a in anchors:
        href = (a.get("href") or "").strip()
        text = _clean(a.get_text(" ", strip=True))
        if not href:
            continue

        full_url = urljoin(base_url, href)
        blob = f"{text} {full_url}".lower()

        if any(
            x in blob
            for x in [
                "apply",
                "application",
                "open call",
                "call for applications",
                "call for proposals",
                "fund",
                "funding",
                "grant",
                "competition",
                "rfp",
            ]
        ):
            preferred.append((text, full_url))
        else:
            fallback.append((text, full_url))

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return None, None


def fetch_gsma_innovation_fund(url: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    try:
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()
    except Exception as e:
        print("⚠️ GSMA fetch failed:", str(e))
        return out

    soup = BeautifulSoup(res.text, "html.parser")
    seen_urls = set()
    seen_titles = set()

    candidate_nodes = soup.select(
        "article, .card, .views-row, li, .elementor-post, .post, .entry, section, div"
    )

    extracted_any = False

    for node in candidate_nodes:
        title_a = node.select_one("a[href]")
        if not title_a:
            continue

        title = _clean(title_a.get_text(" ", strip=True))
        if not title or len(title) < 8:
            continue

        _, full_url = _extract_best_link_from_node(node, url)
        if not full_url:
            continue

        if not _looks_like_fund_page(title, full_url):
            continue

        key_title = title.lower()
        if full_url in seen_urls or key_title in seen_titles:
            continue

        summary = _summary_from_parent(node, title)
        deadline = _extract_deadline(summary)
        amount_max = _extract_amount_max(summary)

        if not _looks_like_live_opportunity(title, summary, full_url):
            continue

        if _is_obviously_stale(title, summary, deadline):
            continue

        out.append(
            {
                "title": title,
                "url": full_url,
                "summary": summary[:500],
                "eligibility_notes": "",
                "deadline_date": deadline,
                "funding_amount_min": None,
                "funding_amount_max": amount_max,
            }
        )
        seen_urls.add(full_url)
        seen_titles.add(key_title)
        extracted_any = True

    if not extracted_any:
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            title = _clean(a.get_text(" ", strip=True))

            if not href or not title or len(title) < 8:
                continue

            full_url = urljoin(url, href)
            if not _looks_like_fund_page(title, full_url):
                continue

            key_title = title.lower()
            if full_url in seen_urls or key_title in seen_titles:
                continue

            parent = a.find_parent(["article", "div", "li", "section"])
            summary = _summary_from_parent(parent, title)
            deadline = _extract_deadline(summary)
            amount_max = _extract_amount_max(summary)

            if not _looks_like_live_opportunity(title, summary, full_url):
                continue

            if _is_obviously_stale(title, summary, deadline):
                continue

            out.append(
                {
                    "title": title,
                    "url": full_url,
                    "summary": summary[:500],
                    "eligibility_notes": "",
                    "deadline_date": deadline,
                    "funding_amount_min": None,
                    "funding_amount_max": amount_max,
                }
            )
            seen_urls.add(full_url)
            seen_titles.add(key_title)

    print(f"✅ GSMA parsed {len(out)} opportunities")
    return out