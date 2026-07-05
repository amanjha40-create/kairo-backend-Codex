"""HTML + plain-text employer verification emails with confirm / decline links."""

from __future__ import annotations

from email.message import EmailMessage

from html import escape


def build_employer_verification_email(
    *,
    app_name: str,
    to_email: str,
    from_email: str,
    contact_name: str,
    subject_full_name: str,
    employer_name: str,
    job_title: str,
    relationship: str,
    review_url: str,
    expires_hours: int,
) -> EmailMessage:
    """Multipart email — single review link opens full details page in the browser."""

    safe_contact = escape(contact_name)
    safe_subject = escape(subject_full_name)
    safe_employer = escape(employer_name)
    safe_title = escape(job_title)
    safe_relationship = escape(relationship)

    subject = f"{app_name} — employment verification request"
    plain = (
        f"Hello {contact_name},\n\n"
        f"You have been asked to verify employment details for {subject_full_name} "
        f"at {employer_name} ({job_title}).\n"
        f"Your relationship to them: {relationship}.\n\n"
        f"Review and respond:\n{review_url}\n\n"
        f"This link expires in {expires_hours} hours.\n"
        f"If you did not expect this email, you can ignore it."
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(app_name)} — employment verification</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f6f8;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
          <tr>
            <td style="padding:28px 32px 8px;">
              <p style="margin:0 0 8px;font-size:13px;color:#6b7280;text-transform:uppercase;letter-spacing:0.04em;">{escape(app_name)}</p>
              <h1 style="margin:0 0 16px;font-size:22px;line-height:1.3;color:#111827;">Employment verification</h1>
              <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#374151;">Hello <strong>{safe_contact}</strong>,</p>
              <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#374151;">
                <strong>{safe_subject}</strong> has asked you to verify their employment as
                <strong>{safe_title}</strong> at <strong>{safe_employer}</strong>.
              </p>
              <p style="margin:0 0 24px;font-size:14px;line-height:1.5;color:#6b7280;">
                Your relationship: {safe_relationship}
              </p>
              <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 24px;">
                <tr>
                  <td>
                    <a href="{escape(review_url)}" style="display:inline-block;padding:14px 28px;background:#2563eb;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;border-radius:8px;">Review &amp; Respond →</a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#9ca3af;">
                Link expires in {expires_hours} hours. If the button does not work, copy this URL:
              </p>
              <p style="margin:0;font-size:12px;word-break:break-all;color:#6b7280;">{escape(review_url)}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 28px;border-top:1px solid #f3f4f6;">
              <p style="margin:0;font-size:12px;line-height:1.5;color:#9ca3af;">
                If you did not expect this message, you can safely ignore it.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")
    return msg
