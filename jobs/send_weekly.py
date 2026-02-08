import os
from services.supabase_client import get_active_subscribers, log_send
from services.email_resend import send_email
import traceback


# IMPORTANT: this should be your existing generator that returns:
# (subject: str, html: str, item_count: int)
from jobs.generate_digest_for_pack import generate_digest_for_pack
# ---- simple .env loader (no dependencies) ----
from pathlib import Path
import os

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
    reply_to = os.environ.get("REPLY_TO")  # optional
    subs = get_active_subscribers()

    print(f"Found {len(subs)} active subscribers")

    for s in subs:
        sid = s["id"]
        email = s["email"]
        pack = (s.get("pack") or "DE").upper()

        try:
            subject, html, item_count = generate_digest_for_pack(pack)

            send_email(
                subject=subject,
                html=html,
                to_email=email,
                reply_to=reply_to,
            )

            log_send(sid, pack, item_count, status="ok", error=None)
            print(f"✅ Sent {pack} to {email} ({item_count} items)")

        except Exception as e:
            print(f"❌ Failed {pack} to {email}: {e}")
            print(traceback.format_exc())


if __name__ == "__main__":
    main()
