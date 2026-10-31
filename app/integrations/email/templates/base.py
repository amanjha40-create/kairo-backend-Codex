"""Shared presentation primitives for KairoID transactional emails."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

BRAND_NAME = "KairoID"
SUPPORT_EMAIL = "contact@kairoid.com"
WEBSITE_URL = "https://kairoid.com"
LOGO_URL = "https://app.kairoid.com/assets/kairoid-logo-primary-Di249jMg.png"
TAGLINE = "Trust that travels."
LEGAL_TEXT = "© 2026 Aletheon Innovations Private Limited. All rights reserved."
FOOTER_TEXT = f"{BRAND_NAME} — {TAGLINE}"


@dataclass(frozen=True, slots=True)
class TransactionalEmailContent:
    subject: str
    html_body: str
    text_body: str


def html_escape(value: object) -> str:
    return escape(str(value), quote=True)


def action_link(*, label: str, url: str) -> str:
    safe_label = html_escape(label)
    safe_url = html_escape(url)
    return (
        '<table role="presentation" cellspacing="0" cellpadding="0" style="margin:24px 0;">'
        "<tr><td>"
        f'<a href="{safe_url}" style="display:inline-block;padding:13px 24px;'
        "background:#1f6f68;color:#ffffff;text-decoration:none;font-weight:600;"
        f'border-radius:8px;">{safe_label}</a>'
        "</td></tr></table>"
    )


def render_html(*, title: str, content: str, preheader: str | None = None) -> str:
    safe_title = html_escape(title)
    safe_preheader = html_escape(preheader or title)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
</head>
<body style="margin:0;padding:0;background:#f3f6f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;mso-hide:all;">{safe_preheader}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;background:#f3f6f6;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:600px;background:#ffffff;border:1px solid #dce8e7;border-radius:16px;overflow:hidden;">
        <tr><td style="height:6px;background:#0aa8a5;font-size:0;line-height:0;">&nbsp;</td></tr>
        <tr><td style="padding:30px 32px 14px;">
          <img src="{LOGO_URL}" width="180" alt="KairoID" style="display:block;width:180px;max-width:100%;height:auto;border:0;margin:0 0 28px;" />
          <h1 style="margin:0 0 20px;font-size:26px;line-height:1.3;color:#0a2442;">{safe_title}</h1>
          {content}
        </td></tr>
        <tr><td style="padding:22px 32px 28px;border-top:1px solid #e4eceb;background:#f9fbfb;">
          <p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#5d6f71;">Need help? Contact <a href="mailto:{SUPPORT_EMAIL}" style="color:#087f7d;text-decoration:underline;">{SUPPORT_EMAIL}</a>.</p>
          <p style="margin:0 0 4px;font-size:13px;font-weight:700;line-height:1.5;color:#0a2442;">{BRAND_NAME}</p>
          <p style="margin:0 0 8px;font-size:12px;line-height:1.5;color:#697b7d;">{TAGLINE}</p>
          <p style="margin:0 0 8px;font-size:12px;line-height:1.5;"><a href="{WEBSITE_URL}" style="color:#087f7d;text-decoration:underline;">kairoid.com</a></p>
          <p style="margin:0;font-size:11px;line-height:1.5;color:#7b898b;">{LEGAL_TEXT}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def with_text_footer(body: str) -> str:
    return (
        f"{body.rstrip()}\n\nNeed help? Contact {SUPPORT_EMAIL}.\n\n"
        f"{BRAND_NAME}\n{TAGLINE}\nkairoid.com\n\n{LEGAL_TEXT}"
    )
