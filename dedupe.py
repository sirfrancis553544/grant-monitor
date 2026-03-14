from __future__ import annotations

import hashlib
from urllib.parse import urlparse


def normalize_text(s: str | None) -> str:
    return (s or "").strip().lower()


def normalize_url(url: str | None) -> str:
    """
    Normalize URL for stable identity.
    Removes tracking parameters and scheme differences.
    """
    if not url:
        return ""

    try:
        u = urlparse(url)

        host = (u.netloc or "").lower()
        path = (u.path or "").rstrip("/").lower()

        return f"{host}{path}"

    except Exception:
        return (url or "").strip().lower()


def make_fingerprint(
    title: str,
    funder: str | None = None,
    deadline_date: str | None = None,
    url: str | None = None,
) -> str:
    """
    Canonical grant fingerprint used across the entire system.

    Identity keys:
      title
      funder
      normalized url

    Deadline intentionally excluded because many sites update it.
    """
    t = normalize_text(title)
    f = normalize_text(funder)
    u = normalize_url(url)

    base = f"{t}|{f}|{u}"

    return hashlib.sha256(base.encode("utf-8")).hexdigest()