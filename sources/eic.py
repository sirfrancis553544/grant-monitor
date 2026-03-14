# sources/eic.py

from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0"}


def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _extract_amounts(text: str) -> tuple[int | None, int | None]:
    """
    Try to detect the classic EIC Accelerator amounts:
    - grant below EUR 2.5 million
    - equity up to EUR 10 million
    """
    t = text.lower()

    grant_max = None
    equity_max = None

    if "2.5 million" in t or "2,5 million" in t:
        grant_max = 2_500_000

    if "10 million" in t or "10,0 million" in t:
        equity_max = 10_000_000

    return grant_max, equity_max


def _looks_like_eic_accelerator_page(text: str) -> bool:
    t = text.lower()

    required_signals = [
        "eic accelerator",
        "startup",
        "sme",
    ]

    return sum(1 for s in required_signals if s in t) >= 2


def fetch_eic_accelerator(eic_url: str) -> list[dict]:
    """
    Returns ONE item for the official EIC Accelerator page.
    Treated as rolling because short proposals can usually be submitted continuously,
    even though full proposals may use batching dates.
    """
    try:
        r = requests.get(eic_url, headers=UA, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print("⚠️ EIC fetch failed:", str(e))
        return []

    text = _clean_text(r.text)

    if not _looks_like_eic_accelerator_page(text):
        print("⚠️ EIC page does not look like the EIC Accelerator page")
        return []

    grant_max, equity_max = _extract_amounts(text)

    summary = (
        "Deep-tech funding for startups and SMEs under Horizon Europe, "
        "combining grant support with potential equity or blended finance."
    )

    eligibility = (
        "Startups and SMEs in EU Member States and Horizon Europe associated countries. "
        "Short proposals are typically accepted on a rolling basis, with full proposals "
        "handled on batching dates."
    )

    if grant_max:
        summary += f" Grant component available up to €{grant_max:,}."
    if equity_max:
        eligibility += f" Equity component may be available up to €{equity_max:,}."

    item = {
        "title": "EIC Accelerator (EU) — Grant + Equity for Startups/SMEs",
        "url": eic_url,
        "summary": summary,
        "deadline_date": "rolling",
        "funding_amount_min": None,
        "funding_amount_max": grant_max,
        "eligibility_notes": eligibility,
    }

    return [item]