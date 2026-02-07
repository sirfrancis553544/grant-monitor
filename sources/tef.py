# sources/tef.py
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

UA = {"User-Agent": "Mozilla/5.0"}

DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b")  # e.g. 1 March 2026
USD_RE = re.compile(r"\bUS\$\s*([\d,]+)\b", re.IGNORECASE)

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}

def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)

def _parse_date_iso(text: str):
    # pick the first "1 March 2026" style date that looks like a deadline
    # TEF press release includes "open from 1 January to 1 March 2026"
    matches = DATE_RE.findall(text)
    # heuristic: choose the last date in the sentence if multiple
    if not matches:
        return None
    dd, mon, yyyy = matches[-1]
    m = MONTHS.get(mon.lower())
    if not m:
        return None
    return f"{yyyy}-{str(m).zfill(2)}-{str(int(dd)).zfill(2)}"

def fetch_tef_programme(press_release_url: str, programme_url: str | None = None) -> list[dict]:
    """
    Returns ONE "call" item for TEF Entrepreneurship Programme (Africa-wide).
    We scrape:
      - deadline date from press release
      - seed capital amount (USD) from press release
      - eligibility bullets from programme page (optional)
    """
    r = requests.get(press_release_url, headers=UA, timeout=20)
    r.raise_for_status()
    text = _clean_text(r.text)

    # deadline: take the last date in the "open from ... to ..." sentence
    deadline_iso = None
    # try to find the line mentioning "open from" first
    for ln in text.splitlines():
        if "Applications" in ln and "open" in ln and "to" in ln and "2026" in ln:
            deadline_iso = _parse_date_iso(ln)
            break
    if not deadline_iso:
        deadline_iso = _parse_date_iso(text)

    # seed capital
    seed = None
    m = USD_RE.search(text)
    if m:
        seed = int(m.group(1).replace(",", ""))

    eligibility = ""
    if programme_url:
        try:
            r2 = requests.get(programme_url, headers=UA, timeout=20)
            r2.raise_for_status()
            t2 = _clean_text(r2.text)
            # pull the eligibility criteria bullets if present
            # lines that start with "Applications from..." on the TEF programme page
            bullets = []
            for ln in t2.splitlines():
                low = ln.lower()
                if low.startswith("applications from africans") or "business no older than 5 years" in low:
                    bullets.append(ln)
                if len(bullets) >= 5:
                    break
            if bullets:
                eligibility = " | ".join(bullets)
        except Exception:
            eligibility = ""

    item = {
        "title": "TEF Entrepreneurship Programme (Africa) — 2026 Applications Open",
        "url": press_release_url,
        "summary": "Seed capital + training + mentorship for entrepreneurs across all 54 African countries (apply via TEFConnect).",
        "deadline_date": deadline_iso,  # e.g. 2026-03-01
        "funding_amount_min": None,
        "funding_amount_max": seed,  # e.g. 5000 (USD)
        "eligibility_notes": eligibility or "Open to entrepreneurs across Africa (see programme eligibility details).",
    }
    return [item]
