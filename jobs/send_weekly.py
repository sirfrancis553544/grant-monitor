# jobs/send_weekly.py

import os
import re
import traceback
from pathlib import Path
from typing import List, Dict, Any
from datetime import date

from services.supabase_client import (
    get_active_subscribers,
    log_send,
    fetch_grants_for_pack,
    has_grants_for_pack,
    get_sent_counts,
    bump_sent,
)

# Optional: weekly history table helper (if you added it later)
try:
    from services.supabase_client import add_send_history  # type: ignore
except Exception:
    add_send_history = None  # noqa: N816

from services.email_resend import send_email
from digest import render_digest_html  # uses your digest.py renderer


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


def week_key_today() -> str:
    # e.g. "2026-W08"
    d = date.today()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _pick_unsent(
    subscriber_id: str,
    grants: List[Dict[str, Any]],
    max_items: int = 12,
    max_repeat: int = 2,
) -> List[Dict[str, Any]]:
    """
    Allow a grant to be emailed at most `max_repeat` times to the same subscriber.
    Assumes each grant has a 'fingerprint'.
    """
    fps = [g.get("fingerprint") for g in grants if g.get("fingerprint")]
    if not fps:
        return []

    counts = get_sent_counts(subscriber_id, fps)

    out: List[Dict[str, Any]] = []
    for g in grants:
        fp = g.get("fingerprint")
        if not fp:
            continue
        if counts.get(fp, 0) >= max_repeat:
            continue
        out.append(g)
        if len(out) >= max_items:
            break
    return out


def _pack_meta(pack: str) -> Dict[str, str]:
    pack = (pack or "").strip().upper()

    mapping = {
        "DE": {"label": "Germany", "flag": "🇩🇪"},
        "EU": {"label": "European Union", "flag": "🇪🇺"},
        "UK": {"label": "United Kingdom", "flag": "🇬🇧"},
        "AFRICA": {"label": "Africa", "flag": "🌍"},
    }

    if pack in mapping:
        return mapping[pack]

    return {"label": pack or "Selected pack", "flag": "📦"}


def _subject(pack: str) -> str:
    label = _pack_meta(pack)["label"]
    return f"RubixScout — Weekly Grant Digest ({label})"


def _footer_html(app_url: str, unsub_url: str) -> str:
    return f"""
    <div style="margin-top:24px;padding:16px 0;border-top:1px solid #e5e7eb;color:#6b7280;font-size:12px;text-align:center">
      <div style="font-weight:800;color:#111827;margin-bottom:6px">RubixScout</div>
      <div>You’re receiving this weekly digest because you subscribed to grant alerts.</div>
      <div style="margin-top:10px">
        <a href="{app_url}" style="color:#2563eb;text-decoration:none;font-weight:800">View site</a>
        <span style="color:#d1d5db;margin:0 10px">•</span>
        <a href="{unsub_url}" style="color:#2563eb;text-decoration:none;font-weight:800">Unsubscribe</a>
      </div>
      <div style="margin-top:10px">Tip: Reply with keywords like “AI”, “Climate”, or “Berlin” to improve future matches.</div>
    </div>
    """


def _strip_existing_footer(html: str) -> str:
    """
    Remove older/static footer blocks so only the final tokenized footer remains.
    This is intentionally defensive because older digest templates may include
    legacy footer HTML already baked into render_digest_html().
    """
    if not html:
        return html

    patterns = [
        # Remove any block containing "Manage subscription"
        r'<div[^>]*>.*?Manage subscription.*?</div>\s*</div>?',

        # Remove any block containing both RubixScout and "New funding opportunities every week."
        r'<div[^>]*>.*?RubixScout.*?New funding opportunities every week\..*?</div>\s*</div>?',

        # Remove any block containing "You’re receiving this weekly digest..."
        r'<div[^>]*>.*?You[’\']re receiving this weekly digest because you subscribed to grant alerts\..*?</div>\s*</div>?',

        # Remove footer-like sections that contain View site / Unsubscribe together
        r'<div[^>]*>.*?View site.*?Unsubscribe.*?</div>\s*</div>?',
    ]

    cleaned = html
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)

    return cleaned


