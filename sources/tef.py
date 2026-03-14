# sources/tef.py

from __future__ import annotations

import re
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0"}

DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b")
USD_RE = re.compile(r"\bUS\$\s*([\d,]+)\b", re.IGNORECASE)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _date_to_iso(dd: str, mon: str, yyyy: str) -> str | None:
    m = MONTHS.get(mon.lower())
    if not m:
        return None
    try:
        return f"{int(yyyy):04d}-{m:02d}-{int(dd):02d}"
    except Exception:
        return None


def _parse_date_iso(text: str):
    """
    Pick the last '1 March 2026' style date in the given text.
    Useful for phrases like:
    'Applications are open from 1 January 2026 to 1 March 2026'
    """
    matches = DATE_RE.findall(text or "")
    if not matches:
        return None
    dd, mon, yyyy = matches[-1]
    return _date_to_iso(dd, mon, yyyy)


def _parse_iso_date(raw: str | None):
    if not raw:
        return None

    s = str(raw).strip().lower()
    if s in {"rolling", "open"}:
        return "rolling"

    try:
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _looks_like_tef_page(text: str) -> bool:
    blob = (text or "").lower()
    required = [
        "tony elumelu",
        "entrepreneurship programme",
        "africa",
    ]
    hits = sum(1 for x in required if x in blob)
    return hits >= 2


def _extract_seed_amount(text: str) -> int | None:
    m = USD_RE.search(text or "")
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except Exception:
        return None


def _extract_deadline_from_text(text: str) -> str | None:
    """
    Prefer lines mentioning applications/open/closing, otherwise fallback
    to the last date found in the page text.
    """
    lines = (text or "").splitlines()

    priority_patterns = [
        ("application", "open"),
        ("applications", "open"),
        ("apply", "deadline"),
        ("closing date",),
        ("deadline",),
        ("open from", "to"),
    ]

    for ln in lines:
        low = ln.lower()
        for pats in priority_patterns:
            if all(p in low for p in pats):
                iso = _parse_date_iso(ln)
                if iso:
                    return iso

    return _parse_date_iso(text)


def _extract_eligibility(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    bullets: list[str] = []

    signals = [
        "applications from africans",
        "business no older than 5 years",
        "54 african countries",
        "african entrepreneurs",
        "entrepreneurs across africa",
        "must be 18 years",
        "legal resident",
        "business idea",
        "startup",
    ]

    for ln in lines:
        low = ln.lower()
        if any(sig in low for sig in signals):
            bullets.append(ln)
        if len(bullets) >= 5:
            break

    if bullets:
        return " | ".join(bullets)

    return ""


def fetch_tef_programme(press_release_url: str, programme_url: str | None = None) -> list[dict]:
    """
    Returns ONE 'call' item for TEF Entrepreneurship Programme (Africa-wide).

    We scrape:
      - deadline date from press release / programme page
      - seed capital amount (USD)
      - eligibility notes from programme page if available

    Returns [] if the content looks stale or invalid.
    """
    try:
        r = requests.get(press_release_url, headers=UA, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print("⚠️ TEF press release fetch failed:", str(e))
        return []

    press_text = _clean_text(r.text)

    if not _looks_like_tef_page(press_text):
        print("⚠️ TEF press release page does not look like a TEF programme page")
        return []

    deadline_iso = _extract_deadline_from_text(press_text)
    seed = _extract_seed_amount(press_text)

    eligibility = ""
    final_url = programme_url or press_release_url
    programme_text = ""

    if programme_url:
        try:
            r2 = requests.get(programme_url, headers=UA, timeout=20)
            r2.raise_for_status()
            programme_text = _clean_text(r2.text)

            if _looks_like_tef_page(programme_text):
                extracted_eligibility = _extract_eligibility(programme_text)
                if extracted_eligibility:
                    eligibility = extracted_eligibility

                # Prefer deadline from programme page if it looks better and exists
                programme_deadline = _extract_deadline_from_text(programme_text)
                if programme_deadline:
                    deadline_iso = programme_deadline
            else:
                print("⚠️ TEF programme page did not match expected TEF content; using press release only")
        except Exception as e:
            print("⚠️ TEF programme page fetch failed:", str(e))

    parsed_deadline = _parse_iso_date(deadline_iso)
    if parsed_deadline not in (None, "rolling"):
        if parsed_deadline < datetime.now(timezone.utc):
            print("⚠️ TEF opportunity looks expired; skipping")
            return []

    if not eligibility:
        eligibility = "Open to entrepreneurs across Africa (see programme eligibility details)."

    summary = (
        "Seed capital, training, and mentorship for entrepreneurs across African countries "
        "through the Tony Elumelu Foundation Entrepreneurship Programme."
    )

    item = {
        "title": "TEF Entrepreneurship Programme (Africa) — Applications Open",
        "url": final_url,
        "summary": summary,
        "deadline_date": deadline_iso,
        "funding_amount_min": None,
        "funding_amount_max": seed,
        "eligibility_notes": eligibility,
    }

    return [item]