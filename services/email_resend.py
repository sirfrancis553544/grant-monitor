import os
import json
import urllib.request


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def send_email(subject: str, html: str, to_email: str, reply_to: str | None = None) -> dict:
    api_key = _env("RESEND_API_KEY")
    email_from = _env("EMAIL_FROM")

    payload = {
        "from": email_from,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url="https://api.resend.com/emails",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "RubixScout/1.0 (+https://rubixscout.com) Python",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Resend error HTTP {e.code}: {err}") from e
