def estimate_application_effort(grant: dict) -> dict:
    title = (grant.get("title") or "").lower()
    summary = (grant.get("summary") or "").lower()

    if "accelerator" in title:
        return {
            "effort": "Hard",
            "label": "🏗 Hard",
            "notes": [
                "multi-stage application",
                "pitch review",
                "due diligence"
            ]
        }

    if "consortium" in summary:
        return {
            "effort": "Hard",
            "label": "🏗 Hard",
            "notes": ["consortium required"]
        }

    if "competition" in title or "innovation fund" in title:
        return {
            "effort": "Easy",
            "label": "⚡ Easy",
            "notes": ["short application"]
        }

    return {
        "effort": "Medium",
        "label": "📄 Medium",
        "notes": ["proposal required"]
    }