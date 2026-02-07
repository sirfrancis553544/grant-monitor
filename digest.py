from __future__ import annotations

from datetime import date
from html import escape
import json
import csv
from pathlib import Path


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

    # Why (optional, subtle)
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

    # Chips
    chips = []
    if funding:
        chips.append(
            '<span style="background:#EEF2FF;color:#3730A3;padding:4px 8px;'
            'border-radius:999px;font-size:12px;font-weight:600;display:inline-block;margin-right:6px">'
            f"Up to {escape(funding)}</span>"
        )
    if deadline:
        chips.append(
            '<span style="background:#ECFEFF;color:#155E75;padding:4px 8px;'
            'border-radius:999px;font-size:12px;font-weight:600;display:inline-block">'
            f"Deadline: {escape(deadline)}</span>"
        )

    chips_html = "".join(chips)

    why_html = ""
    if why_list:
        why_html = (
            "<div style='margin-top:8px;color:#6B7280;font-size:12px'>"
            "Why matched: "
            + ", ".join(escape(x) for x in why_list[:6])
            + "</div>"
        )

    return f"""
    <div style="border:1px solid #e5e7eb;border-radius:14px;padding:16px;margin-bottom:16px;background:#ffffff">
      <div style="font-size:16px;font-weight:750;margin-bottom:6px;line-height:1.25">
        <a href="{escape(url)}" target="_blank" rel="noreferrer" style="color:#111827;text-decoration:none">
          {escape(title_txt)}
        </a>
      </div>

      <div style="margin-bottom:10px">{chips_html}</div>

      <div style="color:#374151;font-size:14px;line-height:1.5;margin-bottom:12px">
        {escape(summary)}
      </div>

      <a href="{escape(url)}" target="_blank" rel="noreferrer"
         style="display:inline-block;padding:8px 14px;border-radius:10px;
                background:#2563EB;color:white;font-weight:650;
                font-size:14px;text-decoration:none">
        Open application →
      </a>

      {why_html}
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
            parts.append(render_card(g))
    else:
        parts.append(
            '<div style="border:1px solid #e5e7eb;border-radius:14px;padding:16px;background:#ffffff">'
            "No matches in this section.</div>"
        )


def render_digest_html(sections: dict):
    """
    sections example:
      {
        "DE": [...],
        "EU": [...],
        "UK": [...],
        "AFRICA": [...]
      }
    Renders Germany first, then a bonus block (EU + UK + Africa), each with its own heading.
    """
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
          <div style="font-size:18px;font-weight:800;margin:0">{escape(title)}</div>
          <div style="margin-top:6px;font-size:13px;color:#d1d5db">
            Total matches: {total} · Generated: {today}
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

    parts.append(
        """
        <div style="margin-top:18px;color:#6b7280;font-size:12px;text-align:center">
        </div>
      </div>
    </body>
    </html>
    """
    )

    return "".join(parts)


def write_outputs(sections: dict, out_dir="data"):
    """
    Writes:
      - digest.json (the full sections dict)
      - digest.csv  (flattened rows with a 'section' column)
      - digest.html (rendered from sections)
    Returns: (json_path, csv_path, html_path)
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "digest.json"
    csv_path = out / "digest.csv"
    html_path = out / "digest.html"

    # JSON (store sections)
    json_path.write_text(
        json.dumps(sections, ensure_ascii=False, indent=2),
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
        for section_key, items in (sections or {}).items():
            for g in (items or []):
                row = {k: g.get(k) for k in cols if k != "section"}
                row["section"] = section_key
                w.writerow(row)

    # HTML
    html = render_digest_html(sections)
    html_path.write_text(html, encoding="utf-8")

    return str(json_path), str(csv_path), str(html_path)