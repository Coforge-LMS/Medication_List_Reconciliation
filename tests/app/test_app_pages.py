"""Run page: grouping, Other (x), three values, columns, interview states, footer, 404."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import OperationalError

from app.labels import DISCLAIMER, NLM_ATTRIBUTION
from app.version import __version__
from contract import Finding
from db import repo
from tests.app.conftest import INTERVIEW, make_run, record


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
    section = _section(client.get("/runs/7").text, "Other (route_mismatch)")
    assert "FHIR route oral; pharmacy route topical." in section


def test_each_finding_shows_all_three_values(client, serve_run):
    """Findings have Patient-reported, FHIR and Pharmacy cells, with a dash when empty.

    The summary sits under the medication's name rather than in a column of its own.
    """
    serve_run(make_run())
    missing = _section(client.get("/runs/7").text, "Missing medication")
    assert "<th>Medication</th><th>Patient-reported</th><th>FHIR</th><th>Pharmacy</th>" in missing
    assert re.search(
        r'<td class="med">ibuprofen<div class="note">[^<]+</div></td>\s*'
        r"<td>200 mg</td>\s*<td>—</td>\s*<td>—</td>",
        missing,
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


def _db_down(session, run_id):
    """Stand-in for repo.get_run when Postgres refuses connections."""
    raise OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))


def test_database_down_is_a_503_page(client, serve_run, monkeypatch):
    """With the app database unreachable the run page is a readable 503, not a traceback."""
    serve_run(None)
    monkeypatch.setattr(repo, "get_run", _db_down)
    response = client.get("/runs/7")
    assert response.status_code == 503
    assert "Database unavailable" in response.text and DISCLAIMER in response.text


def test_database_down_is_a_503_json_for_the_api(client, serve_run, monkeypatch):
    """The JSON API reports the same outage as JSON."""
    serve_run(None)
    monkeypatch.setattr(repo, "get_run", _db_down)
    response = client.get("/api/runs/7")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_stylesheet_is_served_and_linked(client, serve_run):
    """Pages link the bundled stylesheet, and it is served as CSS with no external host."""
    serve_run(make_run())
    html = client.get("/runs/7").text
    assert f'href="/static/app.css?v={__version__}"' in html
    assert 'class="topbar"' in html and "<footer>" in html
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "http://" not in response.text and "https://" not in response.text


def test_run_page_marks_each_finding_type_for_styling(client, serve_run):
    """Summary cards and finding groups carry a per-type class; unknown types get one too."""
    serve_run(make_run())
    html = client.get("/runs/7").text
    assert 'class="card finding-group type-missing"' in html
    assert 'class="card finding-group type-route_mismatch"' in html
    assert '<span class="count">2</span> Missing medication' in html


def test_run_page_links_back_to_the_patient(client, serve_run):
    """The run page links to the patient and their history by FHIR id."""
    serve_run(make_run())
    html = client.get("/runs/7").text
    assert 'href="/patients/2178"' in html and 'href="/patients/2178/history"' in html


def test_run_without_an_interview_says_no_data_for_the_patient_side(client, serve_run):
    """No interview isn't an empty list, so the column doesn't imply records were checked."""
    serve_run(make_run(intake_interview=None, intake=[]))
    column = _section(client.get("/runs/7").text, "Patient-reported")
    assert "No data" in column and "No accepted records" not in column


def test_run_with_a_no_medications_interview_keeps_its_wording(client, serve_run):
    """The patient was asked and reports nothing, so this is not missing data."""
    interview = INTERVIEW.model_copy(update={"no_medications": True})
    serve_run(make_run(intake_interview=interview, intake=[]))
    column = _section(client.get("/runs/7").text, "Patient-reported")
    assert "No accepted records" in column and "No data" not in column


@pytest.mark.parametrize("run_id", ["99999999999999999999", "9223372036854775808", "0", "-1"])
@pytest.mark.parametrize("path", ["/runs/{}", "/runs/{}/report.pdf", "/api/runs/{}"])
def test_impossible_run_ids_are_404_without_querying(client, serve_run, monkeypatch, path, run_id):
    """Ids outside the bigint range never reach Postgres, which would raise an error."""
    serve_run(None)

    def unexpected(session, requested):
        """Fail if the database would have been queried."""
        pytest.fail(f"queried run {requested}")

    monkeypatch.setattr(repo, "get_run", unexpected)
    assert client.get(path.format(run_id)).status_code == 404


def test_frequency_finding_has_its_own_label_on_the_run_page(client, serve_run):
    """A frequency mismatch is a known type now, with its stored plain wording."""
    finding = Finding(
        discrepancy_type="frequency_mismatch",
        medication="sertraline",
        summary="FHIR frequency once daily; pharmacy frequency twice daily.",
        fhir_value="once daily",
        pharmacy_value="twice daily",
    )
    serve_run(make_run(findings=[finding]))
    section = _section(client.get("/runs/7").text, "Frequency mismatch")
    assert "FHIR frequency once daily; pharmacy frequency twice daily." in section
    assert "<td>once daily</td>" in section and "<td>twice daily</td>" in section


def test_footer_has_the_nlm_attribution(client, serve_run):
    """RxNorm data requires NLM's attribution, in its exact words, on every page."""
    serve_run(None)
    assert NLM_ATTRIBUTION in client.get("/runs/999").text


