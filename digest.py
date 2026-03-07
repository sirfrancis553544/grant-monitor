from __future__ import annotations

from datetime import date
from html import escape
import json
import csv
from pathlib import Path
from typing import Any, Dict, List, Union


PACK_LABELS = {
    "DE": "🇩🇪 Germany",
    "EU": "🇪🇺 European Union",
    "UK": "🇬🇧 United Kingdom",
    "AFRICA": "🌍 Africa",
}


def _fmt_money(max_amt, currency="€"):
    """Format max amount into labels like €250k / €1.2M."""
    if max_amt in (None, "", 0, "0"):
        return None
    try:
        v = float(max_amt)
    except Exception:
        return None

    # Guard against obviously broken values
    if v > 1_000_000_000:
        return None

    if v >= 1_000_000:
        return f"{currency}{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{currency}{int(v / 1_000)}k"
    return f"{currency}{int(v)}"


def _fmt_deadline(d):
    """Normalize deadline values for chips."""
    if not d:
        return "OPEN"
    ds = str(d).strip()
    if ds.lower() == "rolling":
        return "ROLLING"
    if ds.lower() == "open":
        return "OPEN"
    return ds


def _trim_summary(text: str, max_len: int = 240) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


def _normalize_why(why) -> list[str]:
    if isinstance(why, str):
        return [why.strip()] if why.strip() else []
    if isinstance(why, (list, tuple)):
        return [str(x).strip() for x in why if str(x).strip()]
    return []


def _first_nonempty(*values) -> str:
    for v in values:
        s = str(v or "").strip()
        if s:
            return s
    return ""


def render_card(g: dict):
    deadline = _fmt_deadline(g.get("deadline_date"))
    funding = _fmt_money(g.get("funding_amount_max"))
    why_list = _normalize_why(g.get("_why"))

    url = (g.get("url") or "#").strip()
    title_txt = _first_nonempty(g.get("title"), "Untitled grant")
    summary = _trim_summary(g.get("summary") or "")

    chips = []
    if funding:
        chips.append(
            f"""
            <span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#eff6ff;color:#1d4ed8;font-size:12px;font-weight:800">
              Up to {escape(funding)}
            </span>
            """
        )
    if deadline:
        chips.append(
            f"""
            <span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#f8fafc;color:#334155;font-size:12px;font-weight:800;border:1px solid #e5e7eb">
              Deadline: {escape(deadline)}
            </span>
            """
        )

    chips_html = "".join(chips)

    why_html = ""
    if why_list:
        why_html = (
            "<div style='margin-top:12px;font-size:12px;line-height:1.6;color:#6b7280'>"
            "<span style='font-weight:800;color:#374151'>Why matched:</span> "
            + ", ".join(escape(x) for x in why_list[:5])
            + "</div>"
        )

    summary_html = ""
    if summary:
        summary_html = f"""
        <div style="margin-top:12px;font-size:14px;line-height:1.65;color:#374151">
          {escape(summary)}
        </div>
        """

    return f"""
<div style="border:1px solid #e5e7eb;border-radius:20px;overflow:hidden;background:#ffffff;margin-bottom:16px;box-shadow:0 2px 10px rgba(15,23,42,0.04)">
  <div style="
    position:relative;
    padding:18px;
    background:
      radial-gradient(140px 90px at 85% 25%, rgba(37,99,235,0.10), transparent 60%),
      radial-gradient(160px 100px at 15% 80%, rgba(16,185,129,0.08), transparent 60%),
      linear-gradient(135deg,#ffffff 0%,#f8fafc 55%,#f3f4f6 100%);
  ">
    <div style="
      position:absolute; inset:0;
      background-image:
        linear-gradient(to right, rgba(17,24,39,0.05) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(17,24,39,0.05) 1px, transparent 1px);
      background-size:36px 36px;
      opacity:0.22;
    "></div>

    <div style="position:relative;z-index:2">
      <div style="font-size:20px;font-weight:900;line-height:1.3;color:#111827">
        <a href="{escape(url)}" target="_blank" rel="noreferrer" style="color:#111827;text-decoration:none">
          {escape(title_txt)}
        </a>
      </div>

      {"<div style='margin-top:12px;display:flex;flex-wrap:wrap;gap:8px'>" + chips_html + "</div>" if chips_html else ""}
    </div>
  </div>

  <div style="padding:18px">
    {summary_html}

    <div style="margin-top:14px">
      <a href="{escape(url)}" target="_blank" rel="noreferrer"
         style="display:inline-block;padding:10px 14px;border-radius:12px;background:#2563EB;color:#ffffff;font-weight:800;font-size:14px;text-decoration:none">
        Open application →
      </a>
    </div>

    {why_html}
  </div>
</div>
"""


def _render_section(parts, heading, items, subheading=None):
    parts.append(
        f"""
        <div style="margin:22px 0 10px;font-size:15px;color:#111827;font-weight:900">
          {escape(heading)}
        </div>
        """
    )

    if subheading:
        parts.append(
            f"""
            <div style="color:#6B7280;font-size:14px;margin:-2px 0 14px">
              {escape(subheading)}
            </div>
            """
        )

    if items:
        for g in items:
            if isinstance(g, dict):
                parts.append(render_card(g))
    else:
        parts.append(
            """
            <div style="border:1px solid #e5e7eb;border-radius:14px;padding:16px;background:#ffffff;color:#6b7280">
              No matches in this section.
            </div>
            """
        )


