import re
import requests
from bs4 import BeautifulSoup

DATE_RE = re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b")
EUR_RE  = re.compile(r"(\d[\d\.\s]*)\s*(EUR|Euro)", re.IGNORECASE)

ROLLING_KEYS = [
    "antragstellung laufend",
    "fortlaufend",
    "laufend",
    "keine antragsfrist",
    "ohne antragsfrist",
]

DEADLINE_KEYS = [
    "antragsfrist",
    "fristen",
    "frist",
    "einreichen bis",
    "endet am",
    "bis zum",
    "bis spätestens",
    "anträge können bis",
]

def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()

def _first_date_iso(text: str | None):
    if not text:
        return None
    m = DATE_RE.search(text)
    if not m:
        return None
    d = m.group(1)  # dd.mm.yyyy
    dd, mm, yyyy = d.split(".")
    return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"

def _slice_around(text: str, idx: int, before: int = 250, after: int = 600) -> str:
    start = max(0, idx - before)
    end = min(len(text), idx + after)
    return text[start:end]

def enrich_foerderdatenbank_program(url: str, timeout=20) -> dict:
    """
    Returns:
      {deadline_date, eligibility_notes, funding_amount_min, funding_amount_max, confidence_boost, raw_snippet}

    Notes:
    - Many programs are rolling: we return deadline_date="rolling"
    - Otherwise we try to pick deadline dates from contexts around deadline keywords.
    """
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    text = _clean_text(r.text)
    t = text.lower()

    # --- Rolling detection ---
    if any(k in t for k in ROLLING_KEYS):
        return {
            "deadline_date": "rolling",
            "eligibility_notes": None,
            "funding_amount_min": None,
            "funding_amount_max": None,
            "confidence_boost": 0.15,
            "raw_snippet": "rolling (laufend/fortlaufend) detected",
        }

    # --- Deadline extraction (prefer keyword contexts; fallback to whole page) ---
    deadline_context = None
    for key in DEADLINE_KEYS:
        idx = t.find(key)
        if idx != -1:
            deadline_context = _slice_around(text, idx)
            break

    deadline_date = _first_date_iso(deadline_context) if deadline_context else None
    if not deadline_date:
        # fallback: whole page (less precise, but better than nothing)
        deadline_date = _first_date_iso(text)

    # --- Eligibility extraction ---
    # Förderdatenbank often renders labels without umlauts, e.g. "Foerderberechtigte:"
    eligibility_notes = None
    m = re.search(r"Foerderberechtigte:\s*\n\s*(.+)", text)
    if m:
        eligibility_notes = m.group(1).strip()
        tail = text[m.end():m.end()+500]
        tail = tail.split("\n\n")[0].strip()
        if tail and len(tail) < 300:
            eligibility_notes = (eligibility_notes + " " + tail).strip()

    # --- Funding amount extraction (approx) ---
    eur_hits = [h[0] for h in EUR_RE.findall(text)]
    amounts = []
    for raw in eur_hits[:8]:
        n = raw.replace(".", "").replace(" ", "")
        try:
            amounts.append(float(n))
        except Exception:
            pass

    funding_amount_min = None
    funding_amount_max = max(amounts) if amounts else None

    # --- Raw snippet for debugging ---
    raw_snippet = (deadline_context or text[:700]).strip()

    # --- Confidence boost ---
    confidence_boost = 0.0
    if deadline_date:
        confidence_boost += 0.2
    if eligibility_notes:
        confidence_boost += 0.1
    if funding_amount_max:
        confidence_boost += 0.1

    return {
        "deadline_date": deadline_date,
        "eligibility_notes": eligibility_notes,
        "funding_amount_min": funding_amount_min,
        "funding_amount_max": funding_amount_max,
        "confidence_boost": confidence_boost,
        "raw_snippet": raw_snippet,
    }
