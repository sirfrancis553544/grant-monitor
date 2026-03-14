from __future__ import annotations

from datetime import date
from html import escape
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


PACK_META = {
    "DE": {"label": "Germany", "flag": "🇩🇪"},
    "EU": {"label": "European Union", "flag": "🇪🇺"},
    "UK": {"label": "United Kingdom", "flag": "🇬🇧"},
    "AFRICA": {"label": "Africa", "flag": "🌍"},
}


def _pack_label(pack: str) -> str:
    pack = (pack or "").strip().upper()
    meta = PACK_META.get(pack)
    if meta:
        return f"{meta['flag']} {meta['label']}"
    return pack or "Selected pack"


def _pack_plain_label(pack: str) -> str:
    pack = (pack or "").strip().upper()
    meta = PACK_META.get(pack)
    if meta:
        return meta["label"]
    return pack or "Selected pack"


def _fmt_money(max_amt: Any, currency: str = "€") -> Optional[str]:
    """Format max amount into labels like €250k / €1.2M."""
    if max_amt in (None, "", 0, "0"):
        return None
    try:
        v = float(max_amt)
    except Exception:
        return None

    if v <= 0 or v > 1_000_000_000:
        return None

    if v >= 1_000_000:
        return f"{currency}{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{currency}{int(v / 1_000)}k"
    return f"{currency}{int(v)}"


def _fmt_deadline(d: Any) -> str:
    """Normalize deadline values for chips."""
    if not d:
        return "Open"
    ds = str(d).strip()
    low = ds.lower()
    if low == "rolling":
        return "Rolling"
    if low == "open":
        return "Open"
    return ds


def _trim_summary(text: str, max_len: int = 240) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


def _normalize_why(why: Any) -> List[str]:
    if isinstance(why, str):
        return [why.strip()] if why.strip() else []
    if isinstance(why, (list, tuple)):
        return [str(x).strip() for x in why if str(x).strip()]
    return []


def _first_nonempty(*values: Any) -> str:
    for v in values:
        s = str(v or "").strip()
        if s:
            return s
    return ""


def _safe_url(url: Any) -> str:
    s = str(url or "").strip()
    return s if s else "#"


def _chip(label: str, bg: str, fg: str, border: Optional[str] = None) -> str:
    border_css = f"border:1px solid {border};" if border else "border:none;"
    return (
        f'<span style="display:inline-block;padding:6px 10px;border-radius:999px;'
        f'background:{bg};color:{fg};font-size:12px;font-weight:800;{border_css}">'
        f"{escape(label)}"
        f"</span>"
    )