def test_each_known_finding_type_has_its_own_accent(client):
    """Types are told apart at a glance; only an unknown type falls back to neutral."""
    css = client.get("/static/app.css").text
    for discrepancy_type in ("duplicate", "missing", "dosage_mismatch", "frequency_mismatch"):
        assert f".type-{discrepancy_type} {{ --type:" in css
    variables = ("duplicate", "missing", "mismatch", "frequency", "other")
    colours = [re.search(rf"--{name}: (#\w+);", css).group(1) for name in variables]
    assert len(set(colours)) == len(variables)


def test_pages_stay_light_whatever_the_system_theme(client):
    """One light theme only, so a Mac in dark mode doesn't turn the pages near-black."""
    css = client.get("/static/app.css").text
    assert "color-scheme: light;" in css and "prefers-color-scheme" not in css


def test_rejected_records_section_is_left_out_when_there_are_none(client, serve_run):
    """An empty Rejected records heading is noise; findings only point there when it exists."""
    serve_run(make_run(rejected=[]))
    assert "Rejected records" not in client.get("/runs/7").text


def _with_brand():
    """A run whose pharmacy list holds a brand RxNorm matched to its ingredient."""
    brand = record("pharmacy", "Zoloft", "50").model_copy(
        update={"normalized_name": "sertraline", "rxcui": "82728"}
    )
    return make_run(pharmacy=[brand])


def test_medication_table_labels_a_brand_with_its_ingredient(client, serve_run):
    """The match is visible beside the source's own name, with the plain record unlabelled."""
    serve_run(_with_brand())
    html = client.get("/runs/7").text
    assert 'Zoloft<div class="matched">Matched as: sertraline</div>' in html
    assert html.count('class="matched"') == 1


def test_matched_label_is_escaped(client, serve_run):
    """The ingredient comes from data, so it can't inject markup into the page."""
    brand = record("pharmacy", "Zoloft", "50").model_copy(
        update={"normalized_name": "<b>sertraline</b>", "rxcui": "82728"}
    )
    serve_run(make_run(pharmacy=[brand]))
    html = client.get("/runs/7").text
    assert "Matched as: &lt;b&gt;sertraline&lt;/b&gt;" in html
    assert "<b>sertraline" not in html


def _agreeing(**overrides):
    """A run whose one medication is in all three sources with no finding."""
    return make_run(
        intake=[record("intake", "metformin", "0.5", "g", "twice a day")],
        fhir=[record("fhir", "metformin", "500", frequency="BID")],
        pharmacy=[record("pharmacy", "metformin", "500", frequency="twice daily")],
        intake_interview=INTERVIEW,
        rejected=[],
        **overrides,
    )


def test_run_page_shows_medications_with_no_differences(client, serve_run):
    """The tile and section appear beside findings, with each source's wording."""
    serve_run(
        _agreeing(findings=[Finding(discrepancy_type="missing", medication="x", summary="y")])
    )
    html = client.get("/runs/7").text
    assert '<span class="count">1</span> No differences' in html
    assert 'id="no-differences"' in html
    for value in ("0.5 g, twice a day", "500 mg, BID", "500 mg, twice daily"):
        assert f"<td>{value}</td>" in html
    assert "no source is treated as correct" in html


def test_run_with_no_findings_still_lists_what_agrees(client, serve_run):
    """A clean patient gets the plain statement and the list, with no findings tiles."""
    serve_run(_agreeing(findings=[]))
    html = client.get("/runs/7").text
    assert "No discrepancies found" in html
    assert 'id="no-differences"' in html
    assert '<ul class="summary">' not in html


def test_run_page_omits_the_section_when_nothing_agrees(client, serve_run):
    """The default run's medications all have findings or a missing source."""
    serve_run(make_run())
    html = client.get("/runs/7").text
    assert "no-differences" not in html and "No differences" not in html


def test_summary_tiles_jump_to_their_sections(client, serve_run):
    """Each tile links to its finding group, so a count leads straight to the findings."""
    serve_run(make_run())
    html = client.get("/runs/7").text
    assert '<a href="#group-missing"><span class="count">2</span> Missing medication</a>' in html
    assert 'id="group-missing"' in html and 'id="group-route_mismatch"' in html


def test_script_is_served_from_the_app_with_no_external_host(client, serve_run):
    """The busy-button script ships with the app, like the stylesheet."""
    serve_run(make_run())
    assert f'src="/static/app.js?v={__version__}"' in client.get("/runs/7").text
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "http://" not in response.text and "https://" not in response.text


def test_motion_has_a_reduced_motion_path(client):
    """Page transitions and tile entrances are switched off for people who ask for less motion."""
    css = client.get("/static/app.css").text
    reduced = css.split("@media (prefers-reduced-motion: reduce)")[1]
    assert "@view-transition { navigation: none; }" in reduced
