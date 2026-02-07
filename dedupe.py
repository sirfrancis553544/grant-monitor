import hashlib
from urllib.parse import urlparse

def _norm_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        u = urlparse(url)
        # stable identity: domain + path (ignore tracking query params)
        return (u.netloc + u.path).lower()
    except Exception:
        return (url or "").lower()

def make_fingerprint(title: str, funder: str | None, deadline_date: str | None, url: str | None) -> str:
    t = (title or "").strip().lower()
    f = (funder or "").strip().lower()
    u = _norm_url(url)
    base = f"{t}|{f}|{u}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()
