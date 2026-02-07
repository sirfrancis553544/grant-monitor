import re
import requests
from bs4 import BeautifulSoup

EUR_RE = re.compile(r"(\d[\d\.\s]*)\s*(EUR|Euro)", re.IGNORECASE)
MIO_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mio|million)\b", re.IGNORECASE)

def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    cleaned = []
    drop_phrases = (
        "einwilligung", "cookie", "cookies", "datenschutzerklärung",
        "tracking", "etracker"
    )
    for ln in lines:
        if not ln:
            continue
        low = ln.lower()
        if any(p in low for p in drop_phrases):
            continue
        cleaned.append(ln)
    return "\n".join(cleaned)

def _extract_deadline(text: str):
    low = text.lower()
    if any(k in low for k in ["laufend", "jederzeit", "fortlaufend", "keine frist"]):
        return "rolling"

    keys = ["antragsfrist", "frist", "bewerbungsfrist", "antragstellung", "bis zum", "endet am", "abgabefrist"]
    ctx = None
    for k in keys:
        idx = low.find(k)
        if idx != -1:
            ctx = text[max(0, idx - 250): min(len(text), idx + 600)]
            break

    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", ctx or text)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"

    return None

def _extract_amount_max(text: str):
    amounts = []

    for raw, _ in EUR_RE.findall(text)[:20]:
        n = raw.replace(".", "").replace(" ", "")
        try:
            amounts.append(float(n))
        except:
            pass

    for val, _ in MIO_RE.findall(text)[:20]:
        try:
            amounts.append(float(val.replace(",", ".")) * 1_000_000)
        except:
            pass

    if not amounts:
        return None
    return int(max(amounts))

def _extract_eligibility(text: str):
    # Common headings: "Zielgruppe", "Antragsberechtigt", "Wer wird gefördert"
    for key in ["Antragsberechtigt", "Wer wird gefördert", "Zielgruppe"]:
        idx = text.lower().find(key.lower())
        if idx != -1:
            snippet = text[idx: idx + 500]
            # take first 1-3 lines after heading
            lines = [ln.strip() for ln in snippet.splitlines() if ln.strip()]
            return " ".join(lines[:4])[:350]
    return None

def enrich_berlin_ibb_program(url: str, timeout: int = 20) -> dict:
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    r.raise_for_status()
    text = _clean_text(r.text)

    deadline = _extract_deadline(text)
    elig = _extract_eligibility(text)
    amt_max = _extract_amount_max(text)

    confidence_boost = 0.0
    if deadline:
        confidence_boost += 0.2
    if elig:
        confidence_boost += 0.1
    if amt_max:
        confidence_boost += 0.1

    return {
        "deadline_date": deadline,
        "eligibility_notes": elig,
        "funding_amount_min": None,
        "funding_amount_max": amt_max,
        "confidence_boost": confidence_boost,
        "raw_snippet": text[:700],
    }
