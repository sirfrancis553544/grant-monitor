# sources/gsma.py

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
    return re.sub(r"\s+", " ", text).strip()


def _extract_deadline(text: str) -> Optional[str]:
    if not text:
        return None

    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",
        r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",
        r"\b[A-Za-z]+\s+\d{1,2},\s+\d{4}\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(0)
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

    good = [
        "fund",
        "innovation",
        "grant",
        "application",
        "apply",
        "programme",
        "program",
        "venture",
        "startup",
        "challenge",
        "opportun",
        "cohort",
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
        "#",
        "mailto:",
    ]

    if any(x in t or x in h for x in bad):
        return False
    return any(x in t or x in h for x in good)


def _summary_from_parent(parent, title: str) -> str:
    if not parent:
        return ""
    text = _clean(parent.get_text(" ", strip=True))
    if text.startswith(title):
        text = text[len(title):].strip(" -:–|")
    return text[:700]


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

    candidate_nodes = soup.select("article, .card, .views-row, li, .elementor-post, .post, .entry, section, div")

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
        if not _looks_like_fund_page(title, full_url):
            continue

        key_title = title.lower()
        if full_url in seen_urls or key_title in seen_titles:
            continue

        summary = _summary_from_parent(node, title)
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