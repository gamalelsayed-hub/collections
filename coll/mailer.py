"""Sending files to reps by e-mail over SMTP (Zoho Mail, Gmail, Outlook 365 or a company server).

The password is kept on this computer only (Qt settings), never in the shared data folder.
Zoho: smtppro.zoho.com (business accounts) or smtp.zoho.com, port 465 SSL, with an App Password.
"""
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage

PRESETS = {
    "Zoho (حساب شركة)": ("smtppro.zoho.com", 465),
    "Zoho (حساب شخصي)": ("smtp.zoho.com", 465),
    "Gmail": ("smtp.gmail.com", 465),
    "Outlook / Office 365": ("smtp.office365.com", 587),
}


def _context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def connect(host, port, user, password):
    port = int(port)
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=_context(), timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls(context=_context())
    server.login(user, password)
    return server


def build_message(sender, sender_name, to, subject, body, attachments, cc=""):
    msg = EmailMessage()
    msg["From"] = f"{sender_name} <{sender}>" if sender_name else sender
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.set_content(body)
    for path in attachments:
        ctype, _ = mimetypes.guess_type(path)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(path))
    return msg


def send_all(config, messages, progress=None):
    """config: dict(host, port, user, password, sender_name, cc). messages: [(to, subject, body, [files])] —
    one separate e-mail per recipient. Returns [(to, ok, error)]."""
    results = []
    server = connect(config["host"], config["port"], config["user"], config["password"])
    try:
        for i, (to, subject, body, files) in enumerate(messages):
            try:
                server.send_message(build_message(config["user"], config.get("sender_name", ""), to, subject, body,
                                                  files, config.get("cc", "")))
                results.append((to, True, ""))
            except Exception as e:  # noqa: BLE001 - reported per recipient
                results.append((to, False, str(e)))
            if progress:
                progress(i + 1, len(messages))
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass
    return results
