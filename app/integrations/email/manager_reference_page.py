"""Accessible, script-free reference form. No third-party assets or tracking."""

# ruff: noqa: E501 -- Embedded HTML/CSS templates.

from html import escape


def shell(body):
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>KairoID professional reference</title><style>
    :root{color-scheme:light dark}body{font:1.1rem Georgia,serif;line-height:1.6;max-width:42rem;margin:auto;padding:1.5rem;background:#f5f3ed;color:#20352e}h1{line-height:1.2}fieldset{border:1px solid #75857b;margin:1.4rem 0;padding:1rem}label{display:block;margin:.8rem 0}input,select,textarea,button{font:inherit;padding:.6rem;max-width:100%;box-sizing:border-box}select,textarea,input[type=date]{display:block;width:100%}button{margin:.5rem 0;min-height:48px}a{color:inherit}:focus-visible{outline:3px solid #a36211;outline-offset:3px}@media(prefers-color-scheme:dark){body{background:#18231f;color:#f5f3ed}}
    </style><main>"""
        + body
        + "</main></html>"
    )


def render_manager_result(message):
    return shell(f"<h1>Professional reference</h1><p role='status'>{escape(message)}</p>")


def select(name, label, options, required=True):
    values = "".join(
        f'<option value="{escape(value)}">{escape(text)}</option>' for value, text in options
    )
    return f'<label>{escape(label)}<select name="{name}" {"required" if required else ""}><option value="">Choose an answer</option>{values}</select></label>'


def render_manager_page(context):
    if context["status"] in {"completed", "declined", "needs_review"}:
        return render_manager_result("Your response has already been recorded. Thank you.")
    body = f"<h1>A short professional reference</h1><p>For <strong>{escape(context['candidate_name'])}</strong>, {escape(context['job_title'])} at {escape(context['employer_name'])}.</p><p>No account needed. Answers are confidential and are not displayed to the candidate or on their public Passport. Authorized verification reviewers may view them.</p><form method='post' action='respond-form'><fieldset><legend>Working relationship</legend>"
    body += select(
        "directly_managed",
        "Did you directly manage this person?",
        [("yes", "Yes"), ("no", "No"), ("cannot_confirm", "Cannot confirm")],
    )
    body += select(
        "working_relationship",
        "Working relationship",
        [
            ("direct_manager", "Direct reporting manager"),
            ("former_direct_manager", "Former direct reporting manager"),
            ("other", "Other / cannot confirm"),
        ],
    )
    body += '<label>From (optional)<input type="date" name="period_start"></label><label>To (optional)<input type="date" name="period_end"></label></fieldset><fieldset><legend>Professional reference</legend><p>If you directly managed this person, please rate each attribute. 1 = Poor, 2 = Below expectations, 3 = Meets expectations, 4 = Strong, 5 = Exceptional. Otherwise leave these blank.</p>'
    for name, label in (
        ("overall_performance", "Overall performance"),
        ("reliability_ownership", "Reliability / ownership"),
        ("communication", "Communication"),
        ("teamwork_collaboration", "Teamwork / collaboration"),
    ):
        body += select(name, label, [(str(i), str(i)) for i in range(1, 6)], required=False)
    body += select(
        "work_together_again",
        "Would you work with this person again?",
        [("yes", "Yes"), ("no", "No"), ("prefer_not_to_answer", "Prefer not to answer")],
    )
    body += '<label>Key strength (optional)<textarea name="key_strength" maxlength="1000" rows="2"></textarea></label><label>Additional comments (optional)<textarea name="additional_comments" maxlength="2000" rows="3"></textarea></label></fieldset><label><input type="checkbox" name="attested" value="yes"> I confirm that I directly managed/worked with this person in the capacity described above. Required only when confirming direct management.</label><button type="submit" name="action" value="submit">Submit reference</button> <button type="submit" name="action" value="decline" formnovalidate>Decline to provide a reference</button></form>'
    return shell(body)