def _normalize_sections(
    sections: Union[Dict[str, List[dict]], List[dict], None]
) -> Dict[str, List[dict]]:
    """
    Backwards-compatible normalizer:
    - If sections is a dict => return as-is
    - If sections is a list => wrap into DE by default for single-pack renderer compatibility
    """
    if sections is None:
        return {"DE": []}

    if isinstance(sections, list):
        return {"DE": sections}

    out: Dict[str, List[dict]] = {}
    for k, v in (sections or {}).items():
        out[str(k)] = v or []
    return out


def _detect_primary_pack(sections: Dict[str, List[dict]]) -> str:
    """
    Pick the first non-empty pack in priority order.
    """
    for key in ("DE", "EU", "UK", "AFRICA"):
        if sections.get(key):
            return key
    return "DE"


def render_digest_html(
    sections,
    unsubscribe_url: str = "https://rubixscout.com/unsubscribe",
):
    """
    Accepts either:
      - dict: {"DE":[...], "EU":[...], ...}
      - list: [ ... ]   (single-pack mode)
    Renders a cleaner weekly digest email.
    """
    sections = _normalize_sections(sections)

    today = date.today().isoformat()

    de = sections.get("DE", []) or []
    eu = sections.get("EU", []) or []
    uk = sections.get("UK", []) or []
    af = sections.get("AFRICA", []) or []

    total = len(de) + len(eu) + len(uk) + len(af)
    primary_pack = _detect_primary_pack(sections)
    primary_pack_label = PACK_LABELS.get(primary_pack, primary_pack)

    non_empty_sections = [(k, v) for k, v in sections.items() if v]
    single_pack_mode = len(non_empty_sections) == 1

    if single_pack_mode:
        intro_text = "Here are this week’s strongest funding matches for your selected pack."
        pack_display = primary_pack_label
    else:
        intro_text = "Here are this week’s best matches across your selected digest sections."
        pack_display = "Multi-pack digest"

    parts = []
    parts.append(
        f"""
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
</head>
<body style="margin:0;padding:0;background:#f6f7fb;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#111827">
  <div style="max-width:820px;margin:0 auto;padding:22px">

    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
      style="background:#111827;color:#ffffff;border-radius:18px;padding:18px 18px;border-collapse:separate">
      <tr>
        <td style="vertical-align:top;padding-right:12px">
          <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#93c5fd">
            RubixScout · Weekly Grant Digest
          </div>
          <div style="margin-top:6px;font-size:22px;font-weight:900;line-height:1.15">
            Hi — here are your best matches for {escape(today)}
          </div>
          <div style="margin-top:8px;font-size:13px;color:#d1d5db">
            {total} opportunities · Prioritized by fit · Source links included
          </div>
        </td>

        <td style="vertical-align:top;text-align:right;width:210px">
          <div style="display:inline-block;background:rgba(255,255,255,0.10);border:1px solid rgba(255,255,255,0.18);padding:10px 12px;border-radius:12px">
            <div style="font-size:12px;color:#e5e7eb;font-weight:800">Pack</div>
            <div style="margin-top:2px;font-size:13px;font-weight:900;color:#ffffff;white-space:nowrap">
              {escape(pack_display)}
            </div>
          </div>
        </td>
      </tr>
    </table>

    <div style="margin-top:14px;background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;padding:14px">
      <div style="font-size:14px;font-weight:900;color:#111827">
        Quick note 👋
      </div>
      <div style="margin-top:6px;font-size:13px;line-height:1.6;color:#374151">
        {escape(intro_text)} Open the source link to verify eligibility and apply fast.
        “Why matched” explains why each opportunity showed up.
      </div>
    </div>
"""
    )

    if single_pack_mode:
        pack_key, items = non_empty_sections[0] if non_empty_sections else ("DE", [])
        heading = PACK_LABELS.get(pack_key, pack_key) + " — best matches"
        _render_section(parts, heading, items)
    else:
        if de:
            _render_section(parts, "🇩🇪 Germany — best matches", de)
        if eu:
            _render_section(parts, "🇪🇺 European Union — best matches", eu)
        if uk:
            _render_section(parts, "🇬🇧 United Kingdom — best matches", uk)
        if af:
            _render_section(parts, "🌍 Africa — best matches", af)

    parts.append(
        f"""
    <div style="margin-top:18px;padding:16px 0;border-top:1px solid #e5e7eb;color:#6b7280;font-size:12px;text-align:center">
      <div style="font-weight:800;color:#111827;margin-bottom:6px">RubixScout</div>
      <div>New funding opportunities every week.</div>
      <div style="margin-top:10px">
        <a href="{escape(unsubscribe_url)}" style="color:#2563eb;text-decoration:none;font-weight:800">Manage subscription</a>
      </div>
    </div>

  </div>
</body>
</html>
"""
    )

    return "".join(parts)


def write_outputs(sections, out_dir="data"):
    """
    Accepts either:
      - dict sections
      - list (single pack)
    Writes:
      - digest.json (normalized sections dict)
      - digest.csv  (flattened rows with a 'section' column)
      - digest.html (rendered from sections)
    Returns: (json_path, csv_path, html_path)
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "digest.json"
    csv_path = out / "digest.csv"
    html_path = out / "digest.html"

    normalized = _normalize_sections(sections)

    json_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    cols = [
        "section",
        "title",
        "funder",
        "deadline_date",
        "funding_amount_min",
        "funding_amount_max",
        "location_scope",
        "themes",
        "url",
        "source",
        "_score",
        "_why",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for section_key, items in (normalized or {}).items():
            for g in (items or []):
                if not isinstance(g, dict):
                    continue
                row = {k: g.get(k) for k in cols if k != "section"}
                row["section"] = section_key
                w.writerow(row)

    html = render_digest_html(
        normalized,
        unsubscribe_url="https://rubixscout.com/unsubscribe",
    )
    html_path.write_text(html, encoding="utf-8")

    return str(json_path), str(csv_path), str(html_path)