def _replace_pack_labels(html: str, pack: str) -> str:
    """
    Temporary sender-layer fix for hardcoded Germany strings inside the digest body.
    Best long-term fix: make digest.py fully dynamic.
    """
    if not html:
        return html

    meta = _pack_meta(pack)
    label = meta["label"]
    flag = meta["flag"]

    replacements = [
        ("Pack Germany", f"Pack {label}"),
        ("🇩🇪 Germany", f"{flag} {label}"),
        ("Germany — best matches", f"{flag} {label} — best matches"),
        (">Germany — best matches<", f">{flag} {label} — best matches<"),
        (">Pack Germany<", f">Pack {label}<"),
        ("(Germany)", f"({label})"),
    ]

    for old, new in replacements:
        html = html.replace(old, new)

    # Extra fallback replacement for standalone visible "Germany" labels
    # Be conservative: only replace if it's clearly visible label text, not URLs.
    html = re.sub(
        r'(?<=>)\s*Germany\s*(?=<)',
        label,
        html,
        flags=re.IGNORECASE,
    )

    return html


def _inject_footer(html: str, footer: str) -> str:
    if "</body>" in html:
        return html.replace("</body>", f"{footer}</body>")
    return html + footer


def main():
    reply_to = os.environ.get("REPLY_TO")
    app_url = os.environ.get("APP_URL", "").rstrip("/")

    subs = get_active_subscribers()
    print(f"Found {len(subs)} active subscribers")

    for sub in subs:
        sid = sub["id"]
        email = sub["email"]
        pack = (sub.get("pack") or "").strip().upper()

        try:
            # 1) Validate subscriber pack
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

            # 2) Validate pack has grants available
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

            # 3) Pull candidates from Supabase (freshest first)
            candidates = fetch_grants_for_pack(pack, limit=200)

            # 4) Choose items excluding grants already sent too often
            chosen = _pick_unsent(sid, candidates, max_items=12, max_repeat=2)

            if not chosen:
                print(f"⚠️ No eligible grants for {email} ({pack}). Skipping send.")
                log_send(
                    subscriber_id=sid,
                    pack=pack,
                    item_count=0,
                    status="skipped",
                    error="no_eligible_items",
                )
                continue

            # 5) Render email HTML
            html = render_digest_html(chosen, pack=pack)
            subject = _subject(pack)

            # 6) Fix body pack labels and remove legacy footer(s)
            html = _replace_pack_labels(html, pack)
            html = _strip_existing_footer(html)

            # 7) Inject final footer with correct unsubscribe token
            unsub_token = sub.get("unsubscribe_token")
            unsub_url = (
                f"{app_url}/unsubscribe?token={unsub_token}"
                if app_url and unsub_token
                else None
            )

            if unsub_url:
                footer = _footer_html(app_url=app_url, unsub_url=unsub_url)
                html = _inject_footer(html, footer)

            # 8) Send email
            send_email(
                subject=subject,
                html=html,
                to_email=email,
                reply_to=reply_to,
            )

            # 9) Track what was actually sent
            sent_fps = [g["fingerprint"] for g in chosen if g.get("fingerprint")]
            bump_sent(sid, sent_fps)

            # 10) Optional weekly history
            if add_send_history and sent_fps:
                wk = week_key_today()
                try:
                    add_send_history(
                        subscriber_id=sid,
                        pack=pack,
                        fingerprints=sent_fps,
                        week_key=wk,
                    )
                except Exception as e:
                    print("⚠️ add_send_history failed:", str(e))

            # 11) Log success
            log_send(
                subscriber_id=sid,
                pack=pack,
                item_count=len(chosen),
                status="ok",
                error=None,
            )
            print(f"✅ Sent {pack} to {email} ({len(chosen)} items)")

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