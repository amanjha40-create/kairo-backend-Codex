"""Script-free reference presentation, sharing the external HR portal's visual language."""

# ruff: noqa: E501 -- Embedded HTML templates.

from base64 import b64encode
from functools import lru_cache
from html import escape
from pathlib import Path

ASSETS = Path(__file__).with_name("reference_assets")


@lru_cache
def brand_assets():
    logo = b64encode((ASSETS / "kairoid-logo-primary.png").read_bytes()).decode("ascii")
    fonts = ""
    for weight, name in ((400, "regular"), (600, "semibold")):
        font = b64encode((ASSETS / f"jakarta-{name}.ttf").read_bytes()).decode("ascii")
        fonts += f"@font-face{{font-family:Jakarta;font-style:normal;font-weight:{weight};font-display:swap;src:url(data:font/ttf;base64,{font}) format('truetype')}}"
    return logo, fonts + (ASSETS / "reference.css").read_text()


def icon(kind):
    paths = {
        "lock": '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
        "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
        "notice": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 3v.01"/>',
    }
    return (
        '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        + paths[kind]
        + "</svg>"
    )


def shell(body):
    logo, styles = brand_assets()
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>KairoID professional reference</title><style>{styles}</style></head><body>
    <a class="skip-link" href="#main">Skip to content</a>
    <header><div class="header-inner"><img class="logo" src="data:image/png;base64,{logo}" alt="KairoID" width="76" height="20"><span class="secure-label">{icon("lock")} Secure reference link</span></div></header>
    <main id="main">{body}</main>
    <footer>Only submit information you are authorized to provide. Never forward this private link.</footer>
    </body></html>"""


def render_manager_result(message, *, title="Reference submitted", error=False):
    role = "alert" if error else "status"
    symbol = icon("notice" if error else "check")
    note = "" if error else '<p class="result-note">No further action is required.</p>'
    return shell(
        f'<section class="card result" role="{role}" aria-labelledby="result-title"><span class="result-icon">{symbol}</span><h1 id="result-title">{escape(title)}</h1><p>{escape(message)}</p>{note}</section>'
    )


def select(name, label, options, required=True):
    values = "".join(
        f'<option value="{escape(value)}">{escape(text)}</option>' for value, text in options
    )
    return f'<div class="field"><label for="{name}">{escape(label)}</label><select id="{name}" name="{name}" {"required" if required else ""}><option value="">Choose an answer</option>{values}</select></div>'


def rating(name, label):
    meanings = ("Poor", "Below expectations", "Meets expectations", "Strong", "Exceptional")
    values = "".join(
        f'<label class="rating-option"><input type="radio" name="{name}" value="{i}"><span aria-hidden="true">{i}</span><span class="sr-only">{i} - {meaning}</span></label>'
        for i, meaning in enumerate(meanings, 1)
    )
    return f'''<fieldset class="rating" aria-describedby="rating-help"><legend>{escape(label)}</legend><div class="rating-scale">{values}</div><div class="rating-caption" aria-hidden="true"><span>1 - Poor</span><span>5 - Exceptional</span></div><label class="unrated"><input type="radio" name="{name}" value="" checked> Not rated</label></fieldset>'''


def render_manager_page(context):
    if context["status"] in {"completed", "declined", "needs_review"}:
        return render_manager_result(
            "Your response has already been recorded. Thank you.",
            title="Reference already submitted",
        )
    body = f"""<section class="intro" aria-labelledby="page-title"><p class="eyebrow">Reporting manager reference</p><h1 id="page-title">Professional reference</h1><p>You've been invited to provide a professional reference for this person's employment. Your response helps verify their professional history.</p>
    <div class="candidate-context"><p class="context-label">Candidate</p><h2>{escape(context["candidate_name"])}</h2><p>{escape(context["job_title"])} at {escape(context["employer_name"])}</p></div>
    <p class="privacy">No account needed. Answers are confidential and are not displayed to the candidate or on their public Passport. Authorized verification reviewers may view them.</p></section>
    <form method='post' action='respond-form'>
    <fieldset class="card"><legend>Relationship</legend><p class="section-copy">Tell us how you worked together.</p>"""
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
    body += """<div class="date-fields"><div class="field"><label for="period_start">From <span class="optional">(optional)</span></label><input id="period_start" type="date" name="period_start"></div><div class="field"><label for="period_end">To <span class="optional">(optional)</span></label><input id="period_end" type="date" name="period_end"></div></div></fieldset>
    <fieldset class="card"><legend>Professional assessment</legend><p id="rating-help" class="section-copy">If you directly managed this person, please rate each attribute. Otherwise leave these blank.</p><p class="scale-key">1 Poor &middot; 2 Below expectations &middot; 3 Meets expectations &middot; 4 Strong &middot; 5 Exceptional</p>"""
    for name, label in (
        ("overall_performance", "Overall performance"),
        ("reliability_ownership", "Reliability / ownership"),
        ("communication", "Communication"),
        ("teamwork_collaboration", "Teamwork / collaboration"),
    ):
        body += rating(name, label)
    body += '</fieldset><fieldset class="card"><legend>Additional feedback</legend>'
    body += select(
        "work_together_again",
        "Would you work with this person again?",
        [("yes", "Yes"), ("no", "No"), ("prefer_not_to_answer", "Prefer not to answer")],
    )
    body += """<div class="field"><label for="key_strength">Key strength <span class="optional">(optional)</span></label><textarea id="key_strength" name="key_strength" maxlength="1000" rows="2" aria-describedby="strength-limit"></textarea><p id="strength-limit" class="field-hint">Up to 1,000 characters.</p></div><div class="field"><label for="additional_comments">Additional comments <span class="optional">(optional)</span></label><textarea id="additional_comments" name="additional_comments" maxlength="2000" rows="3" aria-describedby="comments-limit"></textarea><p id="comments-limit" class="field-hint">Up to 2,000 characters.</p></div></fieldset>
    <fieldset class="card confirmation"><legend>Confirmation</legend><label class="attestation"><input type="checkbox" name="attested" value="yes" aria-describedby="attestation-help"><span>I confirm that I directly managed/worked with this person in the capacity described above.</span></label><p id="attestation-help" class="field-hint">Required only when confirming direct management.</p></fieldset>
    <div class="actions"><button class="primary" type="submit" name="action" value="submit">Submit reference</button><button class="secondary" type="submit" name="action" value="decline" formnovalidate>Decline to provide a reference</button></div></form>"""
    return shell(body)
