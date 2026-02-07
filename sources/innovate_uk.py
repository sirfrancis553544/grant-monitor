# sources/innovate_uk.py
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

UA = {"User-Agent": "Mozilla/5.0"}

GBP_RE = re.compile(r"£\s*([\d,]+(?:\.\d+)?)\s*(million|m)?", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})")

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}

def _date_to_iso(s: str) -> str | None:
    # "11 February 2026" -> 2026-02-11
    parts = s.strip().split()
    if len(parts) != 3:
        return None
    dd, mon, yyyy = parts
    m = MONTHS.get(mon.lower())
    if not m:
        return None
    return f"{yyyy}-{str(m).zfill(2)}-{str(int(dd)).zfill(2)}"

def _parse_gbp_amount(text: str):
    m = GBP_RE.search(text)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    is_m = bool(m.group(2))
    if is_m:
        return int(num * 1_000_000)
    return int(num)

def fetch_innovate_uk_competitions(search_url: str) -> list[dict]:
    r = requests.get(search_url, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    items = []
    # competitions are rendered as repeating blocks with "## <a>"
    # simplest: find all h2, then walk siblings for description + dates
    for h2 in soup.find_all(["h2"]):
        a = h2.find("a")
        if not a or not a.get("href"):
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        href = a["href"].strip()
        if not href.startswith("http"):
            href = "https://apply-for-innovation-funding.service.gov.uk" + href

        # block text: take next ~ few elements until next hr/h2
        block_text = []
        node = h2
        for _ in range(20):
            node = node.find_next_sibling()
            if not node:
                break
            if node.name == "h2":
                break
            if node.name == "hr":
                break
            t = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
            if t:
                block_text.append(t)

        blob = " ".join(block_text)
        summary = blob.split("### Eligibility")[0].strip() if "### Eligibility" in blob else blob[:300].strip()

        funding_max = _parse_gbp_amount(blob)

        # parse "Closes: 11 February 2026" or "Closes: 4 March 2026"
        deadline_iso = None
        m = re.search(r"Closes:\s*([0-9]{1,2}\s+[A-Za-z]+\s+\d{4})", blob)
        if m:
            deadline_iso = _date_to_iso(m.group(1))

        eligibility = ""
        m2 = re.search(r"### Eligibility\s*(.+?)(###|$)", blob)
        if m2:
            eligibility = m2.group(1).strip()

        items.append({
            "title": title,
            "url": href,
            "summary": summary,
            "deadline_date": deadline_iso,
            "funding_amount_min": None,
            "funding_amount_max": funding_max,
            "eligibility_notes": eligibility,
        })

    # keep it sane: only newest 30 parsed from page
    return items[:30]
