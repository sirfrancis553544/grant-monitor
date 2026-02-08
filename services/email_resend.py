import os
import requests

def send_resend_email(subject: str, html: str, to_email: str):
    api_key = os.environ["RESEND_API_KEY"]
    email_from = os.environ["EMAIL_FROM"]

    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "from": email_from,
            "to": [to_email],
            "subject": subject,
            "html": html,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
