# jobs/send_weekly.py

import os
import traceback
from pathlib import Path

from services.supabase_client import get_active_subscribers, log_send
from services.email_resend import send_email
from jobs.generate_digest_for_pack import generate_digest_for_pack


# ---- simple .env loader (no dependencies) ----
def _load_dotenv():
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()
# ---------------------------------------------


def _build_footer(app_url: str, unsub_url: str | None) -> str:
    """Branded footer. Only ONE unsubscribe link (the functional one)."""
    view_site = app_url or "#"

    unsub_btn = ""
    if unsub_url:
        unsub_btn = f"""
          <a href="{unsub_url}" target="_blank" rel="noreferrer"
             style="display:inline-block;padding:8px 12px;border-radius:10px;
                    border:1px solid rgba(37,99,235,0.25);background:#eff6ff;color:#1d4ed8;
                    font-weight:900;font-size:12px;text-decoration:none">
            Unsubscribe
          </a>
        """

    return f"""
    <div style="max-width:820px;margin:0 auto;padding:0 22px 28px">
      <div style="margin-top:18px;border-top:1px solid #e5e7eb;padding-top:14px">
        <div style="font-size:13px;color:#111827;font-weight:900;margin-bottom:6px">RubixScout</div>

        <div style="font-size:12px;line-height:1.6;color:#6b7280">
          You’re receiving this weekly digest because you subscribed to grant alerts.
        </div>

        <div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
          <a href="{view_site}" target="_blank" rel="noreferrer"
             style="display:inline-block;padding:8px 12px;border-radius:10px;
                    border:1px solid #e5e7eb;background:#ffffff;color:#111827;
                    font-weight:900;font-size:12px;text-decoration:none">
            View site
          </a>
          {unsub_btn}
        </div>

        <div style="margin-top:10px;font-size:12px;line-height:1.6;color:#6b7280">
          Tip: Reply with keywords like “AI”, “Climate”, or “Berlin” to improve future matches.
        </div>
      </div>
    </div>
    """


def _inject_before_body_close(html: str, insert_html: str) -> str:
    """Insert footer before </body> if present; else append."""
    if not insert_html:
        return html
    lower = html.lower()
    idx = lower.rfind("</body>")
    if idx != -1:
        return html[:idx] + insert_html + html[idx:]
    return html + insert_html


def main():
    reply_to = os.environ.get("REPLY_TO")  # optional (must be valid format)
    app_url = os.environ.get("APP_URL", "").rstrip("/")

    subs = get_active_subscribers()
    print(f"Found {len(subs)} active subscribers")

    for sub in subs:
        sid = sub["id"]
        email = sub["email"]
        pack = (sub.get("pack") or "DE").upper()

        try:
            # 1) Generate digest
            subject, html, item_count = generate_digest_for_pack(pack)

            # 2) Build ONE functional unsubscribe URL
            unsub_token = sub.get("unsubscribe_token")
            unsub_url = f"{app_url}/unsubscribe?token={unsub_token}" if app_url and unsub_token else None

            # 3) Add branded footer (no extra/unworking unsub links)
            footer = _build_footer(app_url=app_url, unsub_url=unsub_url)
            html = _inject_before_body_close(html, footer)

            # 4) Send email
            # NOTE: Gmail's one-click unsubscribe is best done via headers in email_resend.py.
            # This file keeps only ONE unsubscribe link in the HTML body.
            send_email(
                subject=subject,
                html=html,
                to_email=email,
                reply_to=reply_to,
            )

            # 5) Log success
            log_send(subscriber_id=sid, pack=pack, item_count=item_count, status="ok", error=None)
            print(f"✅ Sent {pack} to {email} ({item_count} items)")

        except Exception as e:
            # Log failure (and keep going)
            try:
                log_send(subscriber_id=sid, pack=pack, item_count=0, status="failed", error=str(e)[:800])
            except Exception:
                pass

            print(f"❌ Failed {pack} to {email}: {e}")
            print(traceback.format_exc())


if __name__ == "__main__":
    main()