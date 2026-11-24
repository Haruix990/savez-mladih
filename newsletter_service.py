from __future__ import annotations

import hashlib
import os
import secrets
from typing import Any
from urllib.parse import quote

import resend


EMAIL_PATTERN = r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"


def normalize_email(value: str) -> str:
    return value.strip().lower()


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_token() -> str:
    return secrets.token_urlsafe(48)


def public_host(request) -> str:
    return (os.environ.get("PUBLIC_HOST") or request.host_url).rstrip("/")


def escape_email_text(value: str) -> str:
    import html

    return html.escape(str(value or ""), quote=True)


def email_shell(title: str, content: str, unsubscribe_url: str | None = None) -> str:
    unsubscribe = ""
    if unsubscribe_url:
        unsubscribe = (
            '<p style="margin:18px 0 0;font-size:12px;color:#91a791;">'
            f'<a href="{escape_email_text(unsubscribe_url)}" style="color:#e2c36e;">Odjavi se sa newslettera</a>'
            "</p>"
        )

    return f"""<!doctype html>
<html lang="bs">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape_email_text(title)}</title></head>
<body style="margin:0;background:#07110a;font-family:Georgia,'Times New Roman',serif;color:#eef4ec;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#07110a;">
<tr><td align="center" style="padding:32px 12px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#102518;border:1px solid rgba(226,195,110,.28);border-radius:18px;overflow:hidden;">
<tr><td style="padding:24px;border-bottom:1px solid rgba(226,195,110,.18);">
<div style="color:#e2c36e;font-family:Arial,sans-serif;font-size:13px;font-weight:bold;letter-spacing:.12em;text-transform:uppercase;">SAVEZ MLADIH · ZELENE BERETKE</div>
</td></tr>
<tr><td style="padding:32px 24px;font-size:16px;line-height:1.65;">
{content}{unsubscribe}
</td></tr>
<tr><td style="padding:20px 24px;background:#09150d;color:#91a791;font-family:Arial,sans-serif;font-size:12px;">
Savez mladih “Stari Grad — Zelene Beretke”<br>
<a href="{escape_email_text(os.environ.get('PUBLIC_HOST', ''))}" style="color:#e2c36e;">Posjeti našu web stranicu</a>
</td></tr>
</table></td></tr></table>
</body></html>"""


def send_resend(
    email: str,
    subject: str,
    html: str,
    unsubscribe_url: str | None = None,
) -> tuple[bool, str | None, str | None]:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        return False, None, "RESEND_API_KEY nije konfigurisan."

    sender = os.environ.get("RESEND_FROM", "Savez Mladih <onboarding@resend.dev>").strip()
    resend.api_key = api_key
    try:
        headers: dict[str, str] = {}
        if unsubscribe_url:
            headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        result = resend.Emails.send({
            "from": sender,
            "to": email,
            "subject": subject,
            "html": html,
            "headers": headers,
        })
        provider_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
        return True, provider_id, None
    except Exception as exc:
        return False, None, str(exc)

