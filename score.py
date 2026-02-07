import re
from datetime import datetime, timedelta, timezone


def _parse_iso_date(s: str | None):
    if not s or s == "rolling":
        return None
    try:
        # Handles YYYY-MM-DD and full ISO timestamps
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))

        # If date is naive, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt
    except Exception:
        return None


def score_grant(g: dict, profile: dict) -> tuple[int, list[str]]:
    inc = [k.lower() for k in profile.get("keywords_include", [])]
    exc = [k.lower() for k in profile.get("keywords_exclude", [])]

    title = (g.get("title") or "").lower()
    summary = (g.get("summary") or "").lower()

    why: list[str] = []
    score = 0

    # --- Exclusions first (hard penalties) ---
    for k in exc:
        if k and (k in title or k in summary):
            score -= 3
            why.append(f"excluded keyword: {k}")

    # --- Inclusions ---
    for k in inc:
        if not k:
            continue
        if k in title:
            score += 2
            why.append(f"title match: {k}")
        elif k in summary:
            score += 1
            why.append(f"summary match: {k}")

    # --- Location scope boost ---
    scope = (g.get("location_scope") or "").upper()
    country = profile.get("country", "DE").upper()
    if country in scope:
        score += 1
        why.append(f"scope includes {country}")

    # --- Deadline window logic ---
    max_days = int(profile.get("max_days_to_deadline", 90))
    dd = _parse_iso_date(g.get("deadline_date"))

    if dd:
        now = datetime.now(timezone.utc)

        if dd < now:
            score -= 2
            why.append("deadline passed")
        elif dd > now + timedelta(days=max_days):
            score -= 1
            why.append(f"deadline beyond {max_days}d")

    return score, why
