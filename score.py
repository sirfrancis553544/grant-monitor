import re
from datetime import datetime, timezone
from typing import Optional


def _parse_iso_date(s: Optional[str]):
    if not s:
        return None

    s = str(s).strip()
    s_l = s.lower()

    if s_l in {"rolling", "open"}:
        return "rolling"

    # Remove weekday prefix like "Tuesday September 3, 2024"
    s = re.sub(
        r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+",
        "",
        s,
        flags=re.IGNORECASE,
    ).strip()

    candidates = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d %B %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %b %Y",
    ]

    for fmt in candidates:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _norm_text(v) -> str:
    return (v or "").strip().lower()


def _region_score(scope: str, country: str) -> tuple[int, list[str]]:
    """
    Strong region fit scoring.
    """
    why = []
    scope_u = (scope or "").strip().upper()
    country_u = (country or "").strip().upper()

    if not scope_u:
        return 0, why

    if country_u == "DE":
        if scope_u == "DE":
            return 6, ["exact region match: DE"]
        if "BERLIN" in scope_u or "GERMANY" in scope_u:
            return 4, [f"sub-region match: {scope_u}"]
        if scope_u in {"EU", "EUROPE"}:
            return 1, ["broad regional relevance: EU"]
        return -4, [f"wrong region: {scope_u}"]

    if country_u == "EU":
        if scope_u == "EU":
            return 6, ["exact region match: EU"]
        if "EUROPE" in scope_u:
            return 5, [f"broad region match: {scope_u}"]
        if scope_u == "DE":
            return 1, ["partial regional relevance: DE within Europe"]
        if scope_u == "UK":
            return -3, ["wrong region: UK"]
        if scope_u == "AFRICA":
            return -4, ["wrong region: AFRICA"]
        return -2, [f"weak region fit: {scope_u}"]

    if country_u == "UK":
        if scope_u == "UK":
            return 6, ["exact region match: UK"]
        if scope_u == "EU":
            return -2, ["wrong region: EU"]
        if scope_u == "AFRICA":
            return -4, ["wrong region: AFRICA"]
        if scope_u == "DE":
            return -3, ["wrong region: DE"]
        return -2, [f"weak region fit: {scope_u}"]

    if country_u == "AFRICA":
        if scope_u == "AFRICA":
            return 6, ["exact region match: AFRICA"]
        if "SUB-SAHARAN" in scope_u:
            return 5, [f"sub-region match: {scope_u}"]
        if scope_u in {"GLOBAL", "INTERNATIONAL"}:
            return 1, [f"broad region relevance: {scope_u}"]
        if scope_u in {"EU", "UK", "DE", "BERLIN"}:
            return -4, [f"wrong region: {scope_u}"]
        return -2, [f"weak region fit: {scope_u}"]

    if country_u in scope_u:
        return 4, [f"scope includes {country_u}"]

    return 0, why


def _deadline_score(deadline_raw, max_days: int) -> tuple[int, list[str]]:
    why = []
    dd = _parse_iso_date(deadline_raw)

    if dd == "rolling":
        return 4, ["rolling/open deadline"]

    if not dd:
        return 0, why

    now = datetime.now(timezone.utc)

    if dd < now:
        return -8, ["deadline passed"]

    delta_days = (dd - now).days

    if delta_days <= 30:
        return 5, [f"deadline soon: {delta_days}d"]
    if delta_days <= 90:
        return 3, [f"deadline within 90d: {delta_days}d"]
    if delta_days <= max_days:
        return 1, [f"deadline within profile window: {delta_days}d"]

    return -2, [f"deadline beyond {max_days}d"]


def _funding_score(g: dict) -> tuple[int, list[str]]:
    why = []
    max_amt = _to_float(g.get("funding_amount_max"))
    min_amt = _to_float(g.get("funding_amount_min"))

    amt = max_amt if max_amt is not None else min_amt
    if amt is None:
        return 0, why

    if amt > 1_000_000_000:
        return -2, ["suspicious funding amount"]

    if amt < 10_000:
        return 0, why
    if amt < 100_000:
        return 1, [f"funding level: {int(amt):,}"]
    if amt < 1_000_000:
        return 2, [f"strong funding level: {int(amt):,}"]
    return 3, [f"high funding level: {int(amt):,}"]


def _startup_fit_score(title: str, summary: str, eligibility: str, themes: str) -> tuple[int, list[str]]:
    why = []
    blob = " ".join([title, summary, eligibility, themes]).lower()

    positives = [
        "startup", "sme", "small business", "kmu", "mittelstand",
        "innovation", "accelerator", "incubator", "prototype",
        "pilot", "feasibility", "scale-up", "deep tech", "technology",
        "digital", "r&d", "research", "founder", "entrepreneur"
    ]
    negatives = [
        "procurement", "tender", "supply of", "school", "kindergarten",
        "construction", "municipality", "public authority only",
        "consultancy services", "staff position", "personnel funding only"
    ]

    score = 0

    for k in positives:
        if k in blob:
            score += 1
            why.append(f"startup-fit match: {k}")

    for k in negatives:
        if k in blob:
            score -= 4
            why.append(f"startup-fit penalty: {k}")

    return score, why


def score_grant(g: dict, profile: dict) -> tuple[int, list[str]]:
    inc = [_norm_text(k) for k in profile.get("keywords_include", [])]
    exc = [_norm_text(k) for k in profile.get("keywords_exclude", [])]

    title = _norm_text(g.get("title"))
    summary = _norm_text(g.get("summary"))
    eligibility = _norm_text(g.get("eligibility_notes"))
    themes = _norm_text(g.get("themes"))
    scope = (g.get("location_scope") or "").strip()
    country = (profile.get("country") or "DE").strip().upper()
    max_days = int(profile.get("max_days_to_deadline", 90))

    why: list[str] = []
    score = 0

    for k in exc:
        if not k:
            continue
        if k in title:
            score -= 5
            why.append(f"excluded title keyword: {k}")
        elif k in summary or k in eligibility:
            score -= 3
            why.append(f"excluded summary keyword: {k}")

    for k in inc:
        if not k:
            continue

        if k in title:
            score += 3
            why.append(f"title match: {k}")
        elif k in themes:
            score += 2
            why.append(f"theme match: {k}")
        elif k in summary or k in eligibility:
            score += 1
            why.append(f"summary match: {k}")

    region_s, region_why = _region_score(scope, country)
    score += region_s
    why.extend(region_why)

    deadline_s, deadline_why = _deadline_score(g.get("deadline_date"), max_days)
    score += deadline_s
    why.extend(deadline_why)

    funding_s, funding_why = _funding_score(g)
    score += funding_s
    why.extend(funding_why)

    fit_s, fit_why = _startup_fit_score(title, summary, eligibility, themes)
    score += fit_s
    why.extend(fit_why)

    return score, why