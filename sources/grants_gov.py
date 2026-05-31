from __future__ import annotations

import csv
import re
from datetime import datetime
from html import unescape
from pathlib import Path
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

PRIORITY_TERMS = [
    "small business", "startup", "sme", "sbir", "sttr", "innovation", "innovative",
    "technology", "software", "digital", "artificial intelligence", " ai ", "data",
    "cyber", "cybersecurity", "research", "r&d", "commercialization",
    "prototype", "manufacturing", "climate", "energy", "clean tech", "health",
]

LOW_PRIORITY_TERMS = [
    "tribal", "municipal", "county", "state government", "law enforcement", "agriculture",
    "wildlife", "marine", "fish", "forest", "housing", "homeless", "museum", "library",
    "school district", "infrastructure", "construction", "water", "wastewater",
]


def _csv_candidates() -> list[Path]:
    candidates = [Path("data/grants_gov_export.csv"), Path("data/grants-search.csv")]
    data_dir = Path("data")
    if data_dir.exists():
        candidates.extend(sorted(data_dir.glob("grants-search-*.csv")))
    return candidates


def _clean(value: Any) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split()).strip()


def _first(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return None


def _number(value: Any) -> int | None:
    raw = _clean(value).replace(",", "")
    if not raw or raw.lower() == "nan":
        return None
    try:
        return int(float(raw))
    except Exception:
        return None


def _normalize_deadline(value: Any) -> str | None:
    raw = _clean(value)
    if not raw or raw.lower() == "nan":
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


def _text(row: dict) -> str:
    return " ".join(_clean(v).lower() for v in row.values() if v not in (None, ""))


def _relevance(row: dict) -> int:
    text = f" {_text(row)} "
    score = 0
    for term in PRIORITY_TERMS:
        if term in text:
            score += 8 if term.strip() in {"sbir", "sttr", "small business", "startup"} else 4
    for term in LOW_PRIORITY_TERMS:
        if term in text:
            score -= 3
    if _clean(_first(row, "award_ceiling", "awardCeiling", "estimated_total_program_funding")):
        score += 2
    if _clean(_first(row, "close_date", "closeDate", "deadline", "due_date", "dueDate", "forecasted_close_date")):
        score += 2
    return score


def _extract_rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for path in (("data", "opportunities"), ("data", "results"), ("data",), ("opportunities",), ("results",), ("items",)):
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

    agency = _clean(_first(row, "agency_name", "agencyName", "agency", "agency_code", "agencyCode", "top_level_agency_name")) or "U.S. Federal Government"
    summary = _clean(_first(row, "summary_description", "summary", "description", "opportunity_summary", "opportunitySummary", "funding_category_description"))
    deadline = _normalize_deadline(_first(row, "close_date", "closeDate", "deadline", "due_date", "dueDate", "forecasted_close_date"))
    url = _clean(_first(row, "url", "opportunity_url", "opportunityUrl"))
    url_id = opportunity_id or opportunity_number
    if not url:
        url = f"https://simpler.grants.gov/opportunity/{url_id}" if url_id else "https://simpler.grants.gov/search?utm_source=Grants.gov"

    return {
        "title": title,
        "url": url,
        "summary": summary or f"Federal funding opportunity from {agency}.",
        "deadline_date": deadline,
        "funding_amount_min": _number(_first(row, "award_floor", "awardFloor")),
        "funding_amount_max": _number(_first(row, "award_ceiling", "awardCeiling", "estimated_total_program_funding")),
        "eligibility_notes": _clean(_first(row, "applicant_eligibility_description", "applicant_eligibility", "applicantEligibility", "eligibility", "applicant_types")),
        "funder": agency,
    }


def _load_csv(max_items: int) -> list[dict]:
    for path in _csv_candidates():
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [row for row in csv.DictReader(handle) if _is_open(row)]
        rows.sort(key=_relevance, reverse=True)
        grants: list[dict] = []
        seen: set[str] = set()
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
            print(f"✅ Grants.gov CSV parsed {len(grants)} prioritized opportunities from {path}")
            return grants
    return []


def fetch_grants_gov_opportunities(url: str | None = None, max_items: int = 50) -> list[dict]:
    csv_grants = _load_csv(max_items)
    if csv_grants:
        return csv_grants

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
                for row in sorted(rows, key=_relevance, reverse=True):
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
