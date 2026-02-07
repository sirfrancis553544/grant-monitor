# sources/eic.py
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

def fetch_eic_accelerator(eic_url: str) -> list[dict]:
    """
    Returns ONE item. EIC Accelerator is effectively rolling (batching dates),
    so we set deadline_date = "rolling".
    Pulls the key funding figures from the page (grant < 2.5m, equity up to 10m).
    """
    r = requests.get(eic_url, headers=UA, timeout=20)
    r.raise_for_status()
    text = _clean_text(r.text)

    # crude extraction (page contains "below EUR 2.5 million" and "Up to € 10 million")
    grant_max = None
    equity_max = None

    if "2.5 million" in text.lower():
        grant_max = 2500000
    if "10 million" in text.lower():
        equity_max = 10000000

    summary = "Deep-tech funding for startups/SMEs (grant + equity/blended finance) under Horizon Europe."
    eligibility = "Startups and SMEs in EU Member States / Horizon Europe associated countries. Short proposal anytime; full proposals on batching dates."

    if equity_max:
        eligibility += f" Equity component up to €{equity_max:,} (see page)."

    item = {
        "title": "EIC Accelerator (EU) — Grant + Equity for Startups/SMEs",
        "url": eic_url,
        "summary": summary,
        "deadline_date": "rolling",
        "funding_amount_min": None,
        "funding_amount_max": grant_max,  # grant part
        "eligibility_notes": eligibility,
    }
    return [item]
