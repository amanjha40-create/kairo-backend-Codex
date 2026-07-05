"""HTML pages for employer magic-link review flow."""

from __future__ import annotations

from html import escape
from typing import Any


def render_review_page(
    *,
    contact_name: str,
    subject_full_name: str,
    subject_email: str | None,
    employer_name: str,
    job_title: str,
    start_date: str,
    end_date: str | None,
    relationship: str,
    documents: list[dict[str, Any]],
    token: str,
    base_url: str,
    already_responded: bool = False,
    existing_response: str = "pending",
    verification_kind: str = "employer-verification",
    headline: str = "Employment Verification",
    intro_noun: str = "employment",
    details_title: str = "Employment Details",
    primary_label: str = "Company",
    secondary_label: str = "Role",
) -> str:
    """Full review page — verifier sees credential details and can approve/decline/hold."""

    action_url = f"{base_url.rstrip('/')}/api/v1/public/{verification_kind}/{escape(token)}/respond"

    period = escape(start_date) + (" – " + escape(end_date) if end_date else " – Present")

    doc_rows = ""
    for d in documents:
        name = escape(d.get("original_filename", "Document"))
        size_bytes = d.get("byte_size", 0)
        size = f"{size_bytes // 1024} KB" if size_bytes else ""
        download = d.get("download_url", "")
        if download:
            doc_rows += f"""
            <div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #f3f4f6;">
              <span style="font-size:20px;">📄</span>
              <div style="flex:1;">
                <div style="font-size:13px;font-weight:500;color:#111827;">{name}</div>
                <div style="font-size:12px;color:#9ca3af;">{size}</div>
              </div>
              <a href="{escape(download)}" target="_blank" style="font-size:12px;font-weight:600;color:#2563eb;text-decoration:none;">View ↗</a>
            </div>"""
        else:
            doc_rows += f"""
            <div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #f3f4f6;">
              <span style="font-size:20px;">📄</span>
              <div style="flex:1;">
                <div style="font-size:13px;font-weight:500;color:#111827;">{name}</div>
                <div style="font-size:12px;color:#9ca3af;">{size}</div>
              </div>
            </div>"""

    docs_section = ""
    if documents:
        docs_section = f"""
        <div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px;margin-bottom:20px;">
          <h3 style="margin:0 0 12px;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#6b7280;">Documents · {len(documents)}</h3>
          {doc_rows}
        </div>"""

    if already_responded:
        label = {"confirmed": "Approved ✓", "declined": "Declined ✗", "on_hold": "On Hold ⏸"}.get(existing_response, "Responded")
        action_html = f"""
        <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:20px;text-align:center;">
          <p style="margin:0;font-size:15px;font-weight:600;color:#15803d;">Your response has been recorded: {escape(label)}</p>
          <p style="margin:8px 0 0;font-size:13px;color:#6b7280;">No further action needed.</p>
        </div>"""
    else:
        action_html = f"""
        <form method="POST" action="{action_url}" style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px;">
          <h3 style="margin:0 0 16px;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#6b7280;">Your response</h3>
          <textarea
            name="remarks"
            placeholder="Add remarks or notes (optional)"
            rows="3"
            style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;line-height:1.5;color:#111827;font-family:inherit;resize:vertical;margin-bottom:16px;"
          ></textarea>
          <div style="display:flex;gap:10px;flex-wrap:wrap;">
            <button name="action" value="confirmed" type="submit"
              style="flex:1;min-width:120px;padding:12px 16px;background:#059669;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;">
              ✓ Approve
            </button>
            <button name="action" value="on_hold" type="submit"
              style="flex:1;min-width:120px;padding:12px 16px;background:#d97706;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;">
              ⏸ Put on Hold
            </button>
            <button name="action" value="declined" type="submit"
              style="flex:1;min-width:120px;padding:12px 16px;background:#fff;color:#b91c1c;border:1px solid #fecaca;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;">
              ✗ Decline
            </button>
          </div>
        </form>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(headline)} — Kairo</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0;padding:0;background:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; }}
  </style>
</head>
<body>
  <div style="min-height:100vh;padding:24px 16px;">
    <div style="max-width:560px;margin:0 auto;">

      <!-- Header -->
      <div style="text-align:center;padding:24px 0 20px;">
        <p style="margin:0 0 4px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:#6b7280;">Kairo</p>
        <h1 style="margin:0;font-size:22px;font-weight:700;color:#111827;">{escape(headline)}</h1>
        <p style="margin:8px 0 0;font-size:14px;color:#6b7280;">
          <strong style="color:#111827;">{escape(subject_full_name)}</strong> has requested you to verify their {escape(intro_noun)}.
        </p>
      </div>

      <!-- Requester info -->
      <div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px;margin-bottom:16px;">
        <h3 style="margin:0 0 12px;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#6b7280;">Requester</h3>
        <div style="font-size:15px;font-weight:600;color:#111827;">{escape(subject_full_name)}</div>
        {f'<div style="font-size:13px;color:#6b7280;margin-top:2px;">{escape(subject_email)}</div>' if subject_email else ""}
        <div style="margin-top:8px;font-size:13px;color:#6b7280;">Your relationship: <strong style="color:#374151;">{escape(relationship)}</strong></div>
      </div>

      <!-- Employment details -->
      <div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px;margin-bottom:16px;">
        <h3 style="margin:0 0 12px;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#6b7280;">{escape(details_title)}</h3>
        <div style="display:grid;gap:8px;">
          <div><span style="font-size:12px;color:#9ca3af;">{escape(primary_label)}</span><div style="font-size:15px;font-weight:600;color:#111827;">{escape(employer_name)}</div></div>
          <div><span style="font-size:12px;color:#9ca3af;">{escape(secondary_label)}</span><div style="font-size:14px;color:#374151;">{escape(job_title)}</div></div>
          <div><span style="font-size:12px;color:#9ca3af;">Period</span><div style="font-size:14px;color:#374151;">{period}</div></div>
        </div>
      </div>

      <!-- Documents -->
      {docs_section}

      <!-- Privacy note -->
      <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;padding:16px;margin-bottom:20px;font-size:13px;color:#0369a1;line-height:1.6;">
        🔒 <strong>Privacy:</strong> No salary or personal financial information is shared. Your response is encrypted and audited.
      </div>

      <!-- Action form -->
      {action_html}

      <p style="text-align:center;margin-top:20px;font-size:12px;color:#9ca3af;">
        If you did not expect this request, you can safely ignore this page.
      </p>
    </div>
  </div>
</body>
</html>"""


def render_result_page(*, title: str, message: str, success: bool) -> str:
    accent = "#059669" if success else "#b91c1c"
    icon = "✓" if success else "!"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="min-height:100vh;padding:32px 16px;">
    <tr>
      <td align="center" valign="middle">
        <table role="presentation" width="100%" style="max-width:480px;background:#fff;border-radius:12px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
          <tr>
            <td align="center">
              <div style="width:56px;height:56px;border-radius:50%;background:{accent};color:#fff;font-size:28px;line-height:56px;font-weight:700;margin-bottom:16px;">{icon}</div>
              <h1 style="margin:0 0 12px;font-size:22px;color:#111827;">{escape(title)}</h1>
              <p style="margin:0;font-size:15px;line-height:1.6;color:#4b5563;">{escape(message)}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
