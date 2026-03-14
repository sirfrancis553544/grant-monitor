import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing env var: {name}")
    return value


def send_email(
    subject: str,
    html: str,
    to_email: str,
    reply_to: Optional[str] = None,
) -> Dict[str, Any]:
    api_key = _env("RESEND_API_KEY")
    email_from = _env("EMAIL_FROM")

    payload: Dict[str, Any] = {
        "from": email_from,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }

    if reply_to:
        payload["reply_to"] = reply_to

    data = json.dumps(payload).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "RubixScout/1.0 (+https://rubixscout.com) Python",
    }

    req = urllib.request.Request(
        url="https://api.resend.com/emails",
        data=data,
        method="POST",
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Resend error HTTP {e.code}: {err}") from e