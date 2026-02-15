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

            # 2) Add unsubscribe footer (cheap + surgical)
            unsub_token = sub.get("unsubscribe_token")
            unsub_url = f"{app_url}/unsubscribe?token={unsub_token}" if app_url and unsub_token else None

            footer = ""
            if unsub_url:
                footer = f"""
                <div style="margin-top:18px;color:#6b7280;font-size:12px;text-align:center">
                  <a href="{unsub_url}" style="color:#6b7280;text-decoration:underline">Unsubscribe</a>
                </div>
                """

            # Only inject if HTML has a </body>. If not, just append.
            if "</body>" in html:
                html = html.replace("</body>", f"{footer}</body>")
            else:
                html = html + footer

            # 3) Send email
            send_email(
                subject=subject,
                html=html,
                to_email=email,
                reply_to=reply_to,
            )

            # 4) Log success
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
