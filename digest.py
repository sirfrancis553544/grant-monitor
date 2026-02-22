from __future__ import annotations

from datetime import date
from html import escape
import json
import csv
from pathlib import Path
from typing import Any, Dict, List, Union


def _fmt_money(max_amt, currency="€"):
    """Format a max amount into a compact label like €250k / €1.2M."""
    if max_amt in (None, "", 0, "0"):
        return None
    try:
        v = float(max_amt)
    except Exception:
        return None

    if v >= 1_000_000:
        return f"{currency}{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{currency}{int(v/1_000)}k"
    return f"{currency}{int(v)}"


def _fmt_deadline(d):
    """Normalize deadline values for chips."""
    if not d:
        return "OPEN"
    ds = str(d).strip()
    if ds.lower() == "rolling":
        return "ROLLING"
    return ds


def render_card(g):
    deadline = _fmt_deadline(g.get("deadline_date"))
    funding = _fmt_money(g.get("funding_amount_max"))

    why = g.get("_why")
    if isinstance(why, str):
        why_list = [why.strip()] if why.strip() else []
    elif isinstance(why, (list, tuple)):
        why_list = [str(x).strip() for x in why if str(x).strip()]
    else:
        why_list = []

    url = (g.get("url") or "#").strip()
    title_txt = (g.get("title") or "").strip()
    summary = (g.get("summary") or "").strip()
    if len(summary) > 280:
        summary = summary[:280].rsplit(" ", 1)[0] + "…"

    # pack label (optional)
    pack = (g.get("section_label") or "").strip()  # if you ever pass it in
    if not pack:
        # fallback: show nothing; section header already exists
        pack = ""

    # chips line
    chips = []
    if funding:
        chips.append(f"<span style='font-weight:800'>Up to {escape(funding)}</span>")
    if deadline:
        chips.append(f"Deadline: <span style='font-weight:800'>{escape(deadline)}</span>")
    chips_html = " <span style='color:#d1d5db;margin:0 8px'>•</span> ".join(chips) if chips else ""

    why_html = ""
    if why_list:
        why_html = (
            "<div style='margin-top:10px;font-size:12px;line-height:1.5;color:#6b7280'>"
            "<span style='font-weight:800;color:#374151'>Why matched:</span> "
            + ", ".join(escape(x) for x in why_list[:6])
            + "</div>"
        )

    return f"""
<div style="border:1px solid #e5e7eb;border-radius:18px;overflow:hidden;background:#ffffff;margin-bottom:16px">
  <!-- IMAGE HEADER -->
  <div style="
    position:relative;
    padding:16px;
    background:
      radial-gradient(120px 80px at 85% 30%, rgba(37,99,235,0.10), transparent 60%),
      radial-gradient(140px 90px at 15% 70%, rgba(16,185,129,0.08), transparent 60%),
      linear-gradient(135deg,#ffffff 0%,#f7f8fb 55%,#f3f4f6 100%);
  ">
    <div style="
      position:absolute; inset:0;
      background-image:
        linear-gradient(to right, rgba(17,24,39,0.06) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(17,24,39,0.06) 1px, transparent 1px);
      background-size:40px 40px;
      opacity:0.35;
    "></div>

    <div style="position:relative;z-index:2">
      <span style="display:inline-block;font-size:12px;font-weight:700;color:#111827;background:rgba(255,255,255,0.90);border:1px solid #e5e7eb;border-radius:999px;padding:6px 10px">
        🔒 Subscribers only
      </span>
    </div>

    <div style="position:relative;z-index:2;margin-top:12px;font-size:18px;font-weight:900;line-height:1.25;color:#111827">
      <a href="{escape(url)}" target="_blank" rel="noreferrer" style="color:#111827;text-decoration:none">
        {escape(title_txt)}
      </a>
    </div>

    {"<div style='position:relative;z-index:2;margin-top:10px;font-size:12px;color:#374151'>" + chips_html + "</div>" if chips_html else ""}
  </div>

  <!-- BODY -->
  <div style="padding:16px">
    <div style="font-size:14px;line-height:1.6;color:#374151">
      {escape(summary)}
    </div>

    <div style="margin-top:12px">
      <a href="{escape(url)}" target="_blank" rel="noreferrer"
         style="display:inline-block;padding:10px 14px;border-radius:12px;background:#2563EB;color:#ffffff;font-weight:800;font-size:14px;text-decoration:none">
        Apply now →
      </a>
    </div>

    {why_html}
  </div>
</div>
"""


def _render_section(parts, heading, items, subheading=None):
    parts.append(
        f"""
        <div style="margin:18px 0 10px;font-size:14px;color:#374151;font-weight:800">
          {escape(heading)}
        </div>
        """
    )
    if subheading:
        parts.append(
            f"""
            <div style="color:#6B7280;font-size:14px;margin:-4px 0 14px">
              {escape(subheading)}
            </div>
            """
        )

    if items:
        for g in items:
            # Guard: only render dict-like grants
            if isinstance(g, dict):
                parts.append(render_card(g))
    else:
        parts.append(
            '<div style="border:1px solid #e5e7eb;border-radius:14px;padding:16px;background:#ffffff">'
            "No matches in this section.</div>"
        )


