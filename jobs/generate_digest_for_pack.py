from pathlib import Path
import yaml

from store import get_all_grants  # if you have a function like this
from score import score_grant
from digest import render_digest_html

PACK_TO_PROFILE = {
    "DE": "profiles/germany_startup.yaml",
    "EU": "profiles/eu_startup.yaml",
    "UK": "profiles/uk_startup.yaml",
    "AFRICA": "profiles/africa_startup.yaml",
}

def load_profile(pack: str) -> dict:
    path = PACK_TO_PROFILE[pack]
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))

def pick_top(grants: list[dict], profile: dict, limit: int = 20) -> list[dict]:
    scored = []
    for g in grants:
        sc, why = score_grant(g, profile)
        if sc <= 0:
            continue
        gg = dict(g)
        gg["_score"] = sc
        gg["_why"] = why
        scored.append(gg)
    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored[:limit]

def generate_html(pack: str) -> tuple[str, int]:
    profile = load_profile(pack)

    # assumes you already have DB with grants ingested
    grants = get_all_grants()  # adjust if your function name differs
    picked = pick_top(grants, profile, limit=int(profile.get("top_n", 20)))

    html = render_digest_html(picked)
    return html, len(picked)
