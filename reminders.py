import sqlite3
from datetime import datetime, date

def _parse_iso(d: str):
    return datetime.strptime(d, "%Y-%m-%d").date()

def get_due_soon(db_path: str, days: int):
    today = date.today()
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT title, url, funder, deadline_date, summary, source
        FROM grants
        WHERE deadline_date IS NOT NULL
        """
    ).fetchall()
    conn.close()

    due = []
    for title, url, funder, deadline_date, summary, source in rows:
        if deadline_date in (None, "rolling"):
            continue
        try:
            dd = _parse_iso(deadline_date)
        except Exception:
            continue
        delta = (dd - today).days
        if 0 <= delta <= days:
            due.append((title, url, funder, deadline_date, summary, source))
    return due

def render_reminder_html(items, days: int):
    if not items:
        return None
    parts = [f"<h2>Deadlines in {days} days</h2>"]
    for title, url, funder, deadline, summary, source in items:
        parts.append(
            f"""
            <div style="margin:14px 0;padding:12px;border:1px solid #eee;border-radius:10px">
              <div><a href="{url}"><b>{title}</b></a></div>
              <div style="color:#555">Funder: {funder} · Source: {source} · Deadline: <b>{deadline}</b></div>
              <div style="margin-top:8px;color:#222">{(summary or "")[:450]}</div>
            </div>
            """
        )
    return "<html><body>" + "\n".join(parts) + "</body></html>"
