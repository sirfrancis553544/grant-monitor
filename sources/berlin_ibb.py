# sources/berlin_ibb.py

from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup

BASE = "https://www.ibb.de"
UA = {"User-Agent": "Mozilla/5.0"}


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_programme_link(title: str, href: str) -> bool:
    blob = f"{title} {href}".lower()

    bad_terms = [
        "kontakt",
        "contact",
        "impressum",
        "datenschutz",
        "privacy",
        "cookie",
        "login",
        "suche",
        "search",
        "newsletter",
        "presse",
        "press",
        "news",
        "event",
        "veranstaltung",
        "download",
        "pdf",
        "#",
        "mailto:",
    ]

    if any(term in blob for term in bad_terms):
        return False

    return "/de/foerderprogramme/" in href.lower()


def fetch_berlin_ibb_programs(url: str, timeout: int = 20) -> list[dict]:
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    programs: list[dict] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        title = _clean(a.get_text(" ", strip=True))

        if not href or not title:
            continue

        if len(title) < 6:
            continue

        if not _looks_like_programme_link(title, href):
            continue

        if href.startswith("/"):
            href = BASE + href

        href_key = href.split("?", 1)[0].rstrip("/")
        title_key = title.lower()

        if href_key in seen_urls or title_key in seen_titles:
            continue

        seen_urls.add(href_key)
        seen_titles.add(title_key)

        programs.append(
            {
                "title": title,
                "url": href_key,
            }
        )

    return programs