def render_card(g: dict) -> str:
    deadline = _fmt_deadline(g.get("deadline_date"))
    funding = _fmt_money(g.get("funding_amount_max"))
    why_list = _normalize_why(g.get("_why"))

    fit_score = g.get("fit_score")
    radar = g.get("deadline_radar") or {}
    effort = g.get("application_effort") or {}

    url = _safe_url(g.get("url"))
    title_txt = _first_nonempty(g.get("title"), "Untitled grant")
    summary = _trim_summary(g.get("summary") or "")

    chips: List[str] = []

    if fit_score not in (None, ""):
        chips.append(_chip(f"Fit score: {fit_score}%", "#ecfeff", "#0e7490"))

    if funding:
        chips.append(_chip(f"Funding: {funding}", "#eff6ff", "#1d4ed8"))

    if radar.get("badge"):
        chips.append(_chip(str(radar["badge"]), "#fef3c7", "#92400e"))

    if effort.get("label"):
        chips.append(_chip(f"Effort: {effort['label']}", "#f8fafc", "#334155", "#e2e8f0"))

    if deadline:
        chips.append(_chip(f"Deadline: {deadline}", "#f8fafc", "#334155", "#e5e7eb"))

    chips_html = "".join(chips)

    summary_html = ""
    if summary:
        summary_html = f"""
        <div style="margin-top:12px;font-size:14px;line-height:1.7;color:#374151">
          {escape(summary)}
        </div>
        """

    why_html = ""
    if why_list:
        why_lines = "".join(
            f'<div style="margin-top:6px">• {escape(item)}</div>'
            for item in why_list[:4]
        )
        why_html = f"""
        <div style="margin-top:16px;padding:14px 16px;border:1px solid #e5e7eb;border-radius:14px;background:#f8fafc">
          <div style="font-size:13px;font-weight:900;color:#111827">Why this matched</div>
          <div style="margin-top:6px;font-size:13px;line-height:1.6;color:#475569">
            {why_lines}
          </div>
        </div>
        """

    return f"""
<div style="border:1px solid #e5e7eb;border-radius:20px;overflow:hidden;background:#ffffff;margin-bottom:16px;box-shadow:0 10px 30px rgba(15,23,42,0.05)">

  <div style="
    position:relative;
    padding:18px;
    background:
      radial-gradient(140px 90px at 85% 25%, rgba(37,99,235,0.10), transparent 60%),
      radial-gradient(160px 100px at 15% 80%, rgba(14,165,233,0.08), transparent 60%),
      linear-gradient(135deg,#ffffff 0%,#f8fbff 55%,#f3f7fb 100%);
  ">

    <div style="position:relative;z-index:2">
      <div style="font-size:22px;font-weight:900;line-height:1.3;color:#111827">
        <a href="{escape(url)}" target="_blank" rel="noreferrer" style="color:#111827;text-decoration:none">
          {escape(title_txt)}
        </a>
      </div>

      {"<div style='margin-top:12px;display:flex;flex-wrap:wrap;gap:8px'>" + chips_html + "</div>" if chips_html else ""}
    </div>
  </div>

  <div style="padding:18px">
    {summary_html}

    <div style="margin-top:16px">
      <a href="{escape(url)}" target="_blank" rel="noreferrer"
         style="display:inline-block;padding:10px 14px;border-radius:12px;background:#2563EB;color:#ffffff;font-weight:800;font-size:14px;text-decoration:none">
        View details →
      </a>

      <a href="{escape(url)}" target="_blank" rel="noreferrer"
         style="display:inline-block;margin-left:10px;padding:10px 14px;border-radius:12px;background:#111827;color:#ffffff;font-weight:800;font-size:14px;text-decoration:none">
        Apply →
      </a>
    </div>

    {why_html}
  </div>
</div>
"""


