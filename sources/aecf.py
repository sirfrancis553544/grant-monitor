# sources/aecf.py

from __future__ import annotations

import re
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
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_deadline(text: str) -> Optional[str]:
    """
    Try to extract a deadline in common formats.
    Returns raw matched text for now.
    """
    if not text:
        return None

    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",                  # 2026-04-15
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",    # 15/04/2026, 15-04-2026
        r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",        # 15 April 2026
        r"\b[A-Za-z]+\s+\d{1,2},\s+\d{4}\b",       # April 15, 2026
    ]

    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(0)

    return None


def _extract_amount_max(text: str) -> Optional[float]:
    """
    Try to extract largest-looking funding amount.
    Handles things like:
    £2,500
    €5 million
    USD 1.2 million
    """
    if not text:
        return None

    candidates = []

    million_pat = re.finditer(
        r"(?:£|\$|€|USD|EUR|GBP)?\s*([\d]+(?:[.,]\d+)?)\s*(million|m)\b",
        text,
        flags=re.IGNORECASE,
    )
    for m in million_pat:
        raw_num = m.group(1).replace(",", "")
        try:
            val = float(raw_num) * 1_000_000
            candidates.append(val)
        except Exception:
            pass

    number_pat = re.finditer(
        r"(?:£|\$|€|USD|EUR|GBP)\s*([\d]{1,3}(?:[,\s]\d{3})*(?:[.,]\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    for m in number_pat:
        raw_num = m.group(1).replace(" ", "").replace(",", "")
        try:
            val = float(raw_num)
            candidates.append(val)
        except Exception:
            pass

    if not candidates:
        return None

    return max(candidates)


def _looks_like_opportunity(title: str, href: str) -> bool:
    title_l = title.lower()
    href_l = href.lower()

    good_keywords = [
        "opportun",
        "fund",
        "call",
        "challenge",
        "application",
        "apply",
        "grant",
        "competition",
        "programme",
        "program",
        "window",
        "seed",
        "financing",
    ]

    bad_keywords = [
        "privacy",
        "cookie",
        "contact",
        "about",
        "team",
        "career",
        "linkedin",
        "facebook",
        "twitter",
        "instagram",
        "youtube",
        "press",
        "newsroom",
        "donate",
        "report",
        "policy",
        "terms",
        "login",
        "sign-in",
        "sign in",
        "search",
        "mailto:",
        "#",
    ]

    if any(b in title_l or b in href_l for b in bad_keywords):
        return False

    return any(k in title_l or k in href_l for k in good_keywords)


def _best_summary_from_parent(parent, title: str) -> str:
    if not parent:
        return ""

    text = _clean(parent.get_text(" ", strip=True))
    if not text:
        return ""

    # remove title repetition
    if text.startswith(title):
        text = text[len(title):].strip(" -:–|")

    # avoid extremely long blocks
    if len(text) > 700:
        text = text[:700].rsplit(" ", 1)[0]

    return text


def fetch_aecf_opportunities(url: str) -> List[Dict[str, Any]]:
    """
    Stronger starter parser for AECF opportunity pages.
    Extracts:
    - title
    - url
    - summary
    - deadline_date (raw if found)
    - funding_amount_max
    """
    out: List[Dict[str, Any]] = []

    try:
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()
    except Exception as e:
        print("⚠️ AECF fetch failed:", str(e))
        return out

    soup = BeautifulSoup(res.text, "html.parser")
    seen_urls = set()
    seen_titles = set()

    # Try common container patterns first
    candidate_nodes = soup.select("article, .card, .views-row, li, .elementor-post, .post, .entry")

    extracted_any = False

    for node in candidate_nodes:
        a = node.select_one("a[href]")
        if not a:
            continue

        href = (a.get("href") or "").strip()
        title = _clean(a.get_text(" ", strip=True))

        if not href or not title or len(title) < 8:
            continue

        full_url = urljoin(url, href)

        if not _looks_like_opportunity(title, full_url):
            continue

        key_title = title.lower()
        if full_url in seen_urls or key_title in seen_titles:
            continue

        summary = _best_summary_from_parent(node, title)
        deadline = _extract_deadline(summary)
        amount_max = _extract_amount_max(summary)

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

    # Fallback: generic link scan
    if not extracted_any:
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            title = _clean(a.get_text(" ", strip=True))

            if not href or not title or len(title) < 8:
                continue

            full_url = urljoin(url, href)

            if not _looks_like_opportunity(title, full_url):
                continue

            key_title = title.lower()
            if full_url in seen_urls or key_title in seen_titles:
                continue

            parent = a.find_parent(["article", "div", "li", "section"])
            summary = _best_summary_from_parent(parent, title)
            deadline = _extract_deadline(summary)
            amount_max = _extract_amount_max(summary)

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

    print(f"✅ AECF parsed {len(out)} opportunities")
    return out