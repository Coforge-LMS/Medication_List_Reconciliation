"""Run page: grouping, Other (x), three values, columns, interview states, footer, 404."""

import re
from datetime import datetime, timedelta, timezone

import pytest

from app.labels import DISCLAIMER
from app.version import __version__
from tests.app.conftest import INTERVIEW, make_run


def _section(html: str, heading: str) -> str:
    """The HTML of the <section> whose <h3> is heading."""
    match = re.search(rf"<h3>{re.escape(heading)}</h3>(.*?)</section>", html, re.S)
    assert match, f"no section {heading!r}"
    return match.group(1)


def test_findings_are_grouped_under_their_labels(client, serve_run):
    """Each type gets one section; both missing findings sit in the Missing section."""
    serve_run(make_run())
    html = client.get("/runs/7").text
    missing = _section(html, "Missing medication")
    assert "ibuprofen" in missing and "metoprolol" in missing
    assert "metformin" in _section(html, "Dosage mismatch")
    assert html.index("Dosage mismatch") < html.index("Missing medication")  # first-seen order


def test_unknown_type_renders_as_other(client, serve_run):
    """A type from a newer release is shown as Other (x) with its stored summary."""
    serve_run(make_run())
    section = _section(client.get("/runs/7").text, "Other (frequency_mismatch)")
    assert "FHIR frequency QD; pharmacy frequency BID." in section


def test_each_finding_shows_all_three_values(client, serve_run):
    """Findings have Patient-reported, FHIR and Pharmacy cells, with a dash when empty."""
    serve_run(make_run())
    missing = _section(client.get("/runs/7").text, "Missing medication")
    assert "<th>Patient-reported</th><th>FHIR</th><th>Pharmacy</th>" in missing
    assert re.search(
        r"<td>ibuprofen</td>.*?<td>200 mg</td>\s*<td>—</td>\s*<td>—</td>", missing, re.S
    )


def test_three_medication_columns_in_order(client, serve_run):
    """Compared records appear under Patient-reported, FHIR and Pharmacy columns."""
    serve_run(make_run())
    html = client.get("/runs/7").text
    compared = html[html.index("Medications compared") :]
    assert compared.index("Patient-reported") < compared.index("FHIR") < compared.index("Pharmacy")
    assert "metoprolol tartrate" in _section(compared, "FHIR")
    assert "1000 mg" in _section(compared, "Pharmacy")


def test_rejected_records_are_listed_with_reasons(client, serve_run):
    """Rejections show source, name and reason."""
    serve_run(make_run())
    html = client.get("/runs/7").text
    assert "warfarin" in html and "dose_amount: not a number" in html


@pytest.mark.parametrize(
    ("interview", "line"),
    [
        (INTERVIEW, "Intake taken 2026-10-01 by RN Okafor (patient)"),
        (INTERVIEW.model_copy(update={"no_medications": True}), "Patient reports no medications"),
        (None, "No intake history recorded"),
    ],
    ids=["taken", "no-medications", "none"],
)
def test_interview_line_states(client, serve_run, interview, line):
    """Each of the three interview states is shown on the run page."""
    serve_run(make_run(intake_interview=interview))
    assert f'<p id="interview">{line}</p>' in client.get("/runs/7").text


def test_footer_has_version_and_disclaimer(client, serve_run):
    """Every page footer carries the app version and the exact disclaimer."""
    serve_run(make_run())
    html = client.get("/runs/7").text
    assert DISCLAIMER in html and f"MedRec {__version__}" in html


def test_run_without_findings_says_so(client, serve_run):
    """A clean run states that no discrepancies were found."""
    serve_run(make_run(findings=[]))
    assert "No discrepancies found" in client.get("/runs/7").text


def test_missing_run_is_404_with_footer(client, serve_run):
    """An unknown run id gives a 404 page that still carries the disclaimer."""
    serve_run(None)
    response = client.get("/runs/999")
    assert response.status_code == 404
    assert "Run not found" in response.text and DISCLAIMER in response.text


def test_run_time_is_shown_in_utc(client, serve_run):
    """A started_at returned in another zone (+05:30) is converted before it's labelled UTC."""
    ist = timezone(timedelta(hours=5, minutes=30))
    serve_run(make_run(started_at=datetime(2026, 10, 30, 14, 5, tzinfo=ist)))
    assert "2026-10-30 08:35 UTC" in client.get("/runs/7").text
