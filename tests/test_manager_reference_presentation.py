"""Presentation-only contract and accessibility guards for the script-free page."""

from html.parser import HTMLParser

import pytest

from app.api.v1.routes.employment_references import PAGE_HEADERS
from app.integrations.email.manager_reference_page import render_manager_page, render_manager_result


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))


def page(**overrides):
    return render_manager_page(
        dict(
            status="invited",
            candidate_name="Synthetic Candidate",
            job_title="Engineer",
            employer_name="Synthetic Employer",
            **overrides,
        )
    )


def test_form_names_required_fields_and_limits_are_unchanged():
    nodes = Elements(page()).nodes
    fields = {
        a["name"]: (tag, a) for tag, a in nodes if tag in {"input", "select", "textarea", "button"}
    }
    assert set(fields) == {
        "directly_managed",
        "working_relationship",
        "period_start",
        "period_end",
        "overall_performance",
        "reliability_ownership",
        "communication",
        "teamwork_collaboration",
        "work_together_again",
        "key_strength",
        "additional_comments",
        "attested",
        "action",
    }
    assert {a["name"] for _, a in nodes if "required" in a} == {
        "directly_managed",
        "working_relationship",
        "work_together_again",
    }
    assert fields["key_strength"][1]["maxlength"] == "1000"
    assert fields["additional_comments"][1]["maxlength"] == "2000"
    assert fields["attested"][1]["value"] == "yes"
    assert [(a["method"], a["action"]) for tag, a in nodes if tag == "form"] == [
        ("post", "respond-form")
    ]
    assert [(a["value"], "formnovalidate" in a) for tag, a in nodes if tag == "button"] == [
        ("submit", False),
        ("decline", True),
    ]


@pytest.mark.parametrize(
    "name",
    [
        "overall_performance",
        "reliability_ownership",
        "communication",
        "teamwork_collaboration",
    ],
)
def test_rating_radio_semantics_preserve_values_and_optional_blank(name):
    nodes = Elements(page()).nodes
    options = [a for tag, a in nodes if tag == "input" and a.get("name") == name]
    assert [a["value"] for a in options] == ["1", "2", "3", "4", "5", ""]
    assert all(a["type"] == "radio" and "required" not in a for a in options)
    assert [a["value"] for a in options if "checked" in a] == [""]
    assert page().count('aria-describedby="rating-help"') == 4


def test_shell_has_embedded_brand_only_and_no_script_or_external_asset():
    html = page()
    nodes = Elements(html).nodes
    assert "<script" not in html and "onclick=" not in html and "onsubmit=" not in html
    assert all(
        a.get("src", "").startswith("data:image/png;base64,") for t, a in nodes if t == "img"
    )
    assert 'alt="KairoID"' in html and "data:font/ttf;base64," in html
    assert 'content="no-referrer"' in html
    assert "https://" not in html
    assert {x.strip() for x in PAGE_HEADERS["Content-Security-Policy"].split(";")} == {
        "default-src 'none'",
        "style-src 'unsafe-inline'",
        "img-src data:",
        "font-src data:",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    }


def test_safe_context_escapes_markup_and_omits_unapproved_fields():
    html = render_manager_page(
        {
            "status": "invited",
            "candidate_name": '<img onerror="alert(1)">',
            "job_title": "<script>role</script>",
            "employer_name": "<b>company</b>",
            "token": "PRIVATE_CAPABILITY",
            "id": "PRIVATE_ID",
            "email": "PRIVATE_EMAIL",
            "phone": "PRIVATE_PHONE",
            "hr_comments": "PRIVATE_COMMENT",
        }
    )
    for value in (
        "PRIVATE_CAPABILITY",
        "PRIVATE_ID",
        "PRIVATE_EMAIL",
        "PRIVATE_PHONE",
        "PRIVATE_COMMENT",
    ):
        assert value not in html
    assert "<script>" not in html and "&lt;script&gt;role&lt;/script&gt;" in html
    assert "&lt;img onerror=&quot;alert(1)&quot;&gt;" in html


@pytest.mark.parametrize("status", ["completed", "declined", "needs_review"])
def test_terminal_links_share_shell_without_second_submission(status):
    html = render_manager_page({"status": status})
    assert "Reference already submitted" in html and 'role="status"' in html
    assert "<form" not in html and "<button" not in html
    assert 'alt="KairoID"' in html and "No further action is required." in html


def test_error_and_success_share_accessible_shell_without_private_error_details():
    success = render_manager_result("Thank you. Your response has been recorded.")
    error = render_manager_result(
        "Use your browser's Back button to correct the form.",
        title="Check your response",
        error=True,
    )
    assert 'role="status"' in success and "Reference submitted" in success
    assert 'role="alert"' in error and 'aria-labelledby="result-title"' in error
    assert "<form" not in error and "No further action" not in error
    assert render_manager_result("<script>unsafe</script>").count("<script>") == 0


def test_labels_hints_mobile_and_keyboard_structure():
    html = page()
    nodes = Elements(html).nodes
    ids = {a["id"] for _, a in nodes if "id" in a}
    assert len(ids) == len([a for _, a in nodes if "id" in a])
    for _, attrs in nodes:
        for reference in attrs.get("aria-describedby", "").split():
            assert reference in ids
        if "for" in attrs:
            assert attrs["for"] in ids
    assert "Skip to content" in html and 'id="main"' in html
    assert 'name="viewport"' in html and "max-width: 768px" in html
    assert ":focus-visible" in html and "forced-colors: active" in html
    assert "overflow-x: hidden" not in html