def _render_section(parts: List[str], heading: str, items: List[dict], subheading: Optional[str] = None) -> None:
    parts.append(
        f"""
        <div style="margin:26px 0 10px;font-size:16px;color:#111827;font-weight:900">
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
    sections: Union[Dict[str, List[dict]], List[dict], None],
    pack: Optional[str] = None,
) -> Dict[str, List[dict]]:
    if sections is None:
        return {(pack or "DE").strip().upper(): []}

    if isinstance(sections, list):
        pack_key = (pack or "DE").strip().upper()
        return {pack_key: sections}

    out: Dict[str, List[dict]] = {}
    for k, v in (sections or {}).items():
        out[str(k).strip().upper()] = v or []
    return out


def _detect_primary_pack(sections: Dict[str, List[dict]]) -> str:
    preferred_order = ("DE", "EU", "UK", "AFRICA")
    for key in preferred_order:
        if sections.get(key):
            return key
    for key in sections.keys():
        return key
    return "DE"


def render_digest_html(
    sections: Union[Dict[str, List[dict]], List[dict], None],
    pack: Optional[str] = None,
) -> str:
    """
    Accepts either:
      - dict: {"DE":[...], "EU":[...], ...}
      - list: [ ... ]   (single-pack mode)

    Important:
    - pass `pack="AFRICA"` / `pack="EU"` / etc when using list mode
    - footer is intentionally NOT rendered here anymore
      because send_weekly.py should inject the final unsubscribe-aware footer
    """
    normalized = _normalize_sections(sections, pack=pack)
    today = date.today().isoformat()

    total = sum(len(items or []) for items in normalized.values())
    primary_pack = (pack or _detect_primary_pack(normalized)).strip().upper()
    primary_pack_label = _pack_label(primary_pack)
    primary_pack_plain = _pack_plain_label(primary_pack)

    non_empty_sections = [(k, v) for k, v in normalized.items() if v]
    single_pack_mode = len(non_empty_sections) == 1

    if single_pack_mode:
        intro_text = (
            "Here are this week’s strongest funding matches for your selected pack. "
            "Open the source link to verify eligibility and apply fast. "
            "“Why this matched” explains why each opportunity showed up."
        )
        hero_title = f"Best funding matches for {primary_pack_plain}"
        hero_meta = f"{total} opportunities · Prioritized by fit · Source links included"
        pack_display = primary_pack_label
    else:
        intro_text = (
            "Here are this week’s strongest funding matches across your selected packs. "
            "Open each source link to verify eligibility and move quickly on deadlines."
        )
        hero_title = f"Your best matches for {today}"
        hero_meta = f"{total} opportunities · Multi-pack digest · Source links included"
        pack_display = "Multi-pack digest"

    parts: List[str] = []
    parts.append(
        f"""
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RubixScout Weekly Grant Digest</title>
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#111827">
  <div style="max-width:820px;margin:0 auto;padding:28px">

    <div style="border:1px solid #e5e7eb;border-radius:24px;overflow:hidden;background:#ffffff;box-shadow:0 20px 60px rgba(0,0,0,0.08)">

      <div style="background:#dbeafe;border-bottom:1px solid #bfdbfe;padding:26px 28px">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse">
          <tr>
            <td style="vertical-align:top;padding-right:12px">
              <div style="height:42px;width:42px;border-radius:10px;background:#2563eb;color:#ffffff;font-weight:900;font-size:18px;line-height:42px;text-align:center;margin-bottom:14px;display:block">
                R
              </div>

              <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#475569">
                RubixScout · Weekly Grant Digest
              </div>

              <div style="margin-top:6px;font-size:24px;font-weight:900;line-height:1.15;color:#111827">
                {escape(hero_title)}
              </div>

              <div style="margin-top:8px;font-size:13px;color:#475569">
                {escape(hero_meta)}
              </div>
            </td>

            <td style="vertical-align:top;text-align:right;width:220px">
              <div style="display:inline-block;background:rgba(255,255,255,0.72);border:1px solid rgba(37,99,235,0.12);padding:10px 12px;border-radius:12px">
                <div style="font-size:12px;color:#64748b;font-weight:800">Pack</div>
                <div style="margin-top:2px;font-size:13px;font-weight:900;color:#111827;white-space:nowrap">
                  {escape(pack_display)}
                </div>
              </div>
            </td>
          </tr>
        </table>
      </div>

      <div style="padding:22px 22px 8px">

        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;padding:16px;box-shadow:0 4px 14px rgba(15,23,42,0.03)">
          <div style="font-size:14px;font-weight:900;color:#111827">
            Quick note 👋
          </div>
          <div style="margin-top:6px;font-size:13px;line-height:1.6;color:#374151">
            {escape(intro_text)}
          </div>
        </div>
"""
    )

    if single_pack_mode:
        pack_key, items = non_empty_sections[0] if non_empty_sections else (primary_pack, [])
        heading = f"{_pack_label(pack_key)} | best matches"
        _render_section(parts, heading, items)
    else:
        for section_key in ("DE", "EU", "UK", "AFRICA"):
            items = normalized.get(section_key, []) or []
            if items:
                _render_section(parts, f"{_pack_label(section_key)} | best matches", items)

        for section_key, items in normalized.items():
            if section_key in {"DE", "EU", "UK", "AFRICA"}:
                continue
            if items:
                _render_section(parts, f"{_pack_label(section_key)} | best matches", items)

    parts.append(
        """
      </div>
    </div>
  </div>
</body>
</html>
"""
    )

    return "".join(parts)


def write_outputs(
    sections: Union[Dict[str, List[dict]], List[dict], None],
    out_dir: str = "data",
    pack: Optional[str] = None,
):
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

    normalized = _normalize_sections(sections, pack=pack)

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
        "fit_score",
        "deadline_radar",
        "application_effort",
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

    html = render_digest_html(normalized, pack=pack)
    html_path.write_text(html, encoding="utf-8")

    return str(json_path), str(csv_path), str(html_path)