"""Shared presentation primitives for Kairo transactional emails."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape


BRAND_NAME = "Kairo"
SUPPORT_EMAIL = "support@kairoid.com"
FOOTER_TEXT = "Kairo — Verify once. Trusted everywhere."


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


def render_html(*, title: str, content: str) -> str:
    safe_title = html_escape(title)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
</head>
<body style="margin:0;padding:0;background:#f3f5f4;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f5f4;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:14px;overflow:hidden;">
        <tr><td style="padding:30px 32px 12px;">
          <p style="margin:0 0 10px;font-size:13px;font-weight:700;color:#1f6f68;text-transform:uppercase;letter-spacing:.08em;">{BRAND_NAME}</p>
          <h1 style="margin:0 0 20px;font-size:24px;line-height:1.3;color:#17211f;">{safe_title}</h1>
          {content}
        </td></tr>
        <tr><td style="padding:20px 32px 28px;border-top:1px solid #e7ecea;">
          <p style="margin:0 0 8px;font-size:12px;line-height:1.5;color:#697572;">Need help? Contact <a href="mailto:{SUPPORT_EMAIL}" style="color:#1f6f68;">{SUPPORT_EMAIL}</a>.</p>
          <p style="margin:0;font-size:12px;line-height:1.5;color:#697572;">{FOOTER_TEXT}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def with_text_footer(body: str) -> str:
    return f"{body.rstrip()}\n\nNeed help? Contact {SUPPORT_EMAIL}.\n\n{FOOTER_TEXT}"
