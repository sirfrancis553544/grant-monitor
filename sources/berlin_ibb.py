import requests
from bs4 import BeautifulSoup

BASE = "https://www.ibb.de"

def fetch_berlin_ibb_programs(url: str, timeout: int = 20):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    programs = []
    seen = set()

    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        title = a.get_text(" ", strip=True)

        if not href or not title:
            continue

        # Program detail pages live here
        if "/de/foerderprogramme/" not in href:
            continue

        if href.startswith("/"):
            href = BASE + href

        href_key = href.split("?")[0]
        if href_key in seen:
            continue
        seen.add(href_key)

        programs.append({"title": title, "url": href})

    return programs
