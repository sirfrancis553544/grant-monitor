from __future__ import annotations

from typing import Any, Dict, List


def _text(grant: dict) -> str:
    parts = [
        grant.get("title"),
        grant.get("summary"),
        grant.get("eligibility_notes"),
        grant.get("funder"),
    ]
    return " ".join(str(x or "") for x in parts).lower()


def estimate_application_effort(grant: dict) -> Dict[str, Any]:
    """
    Returns a normalized effort object for digest cards.

    Example:
    {
        "effort": "Hard",
        "label": "🏗 Hard",
        "notes": ["multi-stage application", "consortium required"]
    }
    """
    text = _text(grant)
    title = str(grant.get("title") or "").lower()
    summary = str(grant.get("summary") or "").lower()

    hard_hits: List[str] = []
    easy_hits: List[str] = []

    hard_keywords = {
        "accelerator": "multi-stage application",
        "consortium": "consortium required",
        "horizon europe": "complex application process",
        "eic accelerator": "detailed application",
        "due diligence": "due diligence required",
        "pitch": "pitch review",
        "multi-stage": "multi-stage application",
        "full proposal": "full proposal required",
    }

    easy_keywords = {
        "competition": "short application",
        "innovation fund": "light application",
        "open call": "simple application flow",
        "rolling": "faster submission path",
        "expression of interest": "short initial submission",
    }

    for keyword, note in hard_keywords.items():
        if keyword in text:
            hard_hits.append(note)

    for keyword, note in easy_keywords.items():
        if keyword in text:
            easy_hits.append(note)

    if "accelerator" in title and "competition" in title:
        hard_hits.append("selection process involved")

    if hard_hits:
        notes = []
        for n in hard_hits:
            if n not in notes:
                notes.append(n)
        return {
            "effort": "Hard",
            "label": "🏗 Hard",
            "notes": notes[:3],
        }

    if easy_hits:
        notes = []
        for n in easy_hits:
            if n not in notes:
                notes.append(n)
        return {
            "effort": "Easy",
            "label": "⚡ Easy",
            "notes": notes[:3],
        }

    if "grant application" in summary or "proposal" in text:
        return {
            "effort": "Medium",
            "label": "📄 Medium",
            "notes": ["proposal required"],
        }

    return {
        "effort": "Medium",
        "label": "📄 Medium",
        "notes": ["standard application effort"],
    }