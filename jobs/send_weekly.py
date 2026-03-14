# jobs/send_weekly.py

from __future__ import annotations

import os
import traceback
from datetime import date
from pathlib import Path
from typing import Optional

from jobs.generate_digest_for_pack import generate_digest_for_pack
from services.email_resend import send_email
from services.supabase_client import get_active_subscribers, has_grants_for_pack, log_send

# Optional: weekly history table helper
try:
    from services.supabase_client import add_send_history  # type: ignore
except Exception:
    add_send_history = None  # noqa: N816


def _load_dotenv() -> None:
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


def week_key_today() -> str:
    d = date.today()
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _footer_html(app_url: str, unsub_url: Optional[str]) -> str:
    links_html = ""

    if app_url and unsub_url:
        links_html = f"""
        <div style="margin-top:10px">
          <a href="{app_url}" style="color:#2563eb;text-decoration:none;font-weight:800">View site</a>
          <span style="color:#d1d5db;margin:0 10px">•</span>
          <a href="{unsub_url}" style="color:#2563eb;text-decoration:none;font-weight:800">Unsubscribe</a>
        </div>
        """
    elif app_url:
        links_html = f"""
        <div style="margin-top:10px">
          <a href="{app_url}" style="color:#2563eb;text-decoration:none;font-weight:800">View site</a>
        </div>
        """
    elif unsub_url:
        links_html = f"""
        <div style="margin-top:10px">
          <a href="{unsub_url}" style="color:#2563eb;text-decoration:none;font-weight:800">Unsubscribe</a>
        </div>
        """

    return f"""
    <div style="margin-top:24px;padding:16px 0;border-top:1px solid #e5e7eb;color:#6b7280;font-size:12px;text-align:center">
      <div style="font-weight:800;color:#111827;margin-bottom:6px">RubixScout</div>
      <div>You’re receiving this weekly digest because you subscribed to grant alerts.</div>
      {links_html}
      <div style="margin-top:10px">Tip: Reply with keywords like “AI”, “Climate”, or “Berlin” to improve future matches.</div>
    </div>
    """


def _inject_footer(html: str, footer: str) -> str:
    if not html:
        return footer

    if "</body>" in html:
        return html.replace("</body>", f"{footer}</body>")

    return html + footer


def _build_unsub_url(app_url: str, unsub_token: Optional[str]) -> Optional[str]:
    app_url = (app_url or "").rstrip("/")
    token = (unsub_token or "").strip()

    if not app_url or not token:
        return None

    return f"{app_url}/unsubscribe?token={token}"


def main() -> None:
    reply_to = (os.environ.get("REPLY_TO") or "").strip() or None
    app_url = (os.environ.get("APP_URL") or "").rstrip("/")

    subs = get_active_subscribers()
    print(f"Found {len(subs)} active subscribers")

    for sub in subs:
        sid = sub["id"]
        email = sub["email"]
        pack = (sub.get("pack") or "").strip().upper()

        try:
            if not pack:
                print(f"⚠️ Subscriber {email} has no pack. Skipping.")
                log_send(
                    subscriber_id=sid,
                    pack="UNKNOWN",
                    item_count=0,
                    status="skipped",
                    error="missing_pack",
                )
                continue

            if not has_grants_for_pack(pack):
                print(f"⚠️ No grants found for subscriber pack {pack} ({email}). Skipping.")
                log_send(
                    subscriber_id=sid,
                    pack=pack,
                    item_count=0,
                    status="skipped",
                    error="no_grants_for_pack",
                )
                continue

            subject, html, item_count, sent_fps = generate_digest_for_pack(
                pack=pack,
                subscriber_id=sid,
                max_repeat=2,
            )

            if item_count <= 0 or not html:
                print(f"⚠️ No eligible grants for {email} ({pack}). Skipping send.")
                log_send(
                    subscriber_id=sid,
                    pack=pack,
                    item_count=0,
                    status="skipped",
                    error="no_eligible_items",
                )
                continue

            unsub_url = _build_unsub_url(app_url, sub.get("unsubscribe_token"))
            footer = _footer_html(app_url=app_url, unsub_url=unsub_url)
            html = _inject_footer(html, footer)

            send_email(
                subject=subject,
                html=html,
                to_email=email,
                reply_to=reply_to,
            )

            if add_send_history and sent_fps:
                try:
                    add_send_history(
                        subscriber_id=sid,
                        pack=pack,
                        fingerprints=sent_fps,
                        week_key=week_key_today(),
                    )
                except Exception as history_err:
                    print(f"⚠️ add_send_history failed for {email}: {history_err}")

            log_send(
                subscriber_id=sid,
                pack=pack,
                item_count=item_count,
                status="ok",
                error=None,
            )
            print(f"✅ Sent {pack} to {email} ({item_count} items)")

        except Exception as e:
            try:
                log_send(
                    subscriber_id=sid,
                    pack=pack or "UNKNOWN",
                    item_count=0,
                    status="failed",
                    error=str(e)[:800],
                )
            except Exception:
                pass

            print(f"❌ Failed {pack or 'UNKNOWN'} to {email}: {e}")
            print(traceback.format_exc())


if __name__ == "__main__":
    main()