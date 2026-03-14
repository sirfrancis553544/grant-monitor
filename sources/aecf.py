# sources/aecf.py

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
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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


def _parse_date(raw: Optional[str]):
    if not raw:
        return None

    s = str(raw).strip()
    s_l = s.lower()

    if s_l in {"rolling", "open"}:
        return "rolling"

    fmts = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
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
        r"(?:£|\$|€|USD|EUR)?\s*([\d]+(?:[.,]\d+)?)\s*(million|m)\b",
        text,
        flags=re.IGNORECASE,
    ):
        try:
            vals.append(float(m.group(1).replace(",", "")) * 1_000_000)
        except Exception:
            pass

    for m in re.finditer(
        r"(?:£|\$|€|USD|EUR)\s*([\d]{1,3}(?:[,\s]\d{3})*(?:[.,]\d+)?)",
        text,
        flags=re.IGNORECASE,
    ):
        try:
            vals.append(float(m.group(1).replace(",", "").replace(" ", "")))
        except Exception:
            pass

    return max(vals) if vals else None


def _looks_like_opportunity(title: str, href: str) -> bool:
    blob = f"{title} {href}".lower()

    good_keywords = [
        "grant",
        "fund",
        "funding",
        "apply",
        "application",
        "open call",
        "call for proposals",
        "competition",
        "challenge fund",
        "innovation fund",
        "request for proposals",
        "rfp",
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
        "search",
        "mailto:",
        "#",
        "blog",
        "news",
        "article",
        "story",
        "case study",
        "event",
        "webinar",
        "workshop",
        "video",
        "resources",
    ]

    if any(b in blob for b in bad_keywords):
        return False

    return any(k in blob for k in good_keywords)


def _looks_like_live_opportunity(title: str, summary: str, href: str) -> bool:
    blob = f"{title} {summary} {href}".lower()

    good = [
        "apply",
        "application",
        "deadline",
        "call for applications",
        "call for proposals",
        "grant",
        "funding",
        "competition",
        "open call",
    ]

    bad = [
        "bootcamp",
        "highlight",
        "event",
        "news",
        "blog",
        "article",
        "story",
        "case study",
        "report",
        "resource",
        "video",
    ]

    if any(x in blob for x in bad):
        return False

    return any(x in blob for x in good)


def _is_stale(title: str, summary: str, deadline: Optional[str]) -> bool:
    blob = f"{title} {summary}".lower()

    if deadline:
        parsed = _parse_date(deadline)
        if parsed != "rolling" and parsed is not None:
            now = datetime.now(timezone.utc)
            if parsed < now:
                return True

    if any(y in blob for y in ["2022", "2023", "2024"]) and any(
        x in blob for x in ["bootcamp", "event", "highlight", "story"]
    ):
        return True

    return False


def _best_summary(parent, title: str) -> str:
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


def _pick_best_link(node, base_url):
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

        full = urljoin(base_url, href)
        blob = f"{text} {full}".lower()

        if any(x in blob for x in ["apply", "application", "fund", "grant"]):
            preferred.append((text, full))
        else:
            fallback.append((text, full))

    if preferred:
        return preferred[0]

    if fallback:
        return fallback[0]

    return None, None


def fetch_aecf_opportunities(url: str) -> List[Dict[str, Any]]:
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

    candidate_nodes = soup.select(
        "article, .card, .views-row, li, .elementor-post, .post, .entry"
    )

    extracted_any = False

    for node in candidate_nodes:
        title_a = node.select_one("a[href]")
        if not title_a:
            continue

        title = _clean(title_a.get_text(" ", strip=True))
        if not title or len(title) < 8:
            continue

        _, full_url = _pick_best_link(node, url)
        if not full_url:
            continue

        if not _looks_like_opportunity(title, full_url):
            continue

        key_title = title.lower()
        if full_url in seen_urls or key_title in seen_titles:
            continue

        summary = _best_summary(node, title)

        deadline = _extract_deadline(summary)
        amount_max = _extract_amount_max(summary)

        if not _looks_like_live_opportunity(title, summary, full_url):
            continue

        if _is_stale(title, summary, deadline):
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

            if not _looks_like_opportunity(title, full_url):
                continue

            key_title = title.lower()
            if full_url in seen_urls or key_title in seen_titles:
                continue

            parent = a.find_parent(["article", "div", "li", "section"])
            summary = _best_summary(parent, title)

            deadline = _extract_deadline(summary)
            amount_max = _extract_amount_max(summary)

            if not _looks_like_live_opportunity(title, summary, full_url):
                continue

            if _is_stale(title, summary, deadline):
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

    print(f"✅ AECF parsed {len(out)} opportunities")

    return out