from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

SEARCH_ENDPOINTS = [
    "https://api.simpler.grants.gov/v1/opportunities/search",
    "https://api.simpler.grants.gov/v1/search/opportunities",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 RubixScoutGrantMonitor/1.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _first(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return None


def _normalize_deadline(value: Any) -> str | None:
    raw = _clean(value)
    if not raw:
        return None
    if raw.lower() in {"rolling", "ongoing", "continuous"}:
        return "rolling"
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return raw[:10] if len(raw) >= 10 else raw


def _is_open(row: dict) -> bool:
    status = _clean(_first(row, "opportunity_status", "opportunityStatus", "status")).lower()
    if not status:
        return True
    return status in {"posted", "forecasted", "open", "active"}


def _extract_rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for path in (
        ("data", "opportunities"),
        ("data", "results"),
        ("data",),
        ("opportunities",),
        ("results",),
        ("items",),
    ):
        current: Any = payload
        for key in path:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                current = None
                break
        if isinstance(current, list):
            return [x for x in current if isinstance(x, dict)]
    return []


def _row_to_grant(row: dict) -> dict | None:
    title = _clean(_first(row, "opportunity_title", "opportunityTitle", "title", "name"))
    opportunity_id = _clean(_first(row, "opportunity_id", "opportunityId", "id"))
    opportunity_number = _clean(_first(row, "opportunity_number", "opportunityNumber", "number"))
    if not title or len(title) < 12:
        return None
    if not _is_open(row):
        return None

    agency = _clean(_first(row, "agency_name", "agencyName", "agency", "agency_code", "agencyCode")) or "U.S. Federal Government"
    summary = _clean(_first(row, "summary", "description", "opportunity_summary", "opportunitySummary"))
    deadline = _normalize_deadline(_first(row, "close_date", "closeDate", "deadline", "due_date", "dueDate"))
    url_id = opportunity_id or opportunity_number
    url = f"https://simpler.grants.gov/opportunity/{url_id}" if url_id else "https://simpler.grants.gov/search?utm_source=Grants.gov"

    return {
        "title": title,
        "url": url,
        "summary": summary or f"Federal funding opportunity from {agency}.",
        "deadline_date": deadline,
        "funding_amount_min": None,
        "funding_amount_max": None,
        "eligibility_notes": _clean(_first(row, "applicant_eligibility", "applicantEligibility", "eligibility")),
        "funder": agency,
    }


def fetch_grants_gov_opportunities(url: str | None = None, max_items: int = 50) -> list[dict]:
    payloads = [
        {"pagination": {"page_offset": 1, "page_size": max_items}, "filters": {"opportunity_statuses": ["posted", "forecasted"]}},
        {"page": 1, "page_size": max_items, "filters": {"status": ["posted", "forecasted"]}},
        {"pagination": {"page": 1, "size": max_items}, "query": ""},
    ]

    for endpoint in SEARCH_ENDPOINTS:
        for payload in payloads:
            try:
                response = requests.post(endpoint, json=payload, headers=HEADERS, timeout=25)
                if response.status_code in {404, 405}:
                    continue
                response.raise_for_status()
                rows = _extract_rows(response.json())
                grants = []
                seen = set()
                for row in rows:
                    grant = _row_to_grant(row)
                    if not grant:
                        continue
                    key = grant["url"] or grant["title"].lower()
                    if key in seen:
                        continue
                    grants.append(grant)
                    seen.add(key)
                    if len(grants) >= max_items:
                        break
                if grants:
                    print(f"✅ Grants.gov parsed {len(grants)} opportunities")
                    return grants
            except Exception as exc:
                print(f"⚠️ Grants.gov endpoint failed {endpoint}: {exc}")
                continue

    print("⚠️ Grants.gov parsed 0 opportunities")
    return []
