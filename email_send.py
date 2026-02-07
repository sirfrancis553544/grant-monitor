import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate

def send_html_email(subject: str, html: str):
    from_email = os.environ["GM_EMAIL"]
    to_email = os.environ.get("GM_TO", from_email)

    app_pw = os.environ["GM_APP_PASSWORD"]
    app_pw = app_pw.replace("\u00a0", " ")
    app_pw = "".join(app_pw.split())

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.ehlo()
        s.starttls()
        print("SMTP login as:", from_email, "to:", to_email, "pw_len:", len(app_pw))
        s.login(from_email, app_pw)
        s.sendmail(from_email, [to_email], msg.as_string())
