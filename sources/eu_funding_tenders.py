# sources/eu_funding_tenders.py

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


def fetch_eu_funding_tenders_calls(url: str) -> List[Dict[str, Any]]:
    """
    Starter parser for EU Funding & Tenders calls page.
    This is intentionally generic because the portal markup can change.
    We extract likely call links + nearby descriptive text.
    """
    out: List[Dict[str, Any]] = []

    try:
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()
    except Exception as e:
        print("⚠️ EU Funding & Tenders fetch failed:", str(e))
        return out

    soup = BeautifulSoup(res.text, "html.parser")
    seen = set()

    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        title = _clean(a.get_text(" ", strip=True))

        if not href or not title:
            continue

        full_url = urljoin(url, href)

        title_l = title.lower()
        href_l = full_url.lower()

        # Bias toward call / topic pages
        if not any(
            kw in title_l or kw in href_l
            for kw in [
                "call",
                "topic",
                "proposal",
                "funding",
                "grant",
                "eic",
                "horizon",
                "innovation",
                "digital",
            ]
        ):
            continue

        if len(title) < 12:
            continue

        if full_url in seen:
            continue
        seen.add(full_url)

        parent = a.find_parent(["article", "div", "li", "section", "tr"])
        summary = ""
        if parent:
            summary = _clean(parent.get_text(" ", strip=True))
            if summary.startswith(title):
                summary = summary[len(title):].strip(" -:–|")

        out.append(
            {
                "title": title,
                "url": full_url,
                "summary": summary[:600],
                "eligibility_notes": "",
                "deadline_date": None,
                "funding_amount_min": None,
                "funding_amount_max": None,
            }
        )

    print(f"✅ EU Funding & Tenders parsed {len(out)} calls")
    return out