def _normalize_sections(
    sections: Union[Dict[str, List[dict]], List[dict], None]
) -> Dict[str, List[dict]]:
    """
    Backwards-compatible normalizer:
    - If sections is a dict => return as-is (safe defaults)
    - If sections is a list => wrap into a single section (DE by default)
    """
    if sections is None:
        return {"DE": []}

    if isinstance(sections, list):
        # Single-pack mode: wrap into a dict so the existing renderer works
        return {"DE": sections}

    # Ensure values are lists (avoid None)
    out: Dict[str, List[dict]] = {}
    for k, v in (sections or {}).items():
        out[str(k)] = v or []
    return out


def render_digest_html(sections):
    """
    Accepts either:
      - dict: {"DE":[...], "EU":[...], ...}
      - list: [ ... ]   (single-pack mode)
    Renders Germany first, then a bonus block (EU + UK + Africa).
    """
    sections = _normalize_sections(sections)

    today = date.today().isoformat()
    de = sections.get("DE", []) or []
    eu = sections.get("EU", []) or []
    uk = sections.get("UK", []) or []
    af = sections.get("AFRICA", []) or []

    title = f"Grant Digest ({today})"
    total = len(de) + len(eu) + len(uk) + len(af)

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
        <div style="background:#111827;color:#ffffff;border-radius:16px;padding:18px 18px">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
    <div>
      <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#93c5fd">
        RubixScout · Weekly Grant Digest
      </div>
      <div style="margin-top:6px;font-size:20px;font-weight:900;line-height:1.1">
        Your matches for {today}
      </div>
      <div style="margin-top:8px;font-size:13px;color:#d1d5db">
        {total} opportunities · Prioritized by fit · Source links included
      </div>
    </div>

    <div style="text-align:right;min-width:140px">
      <div style="display:inline-block;background:rgba(255,255,255,0.10);border:1px solid rgba(255,255,255,0.16);padding:8px 10px;border-radius:12px">
        <div style="font-size:12px;color:#e5e7eb;font-weight:800">Pack</div>
        <div style="margin-top:2px;font-size:13px;font-weight:900;color:#ffffff">Germany + Bonus</div>
      </div>
    </div>
  </div>
</div>

<div style="margin-top:14px;background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;padding:14px">
  <div style="font-size:14px;font-weight:900;color:#111827">How to use this email</div>
  <div style="margin-top:6px;font-size:13px;line-height:1.6;color:#374151">
    Skim the first lines, open the source link, and apply fast. “Why matched” explains why an opportunity was included.
  </div>
</div>
    """
    )

    # Germany first
    _render_section(parts, "🇩🇪 Germany — best matches", de)

    # Bonus block (only show if any exist)
    if eu or uk or af:
        parts.append(
            """
        <h2 style="margin:32px 0 8px;font-size:20px">
          🌍 Bonus: EU + UK + Africa startup funding
        </h2>
        <div style="color:#6B7280;font-size:14px;margin-bottom:14px">
          Additional opportunities outside Germany that may still fit your company.
        </div>
            """
        )
        if eu:
            _render_section(parts, "🇪🇺 EU", eu)
        if uk:
            _render_section(parts, "🇬🇧 UK", uk)
        if af:
            _render_section(parts, "🌍 Africa", af)

        # Footer (always)
    parts.append(
        f"""
        <div style="margin-top:24px;border-top:1px solid #e5e7eb;padding-top:16px;color:#6b7280;font-size:12px;line-height:1.6">
          <div style="font-weight:900;color:#111827">RubixScout</div>

          <div style="margin-top:6px">
            You’re receiving this weekly digest because you subscribed to grant alerts.
          </div>

          <div style="margin-top:10px">
            <a href="https://rubixscout.com" style="color:#2563EB;text-decoration:none;font-weight:800">View site</a>
            <span style="color:#d1d5db;margin:0 8px">•</span>
            <a href="https://rubixscout.com/unsubscribe" style="color:#2563EB;text-decoration:none;font-weight:800">Unsubscribe</a>
          </div>

          <div style="margin-top:10px;color:#9ca3af">
            Tip: Reply with keywords like “AI”, “Climate”, or “Berlin” to improve future matches.
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
      - digest.json (the normalized sections dict)
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

    # JSON (store normalized sections)
    json_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # CSV (stable columns, flattened + section)
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

    # HTML
    html = render_digest_html(normalized)
    html_path.write_text(html, encoding="utf-8")

    return str(json_path), str(csv_path), str(html_path)
